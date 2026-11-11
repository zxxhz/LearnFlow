"""本地 AI / 沙箱执行代理调度器。

监听云端反向隧道转发过来的请求，在本地以异步形式请求本地 127.0.0.1:8420，
天然复用所有既有 API 路由、数据库事务、权限与流式 SSE 输出，
并将生成的流式响应（逐 chunk）封装为 WebSocket 消息推回云端。
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 不向本地 127.0.0.1 转发的请求头（避免触发 Host/CSRF 门禁误拒或底层传输冲突）。
# forwarded 头族必须剥离：云端前置层注入的 X-Forwarded-For 一旦透传，
# 本地 uvicorn（proxy_headers 默认放行回环来源）会采信它把请求来源改写为外部 IP，
# 导致 _AccessGuard 将回环 worker 误判为"局域网设备"而 403。
_HOP_BY_HOP_OR_SENSITIVE_HEADERS = {
    "host",
    "origin",
    "referer",
    "sec-fetch-site",
    "sec-fetch-mode",
    "sec-fetch-dest",
    "content-length",
    "x-forwarded-for",
    "x-real-ip",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
    "forwarded",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
}


async def handle_relay_request(
    send_fn: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    message: dict[str, Any],
) -> None:
    """处理单条由云端转发而来的请求消息并流式回传结果。

    消息结构：
    {
        "type": "request",
        "request_id": "...",
        "method": "POST" | "GET" | ...,
        "path": "/api/...",
        "headers": {...},
        "query_params": {...},
        "body": ...
    }
    """
    request_id = message.get("request_id")
    if not request_id:
        logger.warning("收到缺少 request_id 的请求消息: %s", message)
        return

    method = (message.get("method") or "GET").upper()
    path = message.get("path") or "/"
    if not path.startswith("/"):
        path = "/" + path

    raw_headers = message.get("headers") or {}
    query_params = message.get("query_params") or None
    raw_body = message.get("body")

    # 规范化并清洗转发请求头
    clean_headers: dict[str, str] = {}
    for k, v in raw_headers.items():
        if k.lower() not in _HOP_BY_HOP_OR_SENSITIVE_HEADERS:
            clean_headers[k] = str(v)
    clean_headers["x-learnflow-relayed"] = "true"

    # 处理请求体
    content: bytes | None = None
    json_data: Any = None
    if raw_body is not None:
        if isinstance(raw_body, (dict, list)):
            json_data = raw_body
        elif isinstance(raw_body, str):
            content = raw_body.encode("utf-8")
        elif isinstance(raw_body, bytes):
            content = raw_body

    local_base_url = f"http://127.0.0.1:{settings.port}"
    logger.info(
        "Relay worker 开始执行云端请求: id=%s %s %s",
        request_id,
        method,
        path,
    )

    # 针对 AI 长文本生成设置足够长的超时时间（300秒），连接阶段 10 秒
    timeout = httpx.Timeout(timeout=300.0, connect=10.0)

    try:
        # trust_env=False：绝不读取代理环境变量，防止本地系统代理（Clash 等）劫持
        # worker 对 127.0.0.1:8420 的内部回源请求（与 v0.4.71 websockets proxy=None 同理）
        async with httpx.AsyncClient(base_url=local_base_url, timeout=timeout, trust_env=False) as client:
            req = client.build_request(
                method=method,
                url=path,
                headers=clean_headers,
                params=query_params,
                content=content,
                json=json_data,
            )
            resp = await client.send(req, stream=True)

            logger.info(
                "Relay worker 收到本地响应状态: id=%s status=%s",
                request_id,
                resp.status_code,
            )

            # 逐 chunk 流式读取并实时推送回云端
            try:
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    # LearnFlow 的 AI 响应大多为 SSE (text/event-stream) 或 JSON 文本
                    chunk_str = chunk.decode("utf-8", errors="replace")
                    await send_fn({
                        "type": "chunk",
                        "request_id": request_id,
                        "data": chunk_str,
                    })
            finally:
                await resp.aclose()

            # 发送流结束标记
            resp_headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in {"transfer-encoding", "content-length", "connection"}
            }
            await send_fn({
                "type": "end",
                "request_id": request_id,
                "status_code": resp.status_code,
                "headers": resp_headers,
            })
            logger.info("Relay worker 执行完成: id=%s", request_id)

    except asyncio.CancelledError:
        logger.info("Relay worker 任务被取消: id=%s", request_id)
        await send_fn({
            "type": "error",
            "request_id": request_id,
            "detail": "本地任务已被取消",
        })
        raise
    except Exception as exc:
        logger.exception("Relay worker 执行本地调用异常: id=%s, err=%s", request_id, exc)
        await send_fn({
            "type": "error",
            "request_id": request_id,
            "detail": f"本地执行异常: {exc}",
        })
