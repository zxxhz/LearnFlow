"""练习服务（PRD §5.10）：闯关式代码练习 + 概念题 LLM 评分。

代码关在同一知识点内按 order_index 成链，前一关通过后才解锁下一关；
提交后由执行沙箱运行，stdout 与目标输出精确对比判定；做错的题进错题本。
"""
import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Document, Exercise, ExerciseAttempt, KnowledgePoint
from app.models.exercise import (
    ATTEMPT_GRADED,
    EXERCISE_CHOICE,
    EXERCISE_CODE,
    EXERCISE_CONCEPT,
    EXERCISE_FILL,
    EXERCISE_MATH,
)
from app.schemas.exercise import (

    ConceptGrade,
    ExerciseAttemptOut,
    ExerciseDraftSet,
    ExerciseOut,
)
from app.services.execution.runner import run_code
from app.services.llm import create_adapter_from_settings
from app.services.prompt import render_prompt
from app.services.prefs import get_preferences
from app.services.sections_text import get_section_text

logger = logging.getLogger(__name__)

EXERCISE_TITLE_MAX = 200
CHOICE_LETTERS = "ABCDEFG"


def normalize_output(s: str) -> str:
    """stdout 判定用归一化：统一换行、去行尾空白、去首尾空行。"""
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _norm_fill(s: str) -> str:
    """填空判定用归一化：在 stdout 归一化基础上再去掉全部空白并忽略大小写。"""
    return "".join(normalize_output(s).split()).lower()


def _norm_choice(s: str) -> str:
    """选项作答归一化：只接受字母（大小写不限、容忍首尾噪音）。
    不做数字→字母映射：选项文本本身可能是数字，"4" 无法区分是文本还是序号。"""
    t = s.strip().upper()
    return t[:1] if t and t[0] in CHOICE_LETTERS else t


def _fill_answers(answer_json: str) -> list[str]:
    try:
        data = json.loads(answer_json)
        return [str(x) for x in data] if isinstance(data, list) else [str(data)]
    except (json.JSONDecodeError, TypeError):
        return [answer_json] if answer_json else []


def check_math_equality(user_expr_str: str, expected_expr_str: str) -> bool:
    """使用 SymPy 校验数学表达式的代数等价性（支持多项式、三角函数等化简）。"""
    import sympy as sp

    u_str = user_expr_str.strip()
    e_str = expected_expr_str.strip()
    if not u_str or not e_str:
        return False
    if u_str == e_str:
        return True
    try:
        symbols_dict = {name: sp.Symbol(name) for name in "xyztabcn"}
        u = sp.sympify(u_str, locals=symbols_dict)
        e = sp.sympify(e_str, locals=symbols_dict)
        diff = sp.simplify(u - e)
        return bool(diff == 0)
    except Exception:
        return "".join(u_str.split()).lower() == "".join(e_str.split()).lower()


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
    """为知识点生成闯关关卡（替换旧关卡）。count<=0 时取偏好 exercises_per_kp。"""
    kp = await db.get(KnowledgePoint, knowledge_point_id)
    if kp is None:
        raise LookupError("知识点不存在")
    document, texts = await _kp_context(db, kp)
    course = await db.get(Course, document.course_id)

    if count <= 0:
        prefs = await get_preferences(db)
        count = max(1, min(4, int(prefs.get("exercises_per_kp", 3))))

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
    drafts: ExerciseDraftSet = await adapter.chat_json(
        [{"role": "system", "content": system}], ExerciseDraftSet
    )

    await delete_kp_exercises(db, [kp.id])
    saved: list[Exercise] = []
    for idx, item in enumerate(drafts.exercises):
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
            reference_code=item.reference_code if item.kind == EXERCISE_CODE else "",
            hints=(
                json.dumps([h for h in item.hints if str(h).strip()][:3], ensure_ascii=False)
                if item.kind == EXERCISE_CODE
                else "[]"
            ),
            order_index=idx,
            reference_answer=item.reference_answer if item.kind == EXERCISE_CONCEPT else "",
            options=json.dumps(item.options, ensure_ascii=False) if item.kind == EXERCISE_CHOICE else "",
            answer=item.stored_answer(),
        )
        db.add(row)
        saved.append(row)
    if not saved:
        raise ValueError("生成的练习题不完整，请重试")
    await db.commit()
    return saved


async def list_for_document(db: AsyncSession, document_id: str) -> list[ExerciseOut]:
    """文档下全部练习（不含小测题），附知识点标题与最近一次作答。"""
    exercises = (
        await db.scalars(
            select(Exercise)
            .where(Exercise.document_id == document_id, Exercise.quiz_id == "")
            .order_by(Exercise.knowledge_point_id, Exercise.created_at)
        )
    ).all()
    return await _attach_meta(db, exercises)


async def _attach_meta(db: AsyncSession, exercises: list[Exercise]) -> list[ExerciseOut]:
    """批量附知识点标题 + 每题最新一次作答（窗口函数每题只取一条）。"""
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
        rn = func.row_number().over(
            partition_by=ExerciseAttempt.exercise_id,
            order_by=ExerciseAttempt.created_at.desc(),
        ).label("rn")
        sq = (
            select(ExerciseAttempt.id.label("aid"), rn)
            .where(ExerciseAttempt.exercise_id.in_(ex_ids))
            .subquery()
        )
        latest_ids = (await db.scalars(select(sq.c.aid).where(sq.c.rn == 1))).all()
        if latest_ids:
            for a in (
                await db.scalars(select(ExerciseAttempt).where(ExerciseAttempt.id.in_(latest_ids)))
            ).all():
                latest[a.exercise_id] = a
    # 闯关状态：通过过（任一次）的关卡永久解锁；同一知识点代码关按 order_index 成链
    passed_ids: set[str] = set()
    if ex_ids:
        passed_ids = set(
            await db.scalars(
                select(ExerciseAttempt.exercise_id).where(
                    ExerciseAttempt.exercise_id.in_(ex_ids),
                    ExerciseAttempt.passed.is_(True),
                )
            )
        )
    unlocked_ids: set[str] = set()
    chains: dict[str, list[Exercise]] = {}
    for e in exercises:
        if e.kind == EXERCISE_CODE and not e.quiz_id:
            chains.setdefault(e.knowledge_point_id, []).append(e)
    for chain in chains.values():
        chain.sort(key=lambda e: (e.order_index, e.created_at, e.id))
        for i, e in enumerate(chain):
            if i == 0 or e.id in passed_ids or chain[i - 1].id in passed_ids:
                unlocked_ids.add(e.id)
    out: list[ExerciseOut] = []
    for e in exercises:
        o = ExerciseOut.model_validate(e)
        o.kp_title = kp_titles.get(e.knowledge_point_id)
        o.ever_passed = e.id in passed_ids
        o.unlocked = e.kind != EXERCISE_CODE or bool(e.quiz_id) or e.id in unlocked_ids
        o.latest_attempt = (
            ExerciseAttemptOut.model_validate(latest[e.id]) if e.id in latest else None
        )
        out.append(o)
    return out


async def wrongbook(db: AsyncSession) -> list[ExerciseOut]:
    """错题本：最近一次作答未通过的题（含小测题），按该次作答时间倒序。"""
    rn = func.row_number().over(
        partition_by=ExerciseAttempt.exercise_id,
        order_by=ExerciseAttempt.created_at.desc(),
    ).label("rn")
    sq = select(
        ExerciseAttempt.id.label("aid"),
        ExerciseAttempt.exercise_id.label("eid"),
        ExerciseAttempt.created_at.label("cat"),
        ExerciseAttempt.passed.label("ok"),
        rn,
    ).subquery()
    rows = (
        await db.execute(
            select(sq.c.eid, sq.c.cat)
            .where(sq.c.rn == 1, sq.c.ok.is_(False))  # 最新一次仍未通过才进错题本
            .order_by(sq.c.cat.desc())
            .limit(200)
        )
    ).all()
    if not rows:
        return []
    ordered = [r.eid for r in rows]
    exercises = (
        await db.scalars(select(Exercise).where(Exercise.id.in_(ordered)))
    ).all()
    exercises.sort(key=lambda e: ordered.index(e.id))
    return await _attach_meta(db, exercises)


async def submit(db: AsyncSession, exercise_id: str, content: str) -> ExerciseAttempt:
    """提交作答：代码关运行对比 stdout；单选/填空本地判定；概念题 LLM 评分。"""
    exercise = await db.get(Exercise, exercise_id)
    if exercise is None:
        raise LookupError("练习题不存在")
    if exercise.kind == EXERCISE_CODE and not exercise.quiz_id:
        await _ensure_unlocked(db, exercise)

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
    elif exercise.kind == EXERCISE_CHOICE:
        passed = _norm_choice(content) == exercise.answer.strip().upper()[:1]
        attempt = ExerciseAttempt(
            exercise_id=exercise.id,
            content=content,
            status=ATTEMPT_GRADED,
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=None,
            passed=passed,
            feedback="" if passed else _choice_fail_hint(exercise),
        )
    elif exercise.kind == EXERCISE_FILL:
        passed = _norm_fill(content) in (_norm_fill(a) for a in _fill_answers(exercise.answer))
        attempt = ExerciseAttempt(
            exercise_id=exercise.id,
            content=content,
            status=ATTEMPT_GRADED,
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=None,
            passed=passed,
            feedback="" if passed else f"参考答案：{' / '.join(_fill_answers(exercise.answer))}",
        )
    elif exercise.kind == EXERCISE_MATH:
        ref = exercise.expected_output or exercise.answer or exercise.reference_answer
        passed = check_math_equality(content, ref)
        attempt = ExerciseAttempt(
            exercise_id=exercise.id,
            content=content,
            status=ATTEMPT_GRADED,
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=None,
            passed=passed,
            feedback="" if passed else f"结果与参考目标（{ref}）代数不等价，请检查推导。",
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


async def _ensure_unlocked(db: AsyncSession, exercise: Exercise) -> None:
    """闯关顺序校验：上一关从未通过且本关也从未通过时，禁止提交本关。"""
    chain = (
        await db.scalars(
            select(Exercise).where(
                Exercise.knowledge_point_id == exercise.knowledge_point_id,
                Exercise.kind == EXERCISE_CODE,
                Exercise.quiz_id == "",
            )
        )
    ).all()
    chain.sort(key=lambda e: (e.order_index, e.created_at, e.id))
    idx = next((i for i, e in enumerate(chain) if e.id == exercise.id), None)
    if idx is None or idx == 0:
        return
    passed = set(
        await db.scalars(
            select(ExerciseAttempt.exercise_id).where(
                ExerciseAttempt.exercise_id.in_([e.id for e in chain[: idx + 1]]),
                ExerciseAttempt.passed.is_(True),
            )
        )
    )
    if chain[idx - 1].id not in passed and exercise.id not in passed:
        raise PermissionError("先通过上一关，才能挑战本关")


def _choice_fail_hint(exercise: Exercise) -> str:
    idx = CHOICE_LETTERS.find(exercise.answer.strip().upper()[:1])
    try:
        opts = json.loads(exercise.options)
    except json.JSONDecodeError:
        opts = []
    correct = opts[idx] if 0 <= idx < len(opts) else exercise.answer
    return f"正确答案：{exercise.answer}（{correct}）"


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
    return await adapter.chat_json([{"role": "system", "content": system}], ConceptGrade)


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
    from app.models import Quiz

    await db.execute(Quiz.__table__.delete().where(Quiz.document_id.in_(document_ids)))
