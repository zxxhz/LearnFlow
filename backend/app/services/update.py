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


def _find_learnflow_desktop_exe() -> str:
    """查找 LearnFlow 桌面端主程序（learnflow-desktop.exe）的绝对路径。"""
    import os
    import sys
    from pathlib import Path

    names = ["learnflow-desktop.exe", "LearnFlow.exe"]

    # 1. 优先从当前可执行文件（如 .../LearnFlow/backend/learnflow-backend.exe）的父级目录查找
    cur = Path(sys.executable).resolve()
    for parent in [cur.parent, cur.parent.parent, cur.parent.parent.parent]:
        for name in names:
            candidate = parent / name
            if candidate.exists():
                return str(candidate)

    # 2. 查找 LOCALAPPDATA 与 ProgramFiles 常见安装目录
    search_dirs: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        search_dirs.extend([
            Path(local_appdata) / "LearnFlow",
            Path(local_appdata) / "Programs" / "LearnFlow",
        ])
    prog_files = os.environ.get("ProgramFiles", "")
    if prog_files:
        search_dirs.append(Path(prog_files) / "LearnFlow")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    if prog_files_x86:
        search_dirs.append(Path(prog_files_x86) / "LearnFlow")

    for d in search_dirs:
        for name in names:
            candidate = d / name
            if candidate.exists():
                return str(candidate)

    return ""


def _trigger_silent_installer(installer_path: "Path") -> None:
    """在后台独立进程中启动 NSIS 静默安装，杀掉旧进程释放文件锁，安装完成后拉起新版客户端。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    learnflow_exe = _find_learnflow_desktop_exe()
    bat_path = installer_path.parent / "silent_install.bat"
    launch_line = f'start "" "{learnflow_exe}"' if learnflow_exe else ""

    bat_content = f"""@echo off
rem 等待 1 秒以确保当前网络响应发送完毕
timeout /t 1 /nobreak >nul
rem 主动终止旧版本前端壳与后端，释放所有文件占用
taskkill /F /T /IM learnflow-desktop.exe >nul 2>&1
taskkill /F /T /IM LearnFlow.exe >nul 2>&1
taskkill /F /T /IM learnflow-backend.exe >nul 2>&1
timeout /t 1 /nobreak >nul
rem 启动静默安装并等待安装结束
start /wait "" "{installer_path}" /S
timeout /t 1 /nobreak >nul
rem 自动拉起新版本主程序
{launch_line}
del "%~f0"
"""
    try:
        bat_path.write_text(bat_content, encoding="gbk")
    except Exception:
        bat_path.write_text(bat_content, encoding="utf-8")

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=creationflags,
        close_fds=True,
    )
    logger.info("已触发后台静默安装脚本（主程序路径: %s）: %s", learnflow_exe, bat_path)


async def stream_download_and_install(target_version: str, direct_url: str | None = None):
    """通过加速镜像源流式下载最新安装包，向前端实时推送进度，并在完成后以静默模式触发安装。"""
    import json
    import tempfile
    from pathlib import Path

    repo = _effective_repo() or "zxxhz/LearnFlow"
    clean_v = target_version.lstrip("vV")
    raw_github_exe = f"https://github.com/{repo}/releases/download/v{clean_v}/LearnFlow_{clean_v}_x64-setup.exe"

    # 确定候选下载 URL 列表（首选用已加速链接或当前最优镜像，随后按测速优先级排序）
    urls_to_try: list[str] = []
    if direct_url and direct_url.strip():
        urls_to_try.append(direct_url.strip())

    active_accelerated = apply_mirror(raw_github_exe)
    if active_accelerated not in urls_to_try:
        urls_to_try.append(active_accelerated)

    for prefix in get_ordered_mirror_prefixes():
        p_url = f"{prefix}{raw_github_exe}" if prefix else raw_github_exe
        if p_url not in urls_to_try:
            urls_to_try.append(p_url)

    temp_dir = Path(tempfile.gettempdir()) / "LearnFlow_Update"
    temp_dir.mkdir(parents=True, exist_ok=True)
    installer_path = temp_dir / f"LearnFlow_{clean_v}_x64-setup.exe"

    headers = {"User-Agent": "LearnFlow-InAppUpdater/1.0"}
    success = False
    last_error = ""

    for url in urls_to_try:
        try:
            logger.info("尝试从下载源拉取安装包: %s", url)
            yield f"data: {json.dumps({'type': 'start', 'url': url, 'message': '正在建立加速通道…'}, ensure_ascii=False)}\n\n"

            async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}")

                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    t_last = time.time()
                    bytes_last = 0
                    speed_mb = 0.0

                    with open(installer_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=128 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)

                            now = time.time()
                            if now - t_last >= 0.25:
                                dt = now - t_last
                                speed_mb = round(((downloaded - bytes_last) / dt) / (1024 * 1024), 2)
                                t_last = now
                                bytes_last = downloaded
                                pct = round((downloaded / total) * 100) if total > 0 else None
                                yield f"data: {json.dumps({'type': 'progress', 'downloaded': downloaded, 'total': total, 'percent': pct, 'speed_mb': speed_mb}, ensure_ascii=False)}\n\n"

            if installer_path.exists() and installer_path.stat().st_size > 10 * 1024 * 1024:
                success = True
                break
            else:
                last_error = "下载文件不完整，正在切换备用节点重试…"
                logger.warning(last_error)
        except Exception as e:
            last_error = str(e)
            logger.warning("下载源 %s 失败: %s，正在切换下一个加速源…", url, e)
            yield f"data: {json.dumps({'type': 'retry', 'message': '当前线路响应较慢，正在切换下一个加速源…'}, ensure_ascii=False)}\n\n"

    if not success:
        yield f"data: {json.dumps({'type': 'error', 'detail': f'安装包下载失败：{last_error}'}, ensure_ascii=False)}\n\n"
        return

    # 下载成功：推送准备安装事件
    yield f"data: {json.dumps({'type': 'ready', 'percent': 100, 'message': '下载完成，正在静默安装并自动重启应用…'}, ensure_ascii=False)}\n\n"

    # 触发静默安装
    try:
        _trigger_silent_installer(installer_path)
        yield f"data: {json.dumps({'type': 'installing', 'message': '安装程序已接管，即将重启应用'}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.exception("启动静默安装程序异常: %s", e)
        yield f"data: {json.dumps({'type': 'error', 'detail': f'启动安装程序失败：{e}'}, ensure_ascii=False)}\n\n"
