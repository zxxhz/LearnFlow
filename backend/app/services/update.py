"""更新检查（PRD 实现备注 15）：查询 GitHub Releases 最新版并与 APP_VERSION 比较。

- 仓库来源：环境变量 APP_GITHUB_REPO → 内置默认 zxxhz/LearnFlow（无需配置）
- 非阻塞：短超时（5s），任何失败都优雅降级为不可用，绝不影响应用启动与使用
- 节流：自动检查（打开应用时前端触发）1 小时内不重复请求；设置页按钮可强制刷新
"""
import logging
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import APP_VERSION, settings as app_settings

logger = logging.getLogger(__name__)

AUTO_INTERVAL_SECONDS = 3600
REQUEST_TIMEOUT = 5.0

_cache: dict = {"checked_at": 0.0, "result": None}


def _ver_tuple(v: str) -> tuple:
    """'v1.2.3-beta' → (1, 2, 3, is_release)。用于简单比较。"""
    v = v.strip().lstrip("vV")
    main, _, pre = v.partition("-")
    parts = []
    for p in main.split(".")[:3]:
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts) + (0 if pre else 1,)


def has_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    return _ver_tuple(latest) > _ver_tuple(current)


async def fetch_latest_release(repo: str) -> dict:
    """请求 GitHub Releases latest；抛出异常由调用方处理。"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "LearnFlow-Update-Check", "Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
    return {
        "tag": str(data.get("tag_name") or "").strip(),
        "url": str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        "notes": str(data.get("body") or "")[:2000],
        "prerelease": bool(data.get("prerelease")),
    }


def _effective_repo() -> str:
    """仓库来源：环境变量 APP_GITHUB_REPO → 内置默认 zxxhz/LearnFlow。
    （用户偏好里的 github_repo 设置已移除：默认仓库即官方仓库，老库存量键忽略。）"""
    return (app_settings.github_repo or "").strip().strip("/")


async def check_update(db: AsyncSession, force: bool = False) -> dict:
    """返回 {has_update, current, latest?, url?, notes?, error?, repo?}。失败不抛出。"""
    now = time.time()
    if (
        not force
        and _cache["result"] is not None
        and now - _cache["checked_at"] < AUTO_INTERVAL_SECONDS
    ):
        return _cache["result"]

    result: dict = {"has_update": False, "current": APP_VERSION}
    repo = _effective_repo()
    if not repo:
        result["error"] = "未配置仓库（设置页填 GitHub 仓库，或设置 APP_GITHUB_REPO）"
        _cache.update(checked_at=now, result=result)
        return result
    result["repo"] = repo

    try:
        release = await fetch_latest_release(repo)
        latest = release["tag"]
        if latest:
            result["latest"] = latest
            result["has_update"] = has_newer_version(latest)
            if result["has_update"]:
                result["url"] = release["url"]
                result["notes"] = release["notes"]
        else:
            result["error"] = "仓库尚无正式发布版本"
    except Exception as e:  # noqa: BLE001  网络不通/仓库不存在 → 静默降级
        logger.info("update check failed: %s", e)
        result["error"] = "检查失败（网络不可达、仓库不存在或接口限流）"

    _cache.update(checked_at=now, result=result)
    return result
