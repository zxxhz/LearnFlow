"""数据同步与中转服务器状态 API。

端点：
- POST /api/relay/sync/push：接收本地客户端上传的结构化数据并写入云端 SQLite。
- GET /api/relay/sync/pull：从云端拉取已同步的全部结构化数据。
- GET /api/relay/status：获取中转服务端状态、本地 Worker 连接状态、AI 模式、Token 鉴权状态及云端存储统计。
- GET /api/relay/ai-mode：获取当前服务端的 AI 模式与内置大模型配置。
- POST /api/relay/ai-mode：动态切换 AI 模式（cloud/local/auto）及热更新服务端大模型配置。
- GET /api/relay/health 或 /health：健康检查接口。
"""
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel

from server.auth import require_token
from server.config import settings
from server.db import relay_db
from server.tunnel import tunnel_manager

router = APIRouter(prefix="/api/relay", tags=["relay"])


class SyncPushPayload(BaseModel):
    courses: Optional[list[dict[str, Any]]] = None
    documents: Optional[list[dict[str, Any]]] = None
    banks: Optional[list[dict[str, Any]]] = None
    question_banks: Optional[list[dict[str, Any]]] = None
    bank_questions: Optional[list[dict[str, Any]]] = None
    questions: Optional[list[dict[str, Any]]] = None
    bank_attempts: Optional[list[dict[str, Any]]] = None
    attempts: Optional[list[dict[str, Any]]] = None
    mistakes: Optional[list[dict[str, Any]]] = None
    wrong_questions: Optional[list[dict[str, Any]]] = None
    mindmaps: Optional[list[dict[str, Any]]] = None
    annotations: Optional[list[dict[str, Any]]] = None
    learner_profile: Optional[dict[str, Any]] = None
    synced_at: Optional[str] = None

    class Config:
        extra = "allow"


class AiModeUpdateRequest(BaseModel):
    ai_mode: Optional[Literal["cloud", "local", "auto"]] = None
    server_llm_base_url: Optional[str] = None
    server_llm_api_key: Optional[str] = None
    server_llm_model: Optional[str] = None


@router.post("/sync/push")
async def sync_push(
    payload: dict[str, Any] = Body(...),
    _: bool = Depends(require_token),
):
    """接收本地客户端上传的结构化数据，批量保存至云端 SQLite。"""
    try:
        result = await relay_db.save_sync_payload(payload)
        return {
            "ok": True,
            "message": "数据同步成功",
            "synced_at": result["synced_at"],
            "counts": result["counts"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"数据落库异常: {e}",
        )


@router.get("/sync/pull")
async def sync_pull(_: bool = Depends(require_token)):
    """从云端拉取已存储的全部数据包（供本地客户端同步拉取合并）。"""
    try:
        data = await relay_db.get_sync_payload()
        return {
            "ok": True,
            **data,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"数据拉取失败: {e}",
        )


@router.get("/ai-mode")
async def get_ai_mode():
    """获取当前服务端 AI 执行模式与内置大模型状态。"""
    return {
        "ai_mode": settings.ai_mode,
        "server_llm_configured": settings.is_server_llm_configured(),
        "server_llm_model": settings.server_llm_model,
        "server_llm_base_url": settings.server_llm_base_url,
        "worker_online": tunnel_manager.is_worker_online(),
    }


@router.post("/ai-mode")
async def update_ai_mode(
    req: AiModeUpdateRequest,
    _: bool = Depends(require_token),
):
    """更新服务端 AI 执行模式与大模型配置。"""
    if req.ai_mode is not None:
        settings.ai_mode = req.ai_mode
    if req.server_llm_base_url is not None:
        settings.server_llm_base_url = req.server_llm_base_url.rstrip("/")
    if req.server_llm_api_key is not None:
        settings.server_llm_api_key = req.server_llm_api_key.strip()
    if req.server_llm_model is not None:
        settings.server_llm_model = req.server_llm_model.strip()

    return {
        "ok": True,
        "message": f"AI 模式已切换为 {settings.ai_mode}",
        "ai_mode": settings.ai_mode,
        "server_llm_configured": settings.is_server_llm_configured(),
        "server_llm_model": settings.server_llm_model,
        "server_llm_base_url": settings.server_llm_base_url,
    }


@router.get("/status")
async def relay_status():
    """获取中转服务器运行状态（包括 Worker 在线情况、AI 模式与数据存储指标）。"""
    tunnel_status = tunnel_manager.get_status()
    db_stats = await relay_db.get_db_stats()

    return {
        "status": "running",
        "service": "LearnFlow-Relay-Server",
        "version": "1.0.0",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "auth": {
            "required": settings.relay_auth_required,
            "enabled": settings.is_auth_enabled(),
        },
        "ai": {
            "mode": settings.ai_mode,
            "server_llm_configured": settings.is_server_llm_configured(),
            "server_llm_model": settings.server_llm_model,
            "server_llm_base_url": settings.server_llm_base_url,
        },
        "tunnel": {
            "worker_online": tunnel_status["online"],
            "worker_count": tunnel_status["worker_count"],
            "worker_info": tunnel_status["worker_info"],
        },
        "storage": {
            "db_path": str(relay_db.db_path),
            "stats": db_stats,
        },
    }


@router.get("/health")
async def relay_health():
    """轻量级探针检测。"""
    return {
        "status": "ok",
        "service": "LearnFlow-Relay-Server",
        "worker_online": tunnel_manager.is_worker_online(),
        "ai_mode": settings.ai_mode,
        "auth_enabled": settings.is_auth_enabled(),
    }
