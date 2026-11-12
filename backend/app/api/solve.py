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
from app.core.sse import SSE_HEADERS
from app.api.imports import _run_photo_decode
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
    # Pillow 解码/缩放是秒级 CPU 活：放线程池跑，避免冻结事件循环（SSE/心跳全停）。
    # v0.5.8 体检 P2：走与 imports.py 同款 2 路并发闸——LAN 多端并发拍照时，
    # 每请求 3 张×60MP 的无上限解码可致瞬态内存 GB 级与线程池饥饿
    data_urls = await _run_photo_decode(compress_to_data_urls, images, MAX_SOLVE_IMAGES)
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
        # v0.5.8 体检 P2：chat(stream=True) 惰性打开——此同步 except 实际只捕获
        # 参数/配置类异常，连接与鉴权错误在迭代期经 gen 的 error 事件下发。
        # 保留兜底并注明口径，避免误认「启动失败提示可达」而误导排障
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
        except Exception:  # noqa: BLE001
            logger.exception("solve photo stream error")
            yield f"data: {json.dumps({'type': 'error', 'detail': '解答服务中断，请稍后重试'}, ensure_ascii=False)}\n\n"
            return
        finally:
            # 客户端断连/生成器提前关闭时确定性关闭上游 LLM 流，不依赖 GC 终结器
            try:
                await deltas.aclose()
            except Exception:
                pass
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
