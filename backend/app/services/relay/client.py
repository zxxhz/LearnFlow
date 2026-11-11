"""本地 WebSocket 客户端长连接守护进程。

负责与自建云端中转服务端的 /ws/relay 保持长连接，
支持 Token 认证握手、心跳保活（ping/pong）、指数退避自动重连、
连接状态跟踪与错误记录，并在建立连接后按需触发自动数据同步。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets

from app.models.base import utcnow_iso
from app.services.relay.config import (
    RelayClientConfig,
    get_relay_config,
    normalize_ws_url,
)
from app.services.relay.worker import handle_relay_request

logger = logging.getLogger(__name__)


class RelayClient:
    """管理与云端中转服务器的持久 WebSocket 连接。"""

    def __init__(self) -> None:
        self.status: str = "disconnected"  # disconnected / connecting / connected / error
        self.last_error: str | None = None
        self.last_connected_at: str | None = None
        self.latency_ms: int | None = None

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._current_ws: Any = None
        self._active_worker_tasks: set[asyncio.Task] = set()

    def get_status_dict(self) -> dict[str, Any]:
        """返回当前的连接状态字典。"""
        cfg = get_relay_config()
        return {
            "enabled": cfg.enabled,
            "status": self.status,
            "server_url": cfg.server_url,
            "server_token": cfg.server_token,
            "token": cfg.server_token,  # 前端别名
            "auto_sync": cfg.auto_sync,
            "ai_mode": cfg.ai_mode,
            "actual_ai_mode": cfg.ai_mode,
            "effective_ai_mode": cfg.ai_mode,
            "last_sync_at": cfg.last_sync_at,
            "last_connected_at": self.last_connected_at,
            "last_error": self.last_error,
            "error_message": self.last_error,  # 前端别名
            "latency_ms": self.latency_ms,
        }

    async def start(self) -> None:
        """启动长连接守护进程（若已在运行则忽略）。"""
        if self._task and not self._task.done():
            logger.info("RelayClient 已在运行中")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_daemon())
        logger.info("RelayClient 守护任务已启动")

    async def stop(self) -> None:
        """优雅关闭长连接并取消正在执行的本地 worker 任务。"""
        logger.info("正在停止 RelayClient...")
        self._stop_event.set()

        # 关闭当前活跃 WebSocket
        if self._current_ws:
            try:
                await self._current_ws.close()
            except Exception:
                pass
            self._current_ws = None

        # 取消所有正在执行的 worker 任务
        for t in list(self._active_worker_tasks):
            t.cancel()
        if self._active_worker_tasks:
            await asyncio.gather(*self._active_worker_tasks, return_exceptions=True)
            self._active_worker_tasks.clear()

        # 等待守护主任务退出
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

        self.status = "disconnected"
        logger.info("RelayClient 已安全停止")

    async def restart(self) -> None:
        """重启长连接（常用于用户修改了配置）。"""
        await self.stop()
        cfg = get_relay_config()
        if cfg.enabled:
            await self.start()

    async def send_message(self, message: dict[str, Any]) -> None:
        """将消息放入发送队列，由专用发送协程异步发送。"""
        await self._send_queue.put(message)

    async def _run_daemon(self) -> None:
        """守护主循环：包含重连指数退避机制。"""
        backoff = 2.0
        max_backoff = 30.0

        while not self._stop_event.is_set():
            cfg = get_relay_config()
            if not cfg.enabled:
                self.status = "disconnected"
                self.last_error = None
                logger.info("RelayClient 未启用，守护任务待命...")
                # 挂起直到停止或配置改变唤醒
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                continue

            ws_url = normalize_ws_url(cfg.server_url, cfg.server_token)
            headers = {}
            if cfg.server_token:
                headers["x-server-token"] = cfg.server_token

            self.status = "connecting"
            logger.info("RelayClient 尝试连接云端中转: %s", cfg.server_url)

            try:
                async with websockets.connect(
                    ws_url,
                    additional_headers=headers if headers else None,
                    open_timeout=10.0,
                    ping_interval=25.0,
                    ping_timeout=20.0,
                    close_timeout=5.0,
                    proxy=None,  # 直连 VPS，绕过本地系统代理（避免代理拦截返回 502）
                ) as ws:
                    self._current_ws = ws
                    self.status = "connected"
                    self.last_error = None
                    self.last_connected_at = utcnow_iso()
                    backoff = 2.0  # 连接成功后重置退避时间
                    logger.info("RelayClient 已成功连入云端服务器: %s", cfg.server_url)

                    # 发送欢迎握手帧
                    handshake_msg = {
                        "type": "connected",
                        "client_time": utcnow_iso(),
                        "role": "local_node",
                    }
                    await ws.send(json.dumps(handshake_msg))

                    # 触发自动同步（若配置开启）
                    if cfg.auto_sync:
                        asyncio.create_task(self._trigger_auto_sync())

                    # 创建读写协同协程
                    sender_task = asyncio.create_task(self._sender_loop(ws))
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
                    receiver_task = asyncio.create_task(self._receiver_loop(ws))

                    done, pending = await asyncio.wait(
                        [sender_task, heartbeat_task, receiver_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for p in pending:
                        p.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.status = "error"
                self.last_error = str(exc)
                logger.warning(
                    "RelayClient 连接断开或异常 (%s)，将于 %.1f 秒后尝试重连",
                    exc,
                    backoff,
                )
            finally:
                self._current_ws = None
                if self.status == "connected":
                    self.status = "disconnected"

            if self._stop_event.is_set():
                break

            # 指数退避等待
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 1.5, max_backoff)

        self.status = "disconnected"

    async def _sender_loop(self, ws: Any) -> None:
        """从队列中提取消息并发送至云端 WebSocket。"""
        while not self._stop_event.is_set():
            try:
                msg = await self._send_queue.get()
                payload = json.dumps(msg, ensure_ascii=False)
                await ws.send(payload)
                self._send_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("RelayClient 发送消息失败: %s", exc)
                break

    async def _heartbeat_loop(self, ws: Any) -> None:
        """应用层定时心跳检测与延迟测算。"""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(20.0)
                ping_msg = {
                    "type": "ping",
                    "timestamp": time.time(),
                }
                await ws.send(json.dumps(ping_msg))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("RelayClient 心跳发送异常: %s", exc)
                break

    async def _receiver_loop(self, ws: Any) -> None:
        """接收云端中转分发的消息。"""
        async for raw in ws:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                msg = json.loads(raw)
            except Exception as exc:
                logger.warning("解析来自云端的中转消息失败: %s, raw=%s", exc, raw[:100] if raw else "")
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                # 云端发来的心跳探测，立即回复 pong
                await self.send_message({"type": "pong", "timestamp": msg.get("timestamp")})
            elif msg_type == "pong":
                # 收到心跳回复，计算单程/往返延迟
                sent_ts = msg.get("timestamp")
                if sent_ts and isinstance(sent_ts, (int, float)):
                    self.latency_ms = max(1, int((time.time() - sent_ts) * 1000))
            elif msg_type == "request":
                # 云端转发的 API 请求，启动独立协程在本地执行并推流
                worker_task = asyncio.create_task(
                    handle_relay_request(self.send_message, msg)
                )
                worker_task._relay_request_id = msg.get("request_id")  # 供 cancel 帧定位
                self._active_worker_tasks.add(worker_task)
                worker_task.add_done_callback(self._active_worker_tasks.discard)
            elif msg_type == "cancel":
                # 云端下发的取消帧（v0.5.3 体检 P3）：下游断连/超时后本地中止生成，
                # 不再空烧 LLM token。按 request_id 找到在跑的 worker 任务并 cancel
                request_id = msg.get("request_id")
                for task in list(self._active_worker_tasks):
                    if not task.done() and getattr(task, "_relay_request_id", None) == request_id:
                        task.cancel()
                        break
            else:
                logger.debug("收到其他云端消息: %s", msg)

    async def _trigger_auto_sync(self) -> None:
        """连接就绪后的静默自动数据同步。"""
        try:
            from app.services.relay.sync import push_local_data_to_server

            logger.info("RelayClient: 正在执行初次连接自动数据同步...")
            res = await push_local_data_to_server()
            if res.get("success"):
                logger.info("RelayClient: 自动数据同步成功完成")
            else:
                logger.warning("RelayClient: 自动数据同步提示: %s", res.get("message"))
        except Exception as exc:
            logger.warning("RelayClient: 自动同步遇到异常: %s", exc)


relay_client = RelayClient()


async def test_relay_connection(server_url: str, server_token: str = "") -> dict[str, Any]:
    """主动测试与指定云端服务器的连通性。"""
    ws_url = normalize_ws_url(server_url, server_token)
    headers = {}
    if server_token:
        headers["x-server-token"] = server_token

    start_time = time.time()
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=headers if headers else None,
            open_timeout=6.0,
            close_timeout=3.0,
            proxy=None,  # 直连 VPS，绕过本地系统代理（避免代理拦截返回 502）
        ) as ws:
            latency = max(1, int((time.time() - start_time) * 1000))
            # 发送一次轻量 ping
            await ws.send(json.dumps({"type": "ping", "test": True}))
            return {
                "ok": True,
                "success": True,
                "message": f"成功连接至云端中转服务器 (延迟 {latency}ms)",
                "latency_ms": latency,
            }
    except Exception as exc:
        latency = max(1, int((time.time() - start_time) * 1000))
        err_msg = str(exc)
        if "401" in err_msg or "403" in err_msg:
            detail = "连接被拒绝：Token 认证失败，请检查 Server Token 配置"
        elif "502" in err_msg or "504" in err_msg:
            detail = (
                "网关返回 502/504：通常是本地代理软件拦截了连接，请关闭系统代理或将该服务器地址加入直连规则；"
                "若服务器配置了 Nginx 反代，请检查其 upstream 端口与容器实际监听端口是否一致"
            )
        elif "503" in err_msg:
            detail = "服务端返回 503：云端服务正在维护或本地 Worker 未连接，请稍后重试"
        elif "refused" in err_msg.lower() or "10061" in err_msg:
            detail = f"无法连接到服务器 {server_url}：连接被拒绝，请确认服务端已启动并在指定端口监听"
        else:
            detail = f"连接失败: {err_msg}"
        return {
            "ok": False,
            "success": False,
            "message": detail,
            "latency_ms": latency,
        }
