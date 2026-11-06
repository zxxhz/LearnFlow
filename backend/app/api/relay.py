"""本地客户端中转控制 API。

提供中转配置读取与更新、实时连接状态检测、连通性探测、AI模式切换以及双向数据同步接口。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.relay.client import relay_client, test_relay_connection
from app.services.relay.config import (
    RelayClientConfig,
    get_relay_config,
    save_relay_config,
    update_relay_config,
)
from app.services.relay.sync import (
    execute_bi_directional_sync,
    pull_cloud_data_to_local,
    push_local_data_to_server,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/relay", tags=["relay"])


class UpdateRelayConfigRequest(BaseModel):
    """更新中转配置请求体。"""

    enabled: bool | None = Field(default=None, description="是否启用中转连接")
    server_url: str | None = Field(default=None, description="云端中转服务器地址")
    server_token: str | None = Field(default=None, description="云端鉴权 Token")
    token: str | None = Field(default=None, description="别名：云端鉴权 Token")
    auto_sync: bool | None = Field(default=None, description="是否开启自动同步")
    ai_mode: str | None = Field(default=None, description="AI模式: auto | local | cloud")


class AIModeRequest(BaseModel):
    """设置 AI 模式请求体。"""

    ai_mode: str = Field(description="AI执行偏好模式: auto (智能回退) | local (本地节点) | cloud (云端服务)")


class TestConnectionRequest(BaseModel):
    """测试服务器连通性请求体。"""

    server_url: str | None = Field(default=None, description="测试的目标服务器地址，为空则使用已保存配置")
    server_token: str | None = Field(default=None, description="鉴权 Token")
    token: str | None = Field(default=None, description="别名：鉴权 Token")


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """获取当前中转配置与连接状态。"""
    return relay_client.get_status_dict()


@router.put("/config")
@router.post("/config")
async def update_config(body: UpdateRelayConfigRequest) -> dict[str, Any]:
    """更新中转配置，若配置变更且开启则立即重启长连接守护进程。"""
    effective_token = body.server_token if body.server_token is not None else body.token
    updates: dict[str, Any] = {}
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.server_url is not None:
        updates["server_url"] = body.server_url
    if effective_token is not None:
        updates["server_token"] = effective_token
    if body.auto_sync is not None:
        updates["auto_sync"] = body.auto_sync
    if body.ai_mode is not None:
        mode = body.ai_mode.strip().lower()
        if mode in ("auto", "local", "cloud"):
            updates["ai_mode"] = mode

    new_cfg = update_relay_config(**updates)
    logger.info("中转配置已更新: enabled=%s, server=%s, ai_mode=%s", new_cfg.enabled, new_cfg.server_url, new_cfg.ai_mode)

    # 触发连接状态调整
    if new_cfg.enabled:
        await relay_client.restart()
    else:
        await relay_client.stop()

    return relay_client.get_status_dict()


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """获取当前与云端中转服务器的实时连接状态。"""
    return relay_client.get_status_dict()


@router.get("/ai-mode")
async def get_ai_mode() -> dict[str, Any]:
    """获取本地配置的 AI 执行偏好模式。"""
    cfg = get_relay_config()
    return {
        "ok": True,
        "ai_mode": cfg.ai_mode,
        "actual_ai_mode": cfg.ai_mode,
        "effective_ai_mode": cfg.ai_mode,
        "server_url": cfg.server_url,
    }


@router.put("/ai-mode")
@router.post("/ai-mode")
async def set_ai_mode(body: AIModeRequest) -> dict[str, Any]:
    """设置本地配置的 AI 执行偏好模式 (auto | local | cloud)。"""
    mode = body.ai_mode.strip().lower()
    if mode not in ("auto", "local", "cloud"):
        return {
            "ok": False,
            "success": False,
            "message": "AI 模式仅支持 auto (智能回退)、local (本地节点) 或 cloud (云端服务)",
        }
    new_cfg = update_relay_config(ai_mode=mode)
    logger.info("AI 执行模式已更新为: %s", mode)
    return {
        "ok": True,
        "success": True,
        "ai_mode": new_cfg.ai_mode,
        "actual_ai_mode": new_cfg.ai_mode,
        "effective_ai_mode": new_cfg.ai_mode,
        "message": f"AI 执行模式已切换为 {mode}",
    }


@router.post("/sync/pull")
async def sync_pull() -> dict[str, Any]:
    """从云端服务器单向拉取数据并合并到本地。"""
    cfg = get_relay_config()
    return await pull_cloud_data_to_local(
        server_url=cfg.server_url,
        server_token=cfg.server_token,
    )


@router.post("/sync/push")
async def sync_push() -> dict[str, Any]:
    """单向将本地数据推送至云端中转服务器。"""
    cfg = get_relay_config()
    return await push_local_data_to_server(
        server_url=cfg.server_url,
        server_token=cfg.server_token,
    )


@router.post("/sync/both")
@router.post("/sync/now")
async def sync_both() -> dict[str, Any]:
    """执行双向数据同步（先拉取云端合并，再将本地最新数据推向云端）。"""
    cfg = get_relay_config()
    return await execute_bi_directional_sync(
        server_url=cfg.server_url,
        server_token=cfg.server_token,
    )


@router.post("/test-connection")
@router.post("/test")
async def test_connection(body: TestConnectionRequest | None = None) -> dict[str, Any]:
    """测试与指定云端服务器的连通性。"""
    cfg = get_relay_config()
    target_url = (body.server_url if body and body.server_url else None) or cfg.server_url
    effective_token = (
        (body.server_token if body and body.server_token is not None else (body.token if body else None))
        if body and (body.server_token is not None or body.token is not None)
        else cfg.server_token
    )
    if not target_url:
        return {
            "ok": False,
            "success": False,
            "message": "请先输入云端服务器地址",
            "latency_ms": None,
        }

    return await test_relay_connection(target_url, effective_token or "")
