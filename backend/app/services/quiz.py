"""随堂小测（PRD §5.10 延伸）：跨知识点组卷，只出可自动判定的题型，复用练习判定。"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Document, Exercise, KnowledgePoint, Quiz
from app.models.exercise import EXERCISE_CHOICE, EXERCISE_CODE, EXERCISE_FILL
from app.schemas.exercise import ExerciseDraftSet, QuizOut
from app.services.exercise import _attach_meta  # noqa: SLF001 复用内部装配
from app.services.llm import create_adapter_from_settings
from app.services.prompt import render_prompt
from app.services.sections_text import get_section_text

logger = logging.getLogger(__name__)


async def _kp_texts(db: AsyncSession, kp: KnowledgePoint, cap: int = 1200) -> str:
    texts = []
    for sid in json.loads(kp.section_ids) if kp.section_ids else []:
        text = await get_section_text(db, await db.get(Document, kp.document_id), sid)
        if text:
            texts.append(text)
    joined = "\n\n".join(texts) or kp.summary or "（无教材原文）"
    return joined[:cap]


async def generate_quiz(
    db: AsyncSession, document_id: str, kp_ids: list[str], language: str, per_kp: int
) -> Quiz:
    document = await db.get(Document, document_id)
    if document is None:
        raise LookupError("章节不存在")
    kps = []
    for kid in kp_ids:
        kp = await db.get(KnowledgePoint, kid)
        if kp is None or kp.document_id != document_id:
            raise LookupError("知识点不属于该章节")
        kps.append(kp)
    course = await db.get(Course, document.course_id)

    # 同章旧小测连带题目与作答一并清掉（保留普通练习不受影响）
    old_quizzes = (
        await db.scalars(select(Quiz).where(Quiz.document_id == document_id))
    ).all()
    for q in old_quizzes:
        await _delete_quiz_rows(db, q.id)
        await db.delete(q)

    quiz = Quiz(
        document_id=document_id,
        course_id=document.course_id,
        kp_ids=json.dumps(kp_ids, ensure_ascii=False),
        title=f"随堂小测 · {document.title}",
    )
    db.add(quiz)
    await db.flush()

    kp_blocks = []
    for i, kp in enumerate(kps):
        kp_blocks.append(
            f"### 知识点 {i + 1}：{kp.title}\n摘要：{kp.summary or '（无摘要）'}\n教材原文：\n{await _kp_texts(db, kp)}"
        )
    total = len(kps) * per_kp
    system = render_prompt(
        "quiz_gen",
        COURSE_TOPIC=course.topic if course else "",
        COURSE_TITLE=course.title if course else "",
        KP_BLOCKS="\n\n".join(kp_blocks),
        KP_TITLES="、".join(kp.title for kp in kps),
        LANGUAGE=language,
        TOTAL=str(total),
    )
    adapter = await create_adapter_from_settings(db, scene="generation")
    drafts: ExerciseDraftSet = await adapter.chat_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "请根据上述课程内容与要求生成随堂小测题目，严格以 JSON 格式输出。"},
        ],
        ExerciseDraftSet,
    )

    saved = 0
    for item in drafts.exercises:
        if item.kind not in (EXERCISE_CHOICE, EXERCISE_FILL, EXERCISE_CODE):
            continue
        if not item.is_complete():
            logger.warning("skip incomplete quiz item: kind=%s title=%s", item.kind, item.title)
            continue
        kp = kps[(item.kp_index - 1) % len(kps)] if item.kp_index >= 1 else kps[saved % len(kps)]
        db.add(
            Exercise(
                knowledge_point_id=kp.id,
                document_id=document_id,
                kind=item.kind,
                title=item.title[:200],
                task_md=item.task,
                language=item.resolved_language(language) if item.kind == EXERCISE_CODE else "",
                skeleton_code=item.skeleton_code if item.kind == EXERCISE_CODE else "",
                expected_output=item.expected_output if item.kind == EXERCISE_CODE else "",
                options=json.dumps(item.options, ensure_ascii=False) if item.kind == EXERCISE_CHOICE else "",
                answer=item.stored_answer(),
                quiz_id=quiz.id,
            )
        )
        saved += 1
    if not saved:
        raise ValueError("生成的小测题不完整，请重试")
    await db.commit()
    return quiz


async def _delete_quiz_rows(db: AsyncSession, quiz_id: str) -> None:
    from app.models import ExerciseAttempt

    ex_ids = [
        e.id for e in (await db.scalars(select(Exercise.id).where(Exercise.quiz_id == quiz_id))).all()
    ]
    if ex_ids:
        await db.execute(
            ExerciseAttempt.__table__.delete().where(ExerciseAttempt.exercise_id.in_(ex_ids))
        )
    await db.execute(Exercise.__table__.delete().where(Exercise.quiz_id == quiz_id))


async def list_quizzes(db: AsyncSession, document_id: str) -> list[QuizOut]:
    quizzes = (
        await db.scalars(
            select(Quiz).where(Quiz.document_id == document_id).order_by(Quiz.created_at.desc())
        )
    ).all()
    out: list[QuizOut] = []
    for q in quizzes:
        items = (
            await db.scalars(
                select(Exercise)
                .where(Exercise.quiz_id == q.id)
                .order_by(Exercise.created_at, Exercise.knowledge_point_id)
            )
        ).all()
        attached = await _attach_meta(db, list(items))
        correct = sum(1 for e in attached if e.latest_attempt and e.latest_attempt.passed is True)
        out.append(
            QuizOut(
                id=q.id,
                document_id=q.document_id,
                course_id=q.course_id,
                title=q.title,
                kp_ids=json.loads(q.kp_ids) if q.kp_ids else [],
                created_at=q.created_at,
                items=attached,
                total=len(attached),
                correct=correct,
            )
        )
    return out


async def delete_quiz(db: AsyncSession, quiz_id: str) -> None:
    quiz = await db.get(Quiz, quiz_id)
    if quiz is None:
        raise LookupError("小测不存在")
    await _delete_quiz_rows(db, quiz_id)
    await db.delete(quiz)
    await db.commit()
