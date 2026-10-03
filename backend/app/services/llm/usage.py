"""LLM Token 用量落库（尽力而为）：调用成功后异步写入 llm_usages，失败不影响主流程。"""
import asyncio
import logging

from app.core.db import async_session_factory
from app.models import LLMUsage

logger = logging.getLogger(__name__)


_pending_tasks: set[asyncio.Task] = set()  # 持强引用防 GC（create_task 只留弱引用）


def record_usage(
    scene: str, model: str, prompt_tokens: int, completion_tokens: int, duration_ms: int
) -> None:
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_persist(scene, model, prompt_tokens, completion_tokens, duration_ms))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _persist(
    scene: str, model: str, prompt_tokens: int, completion_tokens: int, duration_ms: int
) -> None:
    try:
        async with async_session_factory() as db:
            db.add(
                LLMUsage(
                    scene=scene,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("LLM 用量记录失败", exc_info=True)
