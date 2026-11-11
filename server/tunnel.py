"""WebSocket 反向隧道核心管理器。

职责：
1. 监听并管理本地客户端通过 /ws/relay 建立的反向长连接。
2. 维护连接状态（在线/离线、最后心跳时间、客户端信息、能力标签）。
3. 提供 dispatch_request 接口：
   将云端收到的 API/AI 请求打包成 RPC 消息下发给本地客户端，
   并通过异步队列接收本地回传的流式 Chunks（如 SSE），实时 yield 供 StreamingResponse 转发给前端。
4. 提供超时检测、断线感知与异常恢复机制。
"""
import asyncio
import base64
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from server.auth import verify_token
from server.config import settings

logger = logging.getLogger("server.tunnel")


class WorkerOfflineError(Exception):
    """本地客户端 Worker 离线异常。"""
    pass


class WorkerRequestTimeoutError(Exception):
    """请求转发给本地 Worker 超时异常。"""
    pass


# 下发本地 Worker 前必须剥离的代理链请求头。
# VPS 前置 TLS 终结层会为所有入站请求注入 X-Forwarded-For（真实客户端公网 IP），
# 若透传到本地后端，本地 uvicorn（proxy_headers 默认开启且放行回环来源）会采信该头
# 把请求来源改写为外部 IP，导致本地 _AccessGuard 将回环 worker 误判为"局域网设备"而 403。
_FORWARDED_HEADERS = frozenset({
    "x-forwarded-for",
    "x-real-ip",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
    "forwarded",
})

# 回传给云端调用方时需要丢弃的响应头（逐跳头与长度头由 ASGI 层自行生成）
_DROP_RESPONSE_HEADERS = frozenset({"transfer-encoding", "content-length", "connection"})


@dataclass
class WorkerConnection:
    worker_id: str
    websocket: WebSocket
    client_id: str = "learnflow-local"
    client_name: str = "本地客户端"
    version: str = "1.0.0"
    connected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_heartbeat: float = field(default_factory=time.time)
    capabilities: list[str] = field(default_factory=list)
    pending_requests: dict[str, asyncio.Queue] = field(default_factory=dict)
    response_metadata: dict[str, dict] = field(default_factory=dict)


class TunnelManager:
    """反向隧道全局管理器。"""

    def __init__(self):
        self._workers: dict[str, WorkerConnection] = {}
        self._lock = asyncio.Lock()

    def is_worker_online(self) -> bool:
        """检查是否有活跃的本地 Worker。"""
        now = time.time()
        for worker in self._workers.values():
            # 60 秒内有心跳则视为在线
            if now - worker.last_heartbeat < 60:
                return True
        return False

    def get_active_worker(self) -> Optional[WorkerConnection]:
        """获取当前最优活跃 Worker。"""
        now = time.time()
        for worker in reversed(list(self._workers.values())):
            if now - worker.last_heartbeat < 60:
                return worker
        return None

    def get_status(self) -> dict[str, Any]:
        """获取当前隧道连接状态摘要。"""
        active_worker = self.get_active_worker()
        worker_info = None
        if active_worker:
            worker_info = {
                "worker_id": active_worker.worker_id,
                "client_id": active_worker.client_id,
                "client_name": active_worker.client_name,
                "version": active_worker.version,
                "connected_at": active_worker.connected_at,
                "last_heartbeat_seconds_ago": round(time.time() - active_worker.last_heartbeat, 1),
                "capabilities": active_worker.capabilities,
                "pending_requests_count": len(active_worker.pending_requests),
            }

        return {
            "online": self.is_worker_online(),
            "worker_count": len(self._workers),
            "worker_info": worker_info,
        }

    async def register(self, websocket: WebSocket, client_info: dict) -> WorkerConnection:
        """注册新接入的本地客户端 Worker。"""
        worker_id = uuid.uuid4().hex[:12]
        worker = WorkerConnection(
            worker_id=worker_id,
            websocket=websocket,
            client_id=client_info.get("client_id", f"worker-{worker_id}"),
            client_name=client_info.get("client_name", "本地 LearnFlow 节点"),
            version=client_info.get("version", "1.0.0"),
            capabilities=client_info.get("capabilities", []),
        )
        async with self._lock:
            self._workers[worker_id] = worker
        logger.info(
            "本地 Worker 连接注册成功: id=%s, name=%s, version=%s",
            worker_id,
            worker.client_name,
            worker.version,
        )
        return worker

    async def unregister(self, worker_id: str):
        """注销断开的本地 Worker 并唤醒所有挂起的请求。"""
        async with self._lock:
            worker = self._workers.pop(worker_id, None)

        if worker:
            logger.warning("本地 Worker 断开注销: id=%s", worker_id)
            # 通知所有该 worker 上挂起等待响应的请求
            for req_id, q in list(worker.pending_requests.items()):
                await q.put(("error", "本地 Worker 已断开连接"))

    async def handle_message(self, worker: WorkerConnection, raw_message: str):
        """处理本地 Worker 发送过来的 WebSocket 消息。"""
        try:
            msg = json.loads(raw_message)
        except Exception:
            logger.warning("收到无效 JSON 帧: %s", raw_message[:100])
            return

        msg_type = msg.get("type")
        worker.last_heartbeat = time.time()

        # 1. 心跳消息
        if msg_type == "ping":
            try:
                await worker.websocket.send_text(json.dumps({"type": "pong", "timestamp": time.time()}))
            except Exception:
                pass
            return
        elif msg_type == "pong":
            return

        # 2. 注册更新
        elif msg_type == "register":
            worker.client_id = msg.get("client_id", worker.client_id)
            worker.client_name = msg.get("client_name", worker.client_name)
            worker.version = msg.get("version", worker.version)
            worker.capabilities = msg.get("capabilities", worker.capabilities)
            try:
                await worker.websocket.send_text(
                    json.dumps({"type": "registered", "status": "ok", "worker_id": worker.worker_id})
                )
            except Exception:
                pass
            return

        request_id = msg.get("request_id")
        if not request_id:
            return

        queue = worker.pending_requests.get(request_id)
        if not queue:
            # 请求可能已超时或取消
            return

        # 3. 响应启动头信息
        if msg_type in ("response_start", "start"):
            status_code = msg.get("status_code", 200)
            headers = msg.get("headers", {})
            worker.response_metadata[request_id] = {
                "status_code": status_code,
                "headers": headers,
            }
            await queue.put(("start", {"status_code": status_code, "headers": headers}))

        # 4. 响应数据块 Chunk
        elif msg_type in ("chunk", "response_chunk"):
            data = msg.get("data", "")
            is_base64 = msg.get("is_base64", False)
            if is_base64 and isinstance(data, str):
                try:
                    raw_bytes = base64.b64decode(data)
                except Exception:
                    raw_bytes = data.encode("utf-8")
            elif isinstance(data, str):
                raw_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                raw_bytes = data
            else:
                raw_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")

            await queue.put(("chunk", raw_bytes))

        # 5. 响应结束
        elif msg_type in ("end", "response_end"):
            status_code = msg.get("status_code", 200)
            headers = msg.get("headers", {})
            await queue.put(("end", {"status_code": status_code, "headers": headers}))

        # 6. 响应异常
        elif msg_type in ("error", "response_error"):
            detail = msg.get("detail", msg.get("error", "本地处理发生未知异常"))
            await queue.put(("error", str(detail)))

    async def dispatch_request(
        self,
        method: str,
        path: str,
        headers: Optional[dict[str, str]] = None,
        query_params: Optional[dict[str, Any]] = None,
        body: Any = None,
        timeout: float = 180.0,
        meta_out: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[bytes]:
        """将请求打包通过 WebSocket 派发给本地 Worker，并以异步迭代器流式返回字节块。

        适配 FastAPI 的 StreamingResponse。

        meta_out：可选的元信息回填字典。Worker 回传的响应头（"start"/"end" 帧）会写入
        {"status_code": int, "headers": dict}；流式调用方可忽略，聚合调用方（dispatch_full）
        依赖它还原本地真实 HTTP 状态码。
        """
        worker = self.get_active_worker()
        if not worker:
            raise WorkerOfflineError("本地 AI 节点未连接，请启动本地 LearnFlow 客户端并在设置中开启中转。")

        request_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        worker.pending_requests[request_id] = queue

        # 处理 body 内容
        body_str: Optional[str] = None
        is_body_b64 = False
        if body is not None:
            if isinstance(body, bytes):
                try:
                    body_str = body.decode("utf-8")
                except UnicodeDecodeError:
                    body_str = base64.b64encode(body).decode("ascii")
                    is_body_b64 = True
            elif isinstance(body, str):
                body_str = body
            else:
                body_str = json.dumps(body, ensure_ascii=False)

        # 过滤敏感请求头，保留重要业务头
        safe_headers = {}
        if headers:
            for k, v in headers.items():
                k_lower = k.lower()
                if k_lower not in ("host", "content-length", "connection") and k_lower not in _FORWARDED_HEADERS:
                    safe_headers[k] = v

        request_payload = {
            "type": "request",
            "request_id": request_id,
            "method": method.upper(),
            "path": path,
            "headers": safe_headers,
            "query_params": query_params or {},
            "body": body_str,
            "is_body_b64": is_body_b64,
        }

        try:
            await worker.websocket.send_text(json.dumps(request_payload, ensure_ascii=False))
        except Exception as e:
            worker.pending_requests.pop(request_id, None)
            worker.response_metadata.pop(request_id, None)
            raise WorkerOfflineError(f"向本地节点下发请求失败: {e}") from e

        # 流式读取队列中的数据并 yield 出来
        try:
            while True:
                try:
                    event_type, payload = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    raise WorkerRequestTimeoutError(f"等待本地节点响应超时 ({timeout}s)")

                if event_type == "chunk":
                    yield payload
                elif event_type == "end":
                    if meta_out is not None:
                        meta_out["status_code"] = payload.get("status_code", 200)
                        meta_out["headers"] = payload.get("headers", {}) or {}
                    break
                elif event_type == "error":
                    err_text = f"data: {{\"type\":\"error\",\"detail\":{json.dumps(str(payload))}}}\n\n"
                    yield err_text.encode("utf-8")
                    break
                elif event_type == "start":
                    if meta_out is not None:
                        meta_out["status_code"] = payload.get("status_code", 200)
                        meta_out["headers"] = payload.get("headers", {}) or {}
                    # 元信息已记录，继续等待 chunk
                    continue
        finally:
            worker.pending_requests.pop(request_id, None)
            worker.response_metadata.pop(request_id, None)

    async def dispatch_full(
        self,
        method: str,
        path: str,
        headers: Optional[dict[str, str]] = None,
        query_params: Optional[dict[str, Any]] = None,
        body: Any = None,
        timeout: float = 60.0,
    ) -> tuple[int, dict[str, str], bytes]:
        """对于普通非流式 REST 请求，聚合全部返回结果。
        返回 (status_code, headers, body_bytes)。
        """
        worker = self.get_active_worker()
        if not worker:
            raise WorkerOfflineError("本地 AI 节点未连接，请启动本地 LearnFlow 客户端。")

        meta: dict[str, Any] = {}
        chunks: list[bytes] = []

        async for chunk in self.dispatch_request(
            method=method,
            path=path,
            headers=headers,
            query_params=query_params,
            body=body,
            timeout=timeout,
            meta_out=meta,
        ):
            chunks.append(chunk)

        full_body = b"".join(chunks)
        # 还原本地 Worker 回传的真实状态码与响应头（此前硬编码 200，
        # 导致本地 403/401 等错误体被云端以 200 包裹，前端把错误体当业务数据渲染直接崩溃）
        resp_status = meta.get("status_code", 200)
        resp_headers = {
            k: v
            for k, v in (meta.get("headers") or {}).items()
            if k.lower() not in _DROP_RESPONSE_HEADERS
        }
        return resp_status, resp_headers, full_body


tunnel_manager = TunnelManager()


async def handle_relay_websocket(websocket: WebSocket):
    """WebSocket /ws/relay 核心端点处理函数。"""
    # 1. 鉴权校验（若启用）
    if settings.is_auth_enabled():
        # 从 query 或 header 提取 Token
        token = websocket.query_params.get("token", "")
        if not token:
            token = websocket.headers.get("x-server-token") or websocket.headers.get("x-access-token", "")
        if not token:
            cookie_str = websocket.headers.get("cookie", "")
            for part in cookie_str.split(";"):
                part = part.strip()
                if part.startswith("lf_server_token="):
                    token = part[16:]
                    break
                elif part.startswith("lf_token="):
                    token = part[9:]
                    break

        if not verify_token(token):
            logger.warning("本地 Worker 鉴权失败，拒绝连接")
            await websocket.close(code=4401, reason="Unauthorized token")
            return

    await websocket.accept()

    # 提取客户端元信息
    client_info = {
        "client_id": websocket.query_params.get("client_id", "learnflow-local"),
        "client_name": websocket.query_params.get("client_name", "本地 LearnFlow 节点"),
        "version": websocket.query_params.get("version", "1.0.0"),
    }

    worker = await tunnel_manager.register(websocket, client_info)

    # 发送连接建立确认帧
    try:
        await websocket.send_text(
            json.dumps({
                "type": "registered",
                "status": "ok",
                "worker_id": worker.worker_id,
                "server_time": datetime.now(timezone.utc).isoformat(),
            })
        )
    except Exception:
        pass

    try:
        while True:
            raw_text = await websocket.receive_text()
            await tunnel_manager.handle_message(worker, raw_text)
    except WebSocketDisconnect:
        logger.info("Worker WebSocket 正常断开: %s", worker.worker_id)
    except Exception as e:
        logger.warning("Worker WebSocket 异常断开: %s (%s)", worker.worker_id, e)
    finally:
        await tunnel_manager.unregister(worker.worker_id)
