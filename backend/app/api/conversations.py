import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from app.core.db import get_db
from app.models import Annotation, Conversation, Document, Message
from app.models.base import utcnow_iso
from app.schemas.conversation import MessageCreate, MessageOut
from app.services.context import build_annotation_messages
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError

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

    if conv.kind == "feynman":
        # 费曼追问：由 feynman 服务全权处理（存消息/更新轮次/建议评价）
        from app.services.feynman import reply_as_tutor

        turn = await reply_as_tutor(db, conv, body.content)
        deltas = turn.deltas
        annotation_mode = False
    else:
        ann = await db.get(Annotation, conv.annotation_id) if conv.annotation_id else None
        if ann is None:
            raise HTTPException(status_code=400, detail="标注不存在")
        db.add(Message(conversation_id=conv.id, role="user", content=body.content))
        ann.updated_at = utcnow_iso()
        await db.commit()
        messages = await build_annotation_messages(db, conv)
        adapter = await create_adapter_from_settings(db, scene="chat")
        deltas = adapter.chat(messages, stream=True)
        annotation_mode = True

    async def gen():
        buffer: list[str] = []
        try:
            async for delta in deltas:
                buffer.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        except LLMError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
            return
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请重试。'}, ensure_ascii=False)}\n\n"
            return
        if annotation_mode:
            saved = Message(
                conversation_id=conv.id, role="assistant", content="".join(buffer)
            )
            db.add(saved)
            await db.commit()
            yield f"data: {json.dumps({'type': 'done', 'message_id': saved.id}, ensure_ascii=False)}\n\n"
        else:
            payload = {"type": "done", "suggest_evaluate": turn.suggest_evaluate}
            if turn.saved_message_id:
                payload["message_id"] = turn.saved_message_id
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
