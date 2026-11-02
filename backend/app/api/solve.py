"""拍照解题 API：上传题目照片 → 视觉 LLM 流式给出答案与分步解析（SSE）。

POST /api/solve/photo   multipart images×N + hint → text/event-stream
事件契约：{"type": "delta", "text"} / {"type": "done"} / {"type": "error", "detail"}
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.images import build_vision_messages, compress_to_data_urls
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError
from app.services.prompt import render_prompt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/solve", tags=["solve"])

MAX_SOLVE_IMAGES = 3


@router.post("/photo")
async def solve_photo(
    images: list[UploadFile] = File(...),
    hint: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """拍照解题：题目照片 → AI 流式输出答案与分步解析（第一行直接给答案）。"""
    # Pillow 解码/缩放是秒级 CPU 活：放线程池跑，避免冻结事件循环（SSE/心跳全停）
    data_urls = await asyncio.to_thread(compress_to_data_urls, images, MAX_SOLVE_IMAGES)
    hint = (hint or "").strip()[:2_000]
    try:
        adapter = await create_adapter_from_settings(db, scene="chat")
    except LLMError:
        # 未配置 LLM → 全局 handler 400 + 中文提示
        raise
    except Exception as e:  # noqa: BLE001
        logger.info("solve photo adapter unavailable: %r", e)
        raise HTTPException(
            status_code=400,
            detail="尚未配置 LLM 服务，请先到「设置」页填写 base_url、API Key 和模型名",
        ) from e

    system_prompt = render_prompt("solve_photo", HINT=hint.strip() or "（未填写）")
    instruction = (
        f"以下是 {len(data_urls)} 张题目照片，请按系统规则直接给出答案与分步解析。"
        f"用户附加说明：{hint.strip() or '无'}"
    )
    messages = build_vision_messages(system_prompt, instruction, data_urls)

    try:
        deltas = await adapter.chat(messages, stream=True)
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("solve photo stream open failed")
        raise HTTPException(
            status_code=502,
            detail=f"启动拍照解题失败：{e}。若反复出现，请确认「设置」页配置的模型支持视觉（多模态）",
        ) from e

    async def gen():
        try:
            async for delta in deltas:
                if delta:
                    yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        except LLMError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("solve photo stream error")
            yield f"data: {json.dumps({'type': 'error', 'detail': f'解答中断：{e}'}, ensure_ascii=False)}\n\n"
            return
        finally:
            # 客户端断连/生成器提前关闭时确定性关闭上游 LLM 流，不依赖 GC 终结器
            await deltas.aclose()
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

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
