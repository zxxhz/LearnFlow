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


DOMESTIC_MIRRORS = [
    # 优先国内主流 GitHub 文件代理获取 latest.json（带 CDN，无 API 限流且直达最新版）
    ("latest_json", "https://ghproxy.net/https://github.com/{repo}/releases/latest/download/latest.json"),
    ("latest_json", "https://gh-proxy.com/https://github.com/{repo}/releases/latest/download/latest.json"),
    ("latest_json", "https://ghfast.top/https://github.com/{repo}/releases/latest/download/latest.json"),
    # API 镜像代理获取完整 release 信息
    ("api", "https://ghproxy.net/https://api.github.com/repos/{repo}/releases/latest"),
]


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


def _parse_api_release(data: dict, repo: str) -> dict:
    return {
        "tag": str(data.get("tag_name") or "").strip(),
        "url": str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        "notes": str(data.get("body") or "")[:2000],
        "prerelease": bool(data.get("prerelease")),
    }


def _parse_latest_json(data: dict, repo: str) -> dict:
    ver = str(data.get("version") or "").strip()
    tag = ver if ver.startswith("v") or ver.startswith("V") else f"v{ver}"
    notes = str(data.get("notes") or data.get("body") or "")[:2000]
    return {
        "tag": tag,
        "url": f"https://github.com/{repo}/releases/tag/{tag}",
        "notes": notes,
        "prerelease": False,
    }


async def fetch_latest_release(repo: str) -> dict:
    """请求最新版本信息：优先官方 GitHub API，若网络不可达/超时/限流则自动无缝回退国内镜像。"""
    official_url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"User-Agent": "LearnFlow-Update-Check", "Accept": "application/vnd.github+json"}

    # 1. 优先尝试官方源（超时设为 4.0 秒，避免长时间阻塞前端）
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            resp = await client.get(official_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("tag_name"):
                return _parse_api_release(data, repo)
    except Exception as e:
        logger.info("GitHub 官方更新接口不可达 (%s)，正在自动切换至国内镜像源...", e)

    # 2. 官方源不可达，依次尝试国内镜像
    for kind, template in DOMESTIC_MIRRORS:
        mirror_url = template.format(repo=repo)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(mirror_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if kind == "api" and data.get("tag_name"):
                    logger.info("通过国内镜像源成功获取更新: %s", mirror_url)
                    return _parse_api_release(data, repo)
                elif kind == "latest_json" and data.get("version"):
                    logger.info("通过国内镜像源成功获取更新: %s", mirror_url)
                    return _parse_latest_json(data, repo)
        except Exception as mirror_err:
            logger.debug("国内镜像源尝试失败: %s (%s)", mirror_url, mirror_err)

    raise RuntimeError("所有更新检查端点（官方与国内镜像）均不可达")


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
            result["has_update"] = has_newer_version(latest, APP_VERSION)
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
