"""统一「AI 助教」API（v0.5.0）：全站唯一的答疑会话入口。

- POST /assistant/session：按归属域（document / bank_question / global）幂等取回会话 ID；
- POST /conversations/{id}/messages/stream：统一流式答疑（含工具调用与来源引用事件）；
- POST /conversations/{id}/tool-confirm：落学员对敏感工具（模型自主沙箱运行）的授权决定。

划线答疑（kind=annotation）的旧端点保持不变，历史兼容由 conversations.py 承担。
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory, get_db
from app.models import Conversation, Message
from app.models.conversation import CONVERSATION_KIND_ASSISTANT
from app.schemas.conversation import MessageOut
from app.services.assistant import (
    ASSISTANT_CONTEXT_TYPES,
    build_evolution_interaction,
    get_or_create_assistant_session,
    resolve_scene_scope,
    resolve_tool_confirm,
    stream_assistant_reply,
)
from app.services.llm import create_adapter_from_settings
from app.services.profile import (
    MISCONCEPTION_SOURCE_CONVERSATION,
    trigger_profile_evolution,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistant"])


class AssistantSessionRequest(BaseModel):
    context_type: str  # document / bank_question / global
    context_id: str = ""


class AssistantMessageRequest(BaseModel):
    content: str
    # 每条消息附带的现场上下文（阅读划选 / 练习代码与判题 / 题库作答），场景护栏按此切换
    scene: dict = Field(default_factory=dict)


class ToolConfirmRequest(BaseModel):
    approve: bool
    # 勾选「本会话自动运行」后，同一会话内后续沙箱运行不再逐次询问（进程内存态，不跨端）
    remember: bool = False


@router.post("/assistant/session")
async def assistant_session(
    body: AssistantSessionRequest, db: AsyncSession = Depends(get_db)
):
    if body.context_type not in ASSISTANT_CONTEXT_TYPES:
        raise HTTPException(status_code=400, detail="不支持的会话归属域")
    try:
        conv = await get_or_create_assistant_session(
            db, body.context_type, body.context_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "conversation_id": conv.id,
        "context_type": conv.context_type,
        "context_id": conv.context_id,
    }


@router.post("/conversations/{conversation_id}/tool-confirm")
async def assistant_tool_confirm(
    conversation_id: str, body: ToolConfirmRequest, db: AsyncSession = Depends(get_db)
):
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.kind != CONVERSATION_KIND_ASSISTANT:
        raise HTTPException(status_code=404, detail="AI 助教会话不存在")
    ok = resolve_tool_confirm(conversation_id, body.approve, body.remember)
    if not ok:
        raise HTTPException(status_code=409, detail="当前没有等待确认的沙箱运行请求")
    return {"ok": True, "remember": body.remember and body.approve}


@router.post("/conversations/{conversation_id}/messages/stream")
async def assistant_message_stream(
    conversation_id: str,
    body: AssistantMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    if conv.kind != CONVERSATION_KIND_ASSISTANT:
        raise HTTPException(status_code=400, detail="该会话不是 AI 助教会话，请使用原消息接口")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="消息内容为空")

    # LLM 配置校验先于任何持久化：未配置时快速 400，不留下没有回应的孤儿提问
    # （v0.5.1 体检 P2；与 solve.py 的既有顺序口径一致）
    adapter = await create_adapter_from_settings(db, scene="chat")

    user_msg = Message(conversation_id=conv.id, role="user", content=body.content)
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)
    user_msg_dict = MessageOut.model_validate(user_msg).model_dump()

    conv_id = conv.id
    scene = body.scene if isinstance(body.scene, dict) else {}

    async def gen():
        yield f"data: {json.dumps({'type': 'user_ack', 'message': user_msg_dict}, ensure_ascii=False)}\n\n"
        buffer: list[str] = []
        stream_finished = False
        agent_stream = stream_assistant_reply(db, conv, scene, adapter)

        async def persist_reply() -> int | None:
            """已生成的回复（含断连/异常时的半截）落库，保证 user/assistant 成对。"""
            full_content = "".join(buffer)
            if not full_content.strip():
                return None
            async with async_session_factory() as s:
                partial = not stream_finished
                saved = Message(
                    conversation_id=conv_id,
                    role="assistant",
                    content=full_content,
                    meta='{"partial": true}' if partial else "{}",
                )
                s.add(saved)
                await s.commit()
                return saved.id

        try:
            async for evt in agent_stream:
                etype = evt.get("type")
                if etype == "delta":
                    buffer.append(evt.get("text", ""))
                elif etype == "done":
                    stream_finished = True
                    break
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            # 客户端断连：半截回复也要落库（v0.5.1 体检 P2——LLM 已消耗的 token 不能凭空蒸发）
            await persist_reply()
            raise
        except Exception:  # noqa: BLE001
            logger.exception("助教 SSE 事件转发异常")
            await persist_reply()
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请稍后重试'}, ensure_ascii=False)}\n\n"
            return
        finally:
            try:
                await agent_stream.aclose()
            except Exception:
                pass

        msg_id = await persist_reply()
        full_content = "".join(buffer)

        # 画像演进：轻量解析学科域（不重跑上下文组装/沙箱），盖章 + 证据溯源到该会话
        if full_content.strip():
            try:
                evolve_scope = await resolve_scene_scope(db, scene)
                context_text, interaction_text = build_evolution_interaction(
                    body.content, full_content, scene
                )
                trigger_profile_evolution(
                    context=context_text,
                    interaction=interaction_text,
                    scope=evolve_scope,
                    source_type=MISCONCEPTION_SOURCE_CONVERSATION,
                    source_id=conv_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("助教画像演进失败（不影响会话）")

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
