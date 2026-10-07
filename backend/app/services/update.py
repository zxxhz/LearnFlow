"""更新检查（PRD 实现备注 15）：查询 GitHub Releases 最新版并与 APP_VERSION 比较。

- 仓库来源：环境变量 APP_GITHUB_REPO → 内置默认 zxxhz/LearnFlow（无需配置）
- 非阻塞：短超时（5s），任何失败都优雅降级为不可用，绝不影响应用启动与使用
- 节流：自动检查（打开应用时前端触发）1 小时内不重复请求；设置页按钮可强制刷新
- 跨版本日志聚合：若当前版本为 0.0.1，最新版本为 0.0.4，将聚合中间所有已发布版本的更新说明，跳过无日志或不存在的版本
"""
import logging
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import APP_VERSION, settings as app_settings
from app.services.download_mirrors import (
    apply_mirror,
    get_active_mirror,
    get_ordered_mirror_prefixes,
)

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


def aggregate_release_notes(releases: list[dict], current: str, latest: str) -> str:
    """聚合 current < tag <= latest 的所有有效发布日志。
    按版本号降序（新版在上）排列。若某版本无发布或日志为空，自动跳过。
    """
    cur_tuple = _ver_tuple(current)
    lat_tuple = _ver_tuple(latest)

    matched = []
    for r in releases:
        if r.get("draft"):
            continue
        tag = str(r.get("tag_name") or "").strip()
        if not tag:
            continue
        v_tuple = _ver_tuple(tag)
        if cur_tuple < v_tuple <= lat_tuple:
            matched.append((v_tuple, tag, r))

    matched.sort(key=lambda x: x[0], reverse=True)

    sections = []
    for _, tag, r in matched:
        body = str(r.get("body") or "").strip()
        if not body:
            continue  # 没有日志则跳过，不输出空内容

        first_line = body.split("\n", 1)[0].strip()
        tag_clean = tag.lstrip("vV")
        if not (first_line.startswith("#") and (tag in first_line or tag_clean in first_line)):
            body = f"### {tag}\n\n{body}"

        sections.append(body[:3000])

    return "\n\n---\n\n".join(sections)[:10000]


def _parse_api_release(data: dict, repo: str) -> dict:
    return {
        "tag": str(data.get("tag_name") or "").strip(),
        "url": str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        "notes": str(data.get("body") or "")[:4000],
        "prerelease": bool(data.get("prerelease")),
    }


def _parse_latest_json(data: dict, repo: str) -> dict:
    ver = str(data.get("version") or "").strip()
    tag = ver if ver.startswith("v") or ver.startswith("V") else f"v{ver}"
    notes = str(data.get("notes") or data.get("body") or "")[:4000]
    return {
        "tag": tag,
        "url": f"https://github.com/{repo}/releases/tag/{tag}",
        "notes": notes,
        "prerelease": False,
    }


async def fetch_releases_list(repo: str) -> list[dict]:
    """尝试获取 releases 列表（最近 30 条），用于跨版本日志聚合。"""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
    headers = {"User-Agent": "LearnFlow-Update-Check", "Accept": "application/vnd.github+json"}

    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.info("GitHub 官方 releases 列表接口不可达 (%s)，将尝试单版本接口或国内镜像...", e)

    return []


async def fetch_latest_release(repo: str) -> dict:
    """请求最新版本信息：优先官方 GitHub API，若网络不可达/超时/限流则自动无缝回退国内镜像（按测速优选）。"""
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

    # 2. 官方源不可达，按测速优选顺序依次尝试国内镜像
    ordered_prefixes = [p for p in get_ordered_mirror_prefixes() if p]
    for prefix in ordered_prefixes:
        mirror_url = f"{prefix}https://github.com/{repo}/releases/latest/download/latest.json"
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(mirror_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if data.get("version"):
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
    """返回 {has_update, current, latest?, url?, accelerated_url?, active_mirror?, notes?, error?, repo?}。失败不抛出。"""
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

    # 1. 优先尝试通过 releases 列表获取，支持跨版本日志聚合
    try:
        releases = await fetch_releases_list(repo)
        if releases:
            valid_releases = [r for r in releases if not r.get("draft") and r.get("tag_name")]
            if valid_releases:
                valid_releases.sort(key=lambda r: _ver_tuple(str(r.get("tag_name", ""))), reverse=True)
                latest_rel = valid_releases[0]
                latest_tag = str(latest_rel.get("tag_name") or "").strip()
                if latest_tag:
                    result["latest"] = latest_tag
                    result["has_update"] = has_newer_version(latest_tag, APP_VERSION)
                    if result["has_update"]:
                        result["url"] = str(latest_rel.get("html_url") or f"https://github.com/{repo}/releases/tag/{latest_tag}")
                        clean_tag = latest_tag.lstrip("vV")
                        direct_exe = f"https://github.com/{repo}/releases/download/{latest_tag}/LearnFlow_{clean_tag}_x64-setup.exe"
                        result["accelerated_url"] = apply_mirror(direct_exe)
                        active = get_active_mirror()
                        result["active_mirror"] = active.get("name")
                        aggregated = aggregate_release_notes(valid_releases, current=APP_VERSION, latest=latest_tag)
                        result["notes"] = aggregated or str(latest_rel.get("body") or "")[:4000]
                    _cache.update(checked_at=now, result=result)
                    return result
    except Exception as e:
        logger.info("获取 releases 列表聚合失败 (%s)，回退至单版本接口...", e)

    # 2. 回退机制：通过 fetch_latest_release 检查（官方/国内镜像 latest.json）
    try:
        release = await fetch_latest_release(repo)
        latest = release["tag"]
        if latest:
            result["latest"] = latest
            result["has_update"] = has_newer_version(latest, APP_VERSION)
            if result["has_update"]:
                result["url"] = release["url"]
                clean_tag = latest.lstrip("vV")
                direct_exe = f"https://github.com/{repo}/releases/download/{latest}/LearnFlow_{clean_tag}_x64-setup.exe"
                result["accelerated_url"] = apply_mirror(direct_exe)
                active = get_active_mirror()
                result["active_mirror"] = active.get("name")
                result["notes"] = release["notes"]
        else:
            result["error"] = "仓库尚无正式发布版本"
    except Exception as e:  # noqa: BLE001  网络不通/仓库不存在 → 静默降级
        logger.info("update check failed: %s", e)
        result["error"] = "检查失败（网络不可达、仓库不存在或接口限流）"

    _cache.update(checked_at=now, result=result)
    return result
