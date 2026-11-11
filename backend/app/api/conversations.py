import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory, get_db
from app.models import Annotation, Conversation, Document, Message
from app.models.base import utcnow_iso
from app.schemas.conversation import MessageCreate, MessageOut
from app.services.context import build_annotation_messages
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError
from app.services.profile import (
    MISCONCEPTION_SOURCE_CONVERSATION,
    discipline_for_document,
    trigger_profile_evolution,
)

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

    # LLM 配置校验先于任何持久化：未配置时快速 400，不留下没有回应的孤儿提问（v0.5.1 体检 P2）
    messages = await build_annotation_messages(db, conv)
    adapter = await create_adapter_from_settings(db, scene="chat")

    user_msg = Message(conversation_id=conv.id, role="user", content=body.content)
    db.add(user_msg)
    ann.updated_at = utcnow_iso()
    await db.commit()
    await db.refresh(user_msg)

    user_msg_dict = MessageOut.model_validate(user_msg).model_dump()
    deltas = await adapter.chat(messages, stream=True)
    conv_id = conv.id
    # 划线所在课程学科域：盲区盖章 scope + 证据溯源（在请求会话存活期内解析好）
    _ann_doc = await db.get(Document, ann.document_id) if ann.document_id else None
    evolve_scope = await discipline_for_document(db, _ann_doc)

    async def gen():
        # 首先立即确认用户消息已保存，供前端快速对齐
        yield f"data: {json.dumps({'type': 'user_ack', 'message': user_msg_dict}, ensure_ascii=False)}\n\n"
        buffer: list[str] = []
        stream_finished = False
        try:
            async for delta in deltas:
                buffer.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
            stream_finished = True
        except LLMError as e:
            logger.warning(f"LLM stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
            return
        except Exception:  # noqa: BLE001
            logger.exception("Conversation stream exception")
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请稍后重试'}, ensure_ascii=False)}\n\n"
            return
        finally:
            try:
                await deltas.aclose()
            except Exception:
                pass
            # 半截回复也落库（含客户端断连）：user/assistant 成对，LLM 已消耗的 token 不凭空蒸发
            full_content = "".join(buffer)
            if full_content.strip():
                async with async_session_factory() as s:
                    saved = Message(
                        conversation_id=conv_id,
                        role="assistant",
                        content=full_content,
                        meta='{"partial": true}' if not stream_finished else "{}",
                    )
                    s.add(saved)
                    await s.commit()
                    msg_id = saved.id

        full_content = "".join(buffer)
        if not stream_finished or not full_content.strip():
            return

        # 异步提炼用户划线问答的认知盲区与提问习惯（盖章学科域与证据来源）
        trigger_profile_evolution(
            context=f"划线文本：{ann.exact}",
            interaction=f"学生提问：{body.content}\n助教解答：{full_content[:300]}",
            scope=evolve_scope,
            source_type=MISCONCEPTION_SOURCE_CONVERSATION,
            source_id=conv_id,
        )

        yield f"data: {json.dumps({'type': 'done', 'message_id': msg_id, 'content': full_content}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )

