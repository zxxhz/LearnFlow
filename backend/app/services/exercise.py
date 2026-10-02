"""练习服务（PRD §5.10）：按知识点出题 + 代码题自动判定 + 概念题 LLM 评分。"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Document, Exercise, ExerciseAttempt, KnowledgePoint
from app.models.exercise import ATTEMPT_GRADED, EXERCISE_CODE, EXERCISE_CONCEPT
from app.schemas.exercise import (
    ConceptGrade,
    ExerciseAttemptOut,
    ExerciseDraftSet,
    ExerciseOut,
)
from app.services.execution.runner import run_code
from app.services.llm import create_adapter_from_settings, get_llm_temperature
from app.services.prompt import render_prompt
from app.services.review import get_preferences
from app.services.sections_text import get_section_text

logger = logging.getLogger(__name__)

EXERCISE_TITLE_MAX = 200


def normalize_output(s: str) -> str:
    """stdout 判定用归一化：统一换行、去行尾空白、去首尾空行。"""
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


async def _kp_context(db: AsyncSession, kp: KnowledgePoint) -> tuple[Document, list[str]]:
    document = await db.get(Document, kp.document_id)
    if document is None:
        raise LookupError("知识点所属章节不存在")
    texts = []
    for sid in json.loads(kp.section_ids) if kp.section_ids else []:
        text = await get_section_text(db, document, sid)
        if text:
            texts.append(text)
    return document, texts


async def delete_kp_exercises(db: AsyncSession, kp_ids: list[str]) -> None:
    """删除知识点的全部练习与作答（出题替换 / 章节重建级联共用）。"""
    if not kp_ids:
        return
    old = (
        await db.scalars(select(Exercise).where(Exercise.knowledge_point_id.in_(kp_ids)))
    ).all()
    old_ids = [e.id for e in old]
    if old_ids:
        await db.execute(
            ExerciseAttempt.__table__.delete().where(ExerciseAttempt.exercise_id.in_(old_ids))
        )
        await db.execute(Exercise.__table__.delete().where(Exercise.id.in_(old_ids)))


async def generate_for_kp(
    db: AsyncSession, knowledge_point_id: str, language: str, count: int
) -> list[Exercise]:
    """为知识点出题（替换旧题）。count<=0 时取偏好 exercises_per_kp。"""
    kp = await db.get(KnowledgePoint, knowledge_point_id)
    if kp is None:
        raise LookupError("知识点不存在")
    document, texts = await _kp_context(db, kp)
    course = await db.get(Course, document.course_id)

    if count <= 0:
        prefs = await get_preferences(db)
        count = max(1, min(4, int(prefs.get("exercises_per_kp", 2))))

    system = render_prompt(
        "exercise_gen",
        COURSE_TOPIC=course.topic if course else "",
        COURSE_TITLE=course.title if course else "",
        KP_TITLE=kp.title,
        KP_SUMMARY=kp.summary or "（无摘要）",
        SECTION_TEXTS="\n\n".join(texts) or "（无教材原文）",
        LANGUAGE=language,
        COUNT=str(count),
    )
    adapter = await create_adapter_from_settings(db, scene="generation")
    temperature = await get_llm_temperature(db)
    drafts: ExerciseDraftSet = await adapter.chat_json(
        [{"role": "system", "content": system}], ExerciseDraftSet, temperature=temperature
    )

    await delete_kp_exercises(db, [kp.id])
    saved: list[Exercise] = []
    for item in drafts.exercises:
        if not item.is_complete():
            logger.warning("skip incomplete exercise draft: kind=%s title=%s", item.kind, item.title)
            continue
        row = Exercise(
            knowledge_point_id=kp.id,
            document_id=kp.document_id,
            kind=item.kind,
            title=item.title[:EXERCISE_TITLE_MAX],
            task_md=item.task,
            language=item.resolved_language(language) if item.kind == EXERCISE_CODE else "",
            skeleton_code=item.skeleton_code if item.kind == EXERCISE_CODE else "",
            expected_output=item.expected_output if item.kind == EXERCISE_CODE else "",
            reference_answer=item.reference_answer if item.kind == EXERCISE_CONCEPT else "",
        )
        db.add(row)
        saved.append(row)
    if not saved:
        raise ValueError("生成的练习题不完整，请重试")
    await db.commit()
    return saved


async def list_for_document(db: AsyncSession, document_id: str) -> list[ExerciseOut]:
    """文档下全部练习，附知识点标题与最近一次作答。"""
    exercises = (
        await db.scalars(
            select(Exercise)
            .where(Exercise.document_id == document_id)
            .order_by(Exercise.knowledge_point_id, Exercise.created_at)
        )
    ).all()
    ex_ids = [e.id for e in exercises]
    kp_ids = {e.knowledge_point_id for e in exercises}
    kp_titles: dict[str, str] = {}
    if kp_ids:
        for k in (
            await db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids)))
        ).all():
            kp_titles[k.id] = k.title
    latest: dict[str, ExerciseAttempt] = {}
    if ex_ids:
        for a in (
            await db.scalars(
                select(ExerciseAttempt)
                .where(ExerciseAttempt.exercise_id.in_(ex_ids))
                .order_by(ExerciseAttempt.created_at)
            )
        ).all():
            latest[a.exercise_id] = a  # 后写覆盖 → 每题留最新一次
    out: list[ExerciseOut] = []
    for e in exercises:
        o = ExerciseOut.model_validate(e)
        o.kp_title = kp_titles.get(e.knowledge_point_id)
        o.latest_attempt = (
            ExerciseAttemptOut.model_validate(latest[e.id]) if e.id in latest else None
        )
        out.append(o)
    return out


async def submit(db: AsyncSession, exercise_id: str, content: str) -> ExerciseAttempt:
    """提交作答：代码题运行并对比 stdout 判定；概念题 LLM 评分。"""
    exercise = await db.get(Exercise, exercise_id)
    if exercise is None:
        raise LookupError("练习题不存在")

    if exercise.kind == EXERCISE_CODE:
        result = await run_code(exercise.language, content)
        passed = (
            result["status"] == "success"
            and normalize_output(result["stdout"]) == normalize_output(exercise.expected_output)
        )
        attempt = ExerciseAttempt(
            exercise_id=exercise.id,
            content=content,
            status=result["status"],
            exit_code=result["exit_code"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            duration_ms=result["duration_ms"],
            passed=passed,
            feedback="" if passed else _code_fail_hint(result["status"]),
        )
    else:
        grade = await _grade_concept(db, exercise, content)
        attempt = ExerciseAttempt(
            exercise_id=exercise.id,
            content=content,
            status=ATTEMPT_GRADED,
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=None,
            passed=grade.passed,
            feedback=f"（{grade.score} 分）{grade.feedback}".strip(),
        )

    db.add(attempt)
    await db.commit()
    return attempt


def _code_fail_hint(status: str) -> str:
    return {
        "compile_error": "代码没有编译通过，请检查语法。",
        "runtime_error": "程序运行出错了，请检查逻辑。",
        "timeout": "运行超时（10 秒上限），请检查是否存在死循环。",
        "compiler_missing": "未检测到 C++ 编译器，请先在设置中安装运行环境。",
    }.get(status, "")


async def _grade_concept(db: AsyncSession, exercise: Exercise, content: str) -> ConceptGrade:
    kp = await db.get(KnowledgePoint, exercise.knowledge_point_id)
    texts: list[str] = []
    if kp is not None:
        _, texts = await _kp_context(db, kp)
    system = render_prompt(
        "exercise_grade",
        KP_TITLE=kp.title if kp else "",
        KP_SUMMARY=(kp.summary if kp else "") or "（无摘要）",
        SECTION_TEXTS="\n\n".join(texts) or "（无教材原文）",
        TASK=exercise.task_md,
        REFERENCE_ANSWER=exercise.reference_answer,
        LEARNER_ANSWER=content,
    )
    adapter = await create_adapter_from_settings(db, scene="chat")
    temperature = await get_llm_temperature(db)
    return await adapter.chat_json(
        [{"role": "system", "content": system}], ConceptGrade, temperature=temperature
    )


async def delete_exercise(db: AsyncSession, exercise_id: str) -> None:
    exercise = await db.get(Exercise, exercise_id)
    if exercise is None:
        raise LookupError("练习题不存在")
    await db.execute(
        ExerciseAttempt.__table__.delete().where(ExerciseAttempt.exercise_id == exercise.id)
    )
    await db.execute(Exercise.__table__.delete().where(Exercise.id == exercise.id))
    await db.commit()


async def purge_document_exercises(db: AsyncSession, document_ids: list[str]) -> None:
    """删课程/文档时清理其练习数据（pipeline.purge_course_data 调用）。"""
    if not document_ids:
        return
    exercises = (
        await db.scalars(select(Exercise).where(Exercise.document_id.in_(document_ids)))
    ).all()
    await delete_kp_exercises(db, list({e.knowledge_point_id for e in exercises}))
