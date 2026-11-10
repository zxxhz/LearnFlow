"""系统版本检测与在线更新 API。

端点：
- GET /api/relay/system/version: 获取服务端当前版本、云端最新版本、发布日志及更新支持能力。
- POST /api/relay/system/update: 触发服务端在线更新（支持 Watchtower API、Docker Socket 或更新指令）。
"""
import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import urllib.request
import urllib.error

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.auth import require_token
from server.config import settings

logger = logging.getLogger("server.system")

router = APIRouter(prefix="/api/relay/system", tags=["system"])

# 内存缓存：避免高频请求 GitHub Releases API 触发 60次/小时 的 IP 限流
_CACHE_TTL_SECONDS = 600  # 10 分钟缓存
_version_cache: dict[str, Any] = {
    "timestamp": 0.0,
    "data": None,
}


def _is_running_in_container() -> bool:
    """判断当前服务是否运行在 Docker 容器内部。"""
    if Path("/.dockerenv").exists():
        return True
    try:
        with open("/proc/1/cgroup", "rt", encoding="utf-8") as f:
            content = f.read()
            if "docker" in content or "containerd" in content or "kubepods" in content:
                return True
    except Exception:
        pass
    return False


def _get_docker_socket_path() -> Optional[str]:
    """检查可用的 Docker Unix Socket 路径。"""
    sock_path = os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
    if os.path.exists(sock_path):
        return sock_path
    return None


def _get_container_id() -> Optional[str]:
    """尝试获取本容器的短 ID 或主机名。"""
    hostname = socket.gethostname()
    if hostname and re.match(r"^[0-9a-f]{12,64}$", hostname):
        return hostname
    try:
        with open("/etc/hostname", "rt", encoding="utf-8") as f:
            h = f.read().strip()
            if re.match(r"^[0-9a-f]{12,64}$", h):
                return h
    except Exception:
        pass
    return None


def _parse_semver(ver: str) -> tuple[int, ...]:
    """提取语义版本数字用于对比，例如 'v0.4.70' -> (0, 4, 70)。"""
    nums = re.findall(r"\d+", ver)
    return tuple(int(n) for n in nums) if nums else (0, 0, 0)


async def _fetch_github_latest_release(repo: str) -> dict[str, Any]:
    """从 GitHub API 获取最新发布版本（带内存缓存与超时防护）。"""
    now = time.time()
    if _version_cache["data"] and (now - _version_cache["timestamp"] < _CACHE_TTL_SECONDS):
        return _version_cache["data"]

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LearnFlow-Relay-Server-Updater",
            "Accept": "application/vnd.github.v3+json",
        },
    )

    def _sync_fetch() -> dict[str, Any]:
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return {
                        "tag_name": data.get("tag_name", ""),
                        "name": data.get("name", ""),
                        "body": data.get("body", ""),
                        "published_at": data.get("published_at", ""),
                        "html_url": data.get("html_url", ""),
                        "error": None,
                    }
        except Exception as e:
            logger.warning("检查 GitHub 最新版本失败: %s", e)
            return {"error": str(e)}
        return {"error": "请求无响应"}

    result = await asyncio.to_thread(_sync_fetch)
    if not result.get("error"):
        _version_cache["timestamp"] = now
        _version_cache["data"] = result
    return result


@router.get("/version")
async def get_version_info():
    """获取当前服务端版本与 GitHub 最新版本信息。"""
    current_ver = settings.server_version
    repo = settings.github_repo
    in_container = _is_running_in_container()
    docker_sock = _get_docker_socket_path()

    can_auto_update = False
    update_driver = "manual"

    # 判断可用自动更新机制：以挂载的 Docker Socket 直连为主力标准
    if os.getenv("UPDATE_COMMAND"):
        can_auto_update = True
        update_driver = "command"
    elif docker_sock and (os.access(docker_sock, os.W_OK) or os.name == "nt"):
        can_auto_update = True
        update_driver = "docker_socket"

    rel_info = await _fetch_github_latest_release(repo)
    latest_tag = rel_info.get("tag_name", "")
    has_update = False
    if latest_tag:
        cur_tuple = _parse_semver(current_ver)
        latest_tuple = _parse_semver(latest_tag)
        if latest_tuple > cur_tuple:
            has_update = True

    return {
        "current_version": current_ver,
        "latest_version": latest_tag or current_ver,
        "has_update": has_update,
        "release_title": rel_info.get("name") or latest_tag,
        "release_notes": rel_info.get("body", ""),
        "published_at": rel_info.get("published_at", ""),
        "html_url": rel_info.get("html_url", f"https://github.com/{repo}/releases"),
        "in_container": in_container,
        "can_auto_update": can_auto_update,
        "update_driver": update_driver,
        "check_error": rel_info.get("error"),
    }


class UpdateTriggerResponse(BaseModel):
    status: str
    message: str
    driver: str
    estimated_seconds: int


@router.post("/update", response_model=UpdateTriggerResponse)
async def trigger_system_update(_: bool = Depends(require_token)):
    """触发服务端在线更新并重启。需要管理 Token 鉴权。"""
    logger.info("收到系统在线更新触发请求...")

    # 1. 优先尝试自定义命令（若配置）
    custom_cmd = os.getenv("UPDATE_COMMAND")
    if custom_cmd:
        logger.info("执行自定义更新命令: %s", custom_cmd)
        try:
            subprocess.Popen(custom_cmd, shell=True)
            return UpdateTriggerResponse(
                status="triggered",
                message="已执行自定义更新脚本，服务正在重新构建/启动中...",
                driver="command",
                estimated_seconds=20,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"执行自定义更新命令失败: {e}")

    # 2. 核心标准：通过挂载的 Docker Socket 直连 Docker 引擎拉取最新镜像并重启
    docker_sock = _get_docker_socket_path()
    if docker_sock:
        # 发起异步任务，避免阻塞本次 HTTP 响应返回给前端
        async def _docker_pull_and_restart():
            await asyncio.sleep(1.0)
            image_name = "ghcr.io/zxxhz/learnflow-server:latest"
            logger.info("通过 Docker Socket 拉取最新镜像: %s", image_name)

            # 使用 curl --unix-socket 调用 Docker Engine API 拉取镜像
            pull_cmd = [
                "curl", "-s", "-X", "POST",
                "--unix-socket", docker_sock,
                f"http://localhost/images/create?fromImage={image_name}"
            ]
            try:
                proc = await asyncio.create_subprocess_exec(*pull_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                await proc.communicate()
            except Exception as e:
                logger.error("通过 Docker Socket 拉取镜像失败: %s", e)
                return

            cid = _get_container_id()
            if cid:
                logger.info("正在重启当前容器: %s", cid)
                restart_cmd = [
                    "curl", "-s", "-X", "POST",
                    "--unix-socket", docker_sock,
                    f"http://localhost/containers/{cid}/restart"
                ]
                try:
                    p = await asyncio.create_subprocess_exec(*restart_cmd)
                    await p.communicate()
                except Exception as e:
                    logger.error("重启容器失败: %s", e)

        asyncio.create_task(_docker_pull_and_restart())

        return UpdateTriggerResponse(
            status="triggered",
            message="已通过 Docker Socket 触发最新镜像拉取与容器平滑重启，服务预计 15 秒内就绪",
            driver="docker_socket",
            estimated_seconds=15,
        )

    # 3. 未挂载 Socket 时的保底友好提示
    return UpdateTriggerResponse(
        status="manual_required",
        message="当前未挂载 /var/run/docker.sock。请在服务器执行: docker compose pull && docker compose up -d",
        driver="manual",
        estimated_seconds=0,
    )
