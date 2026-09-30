"""费曼学习服务（PRD §10.2）：AI 扮演学生追问 + 理解度评价。"""
import json
import logging
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Document, FeynmanSession, KnowledgePoint, Message
from app.models.base import utcnow_iso
from app.schemas.feynman import FeynmanEvaluation
from app.services.llm import (
    OpenAICompatAdapter,
    create_adapter_from_settings,
    get_llm_temperature,
)
from app.services.prompt import render_prompt
from app.services.review import get_preferences
from app.services.sections_text import get_section_text

logger = logging.getLogger(__name__)


class FeynmanTurn:
    """一轮追问的流式结果：deltas 消费完毕后 saved_message_id / suggest_evaluate 可读。"""

    def __init__(self, deltas: AsyncIterator[str]):
        self.deltas = deltas
        self.saved_message_id: str | None = None
        self.suggest_evaluate: bool = False


async def _load_context(db: AsyncSession, session: FeynmanSession):
    kp = await db.get(KnowledgePoint, session.knowledge_point_id)
    document = await db.get(Document, kp.document_id)
    section_ids = json.loads(kp.section_ids) if kp.section_ids else []
    texts = []
    for sid in section_ids:
        text = await get_section_text(db, document, sid)
        if text:
            texts.append(f"[{sid}] {text}")
    return kp, document, texts


def _history_messages(messages: list[Message]) -> str:
    if not messages:
        return "（暂无）"
    return "\n".join(f"{'学习者' if m.role == 'user' else '学生'}：{m.content}" for m in messages)


async def _tutor_prompt(
    db: AsyncSession, kp: KnowledgePoint, texts: list[str], history: list[Message], round_no: int, max_rounds: int
) -> list[dict]:
    system = render_prompt(
        "feynman_tutor",
        KP_TITLE=kp.title,
        KP_SUMMARY=kp.summary or "（无摘要）",
        SECTION_TEXTS="\n\n".join(texts) or "（无教材原文）",
        HISTORY=_history_messages(history),
        ROUND=str(round_no),
        MAX_ROUNDS=str(max_rounds),
    )
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    return messages


async def _preferences_max_rounds(db: AsyncSession) -> int:
    return int((await get_preferences(db)).get("feynman_max_rounds", 4))


async def start_session(
    db: AsyncSession, knowledge_point_id: str, explanation: str
) -> FeynmanSession:
    kp = await db.get(KnowledgePoint, knowledge_point_id)
    if kp is None:
        raise LookupError("知识点不存在")

    conv = Conversation(kind="feynman")
    db.add(conv)
    await db.flush()
    session = FeynmanSession(
        knowledge_point_id=kp.id,
        document_id=kp.document_id,
        conversation_id=conv.id,
        status="questioning",
        round_count=0,
    )
    db.add(session)
    await db.flush()
    conv.feynman_session_id = session.id

    db.add(Message(conversation_id=conv.id, role="user", content=explanation))
    await db.commit()

    # 生成学生的第一个追问
    await reply_as_tutor(db, conv, None, first_turn=True)
    return session


async def reply_as_tutor(
    db: AsyncSession,
    conversation: Conversation,
    user_content: str | None,
    *,
    first_turn: bool = False,
) -> FeynmanTurn:
    """生成学生追问（流式）。user_content 为空表示仅生成第一问（start_session 内部用）。"""
    session = await db.get(FeynmanSession, conversation.feynman_session_id)
    if user_content:
        db.add(Message(conversation_id=conversation.id, role="user", content=user_content))
        await db.commit()

    kp, _, texts = await _load_context(db, session)
    history = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    ).all()
    max_rounds = await _preferences_max_rounds(db)
    round_no = min(session.round_count + 1, max_rounds)
    messages = await _tutor_prompt(db, kp, texts, list(history), round_no, max_rounds)

    adapter: OpenAICompatAdapter = await create_adapter_from_settings(db)
    temperature = await get_llm_temperature(db)
    turn = FeynmanTurn(adapter.chat(messages, stream=True, temperature=temperature))

    async def _wrap() -> AsyncIterator[str]:
        buffer: list[str] = []
        async for delta in turn.deltas:
            buffer.append(delta)
            yield delta
        saved = Message(
            conversation_id=conversation.id, role="assistant", content="".join(buffer)
        )
        db.add(saved)
        session.round_count += 1
        session.updated_at = utcnow_iso()
        await db.commit()
        turn.saved_message_id = saved.id
        turn.suggest_evaluate = session.round_count >= max_rounds

    turn.deltas = _wrap()  # type: ignore[assignment]
    return turn


async def evaluate_session(db: AsyncSession, session_id: str) -> FeynmanSession:
    session = await db.get(FeynmanSession, session_id)
    if session is None:
        raise LookupError("费曼会话不存在")
    kp, document, texts = await _load_context(db, session)
    messages = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == session.conversation_id)
            .order_by(Message.created_at)
        )
    ).all()

    section_list = "\n".join(texts) if texts else "（无）"
    system = render_prompt(
        "feynman_eval",
        KP_TITLE=kp.title,
        KP_SUMMARY=kp.summary or "（无摘要）",
        SECTION_LIST=section_list,
        HISTORY=_history_messages(list(messages)),
    )
    adapter: OpenAICompatAdapter = await create_adapter_from_settings(db)
    evaluation: FeynmanEvaluation = await adapter.chat_json(
        [{"role": "system", "content": system}],
        FeynmanEvaluation,
    )
    # gap 的 section_id 必须落在该知识点的块集合内，否则置空（PRD FR-4.3）
    valid_ids = set(json.loads(kp.section_ids) if kp.section_ids else [])
    for gap in evaluation.gaps:
        if gap.section_id and gap.section_id not in valid_ids:
            gap.section_id = None

    session.evaluation = evaluation.model_dump_json()
    session.status = "done"
    session.updated_at = utcnow_iso()
    await db.commit()
    return session


async def kp_context(db: AsyncSession, kp_id: str) -> dict:
    kp = await db.get(KnowledgePoint, kp_id)
    if kp is None:
        raise LookupError("知识点不存在")
    document = await db.get(Document, kp.document_id)
    from app.models import Course

    course = await db.get(Course, document.course_id)
    return {
        "knowledge_point": kp,
        "document_id": document.id,
        "document_title": document.title,
        "course_id": course.id,
        "course_title": course.title,
    }
