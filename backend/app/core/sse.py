# -*- coding: utf-8 -*-
"""SSE 流式响应的统一响应头与空闲心跳包装。

全站所有 text/event-stream 端点共用：缺 charset 会在中文 payload 下产生编码歧义，
缺 X-Accel-Buffering 过 nginx 等缓冲代理时流式变阻塞（v0.5.1 体检 P3 收口）。
"""
import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Type": "text/event-stream; charset=utf-8",
}


async def with_idle_ping(
    source: AsyncIterator[Any], interval: float = 15.0
) -> AsyncIterator[Any]:
    """空闲心跳包装（v0.5.8 全量体检 P3-10）：慢工具（如 create_course 含 LLM 重试
    链路）期间上游可能数分钟无事件，代理/网关会掐断静默连接且 UI 呈假死。
    以 SSE 注释帧（": ping"，前端两种解析器均按规范忽略）定期保活。

    实现要点：上游事件的等待任务绝不能被超时取消——wait_for 会在超时时把
    CancelledError 注入上游生成器、杀掉在途 LLM/工具调用。因此用 asyncio.wait
    FIRST_COMPLETED 双任务竞速，只取消本地 sleep，上游任务始终存活。
    """
    aiter = source.__aiter__()
    next_task: "asyncio.Task[Any] | None" = None
    try:
        while True:
            if next_task is None or next_task.done():
                next_task = asyncio.ensure_future(aiter.__anext__())
            ping_task = asyncio.ensure_future(asyncio.sleep(interval))
            try:
                done, _ = await asyncio.wait(
                    {next_task, ping_task}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                ping_task.cancel()
            if next_task not in done:
                yield ": ping\n\n"
                continue
            try:
                evt = next_task.result()
            except StopAsyncIteration:
                next_task = None
                return
            next_task = None
            yield evt
    finally:
        # 消费方 break / 断连时收尾：先终止仍在等待的上游事件任务（其内部
        # finally 自会处理半截落库），再确定性 aclose 上游生成器
        if next_task is not None and not next_task.done():
            next_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await next_task
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()
