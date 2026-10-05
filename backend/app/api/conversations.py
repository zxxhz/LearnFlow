import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from app.core.db import async_session_factory, get_db
from app.models import Annotation, Conversation, Message
from app.models.base import utcnow_iso
from app.schemas.conversation import MessageCreate, MessageOut
from app.services.context import build_annotation_messages
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _get_conversation(db: AsyncSession, conversation_id: str) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conv


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: str, db: AsyncSession = Depends(get_db)):
    await _get_conversation(db, conversation_id)
    messages = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    ).all()
    return [MessageOut.model_validate(m) for m in messages]


@router.post("/{conversation_id}/messages")
async def post_message(
    conversation_id: str, body: MessageCreate, db: AsyncSession = Depends(get_db)
):
    conv = await _get_conversation(db, conversation_id)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="消息内容为空")

    ann = await db.get(Annotation, conv.annotation_id) if conv.annotation_id else None
    if ann is None:
        raise HTTPException(status_code=400, detail="标注不存在")
    db.add(Message(conversation_id=conv.id, role="user", content=body.content))
    ann.updated_at = utcnow_iso()
    await db.commit()
    messages = await build_annotation_messages(db, conv)
    adapter = await create_adapter_from_settings(db, scene="chat")
    deltas = await adapter.chat(messages, stream=True)
    conv_id = conv.id

    async def gen():
        buffer: list[str] = []
        try:
            async for delta in deltas:
                buffer.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        except LLMError as e:
            logger.warning(f"LLM stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
            return
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Conversation stream exception: {e}")
            yield f"data: {json.dumps({'type': 'error', 'detail': f'服务异常：{e}'}, ensure_ascii=False)}\n\n"
            return

        async with async_session_factory() as s:
            saved = Message(
                conversation_id=conv_id, role="assistant", content="".join(buffer)
            )
            s.add(saved)
            await s.commit()
            msg_id = saved.id
        yield f"data: {json.dumps({'type': 'done', 'message_id': msg_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
