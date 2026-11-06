"""本地中转配置持久化与管理。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "relay_client_config.json"


class RelayClientConfig(BaseModel):
    """本地客户端中转配置。"""

    enabled: bool = Field(default=False, description="是否启用连接自建云端服务器")
    server_url: str = Field(
        default="http://127.0.0.1:8421",
        description="云端中转服务器地址，如 http://your-server-ip:8421",
    )
    server_token: str = Field(
        default="",
        description="连接云端服务器使用的 Token（若云端未配置或关闭鉴权可为空）",
    )
    auto_sync: bool = Field(
        default=True,
        description="是否在启动连接成功或数据变更时自动同步数据到云端",
    )
    ai_mode: str = Field(
        default="auto",
        description="AI执行偏好模式: auto (智能回退) | local (本地节点) | cloud (云端服务)",
    )
    last_sync_at: str | None = Field(
        default=None,
        description="最后一次成功同步时间 (UTC ISO8601)",
    )


def _config_file_path() -> Path:
    return settings.data_dir / CONFIG_FILENAME


def get_relay_config() -> RelayClientConfig:
    """读取本地中转配置；若文件不存在或损坏则返回默认配置。"""
    cfg_file = _config_file_path()
    if not cfg_file.exists():
        return RelayClientConfig()

    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return RelayClientConfig()
        # 兼容 token 别名字段
        if "token" in data and "server_token" not in data:
            data["server_token"] = data["token"]
        return RelayClientConfig.model_validate(data)
    except Exception as exc:
        logger.warning("读取中转配置文件失败，将使用默认配置: %s", exc)
        return RelayClientConfig()


def save_relay_config(config: RelayClientConfig) -> None:
    """持久化保存中转配置到 settings.data_dir / relay_client_config.json。"""
    cfg_file = _config_file_path()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        temp_file = cfg_file.with_suffix(".tmp")
        temp_file.write_text(
            json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_file.replace(cfg_file)
    except Exception as exc:
        logger.error("保存中转配置文件失败: %s", exc)
        raise


def update_relay_config(**updates) -> RelayClientConfig:
    """部分更新并保存配置。"""
    current = get_relay_config()
    data = current.model_dump()
    for k, v in updates.items():
        if k == "token":
            k = "server_token"
        if k in data and v is not None:
            data[k] = v
    new_config = RelayClientConfig.model_validate(data)
    save_relay_config(new_config)
    return new_config


def normalize_http_url(url: str) -> str:
    """将输入的服务器地址转换为标准 HTTP/HTTPS 根地址。"""
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return "http://127.0.0.1:8421"

    if raw.startswith("ws://"):
        raw = "http://" + raw[5:]
    elif raw.startswith("wss://"):
        raw = "https://" + raw[6:]
    elif not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "http://" + raw

    # 移除末尾多余的 /ws/relay 或 /api 路径（若用户粘贴了完整路径）
    parsed = urlparse(raw)
    path = parsed.path
    for suffix in ("/ws/relay", "/ws", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    
    port_part = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port_part}{path}".rstrip("/")


def normalize_ws_url(url: str, token: str = "") -> str:
    """将输入的服务器地址转换为 WebSocket 长连地址（末尾含 /ws/relay 及可选 token）。"""
    http_base = normalize_http_url(url)
    if http_base.startswith("https://"):
        ws_base = "wss://" + http_base[8:]
    else:
        ws_base = "ws://" + http_base[7:]

    ws_url = f"{ws_base}/ws/relay"
    if token and token.strip():
        sep = "&" if "?" in ws_url else "?"
        ws_url = f"{ws_url}{sep}token={quote(token.strip())}"
    return ws_url
