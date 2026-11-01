"""更新检查（PRD 实现备注 15）：查询 GitHub Releases 最新版并与 APP_VERSION 比较。

- 仓库来源：环境变量 APP_GITHUB_REPO → 内置默认 zxxhz/LearnFlow（无需配置）
- 非阻塞：短超时（5s），任何失败都优雅降级为不可用，绝不影响应用启动与使用
- 节流：自动检查（打开应用时前端触发）1 小时内不重复请求；设置页按钮可强制刷新
- 跨版本日志聚合：若当前版本为 0.0.1，最新版本为 0.0.4，将聚合中间所有已发布版本的更新说明，跳过无日志或不存在的版本
"""
import asyncio
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

# in-app-install 安装包下载硬上限：单包体积 600MB（超限弃源）、全部源合计 20 分钟
_INSTALLER_MAX_BYTES = 600 * 1024 * 1024
_DOWNLOAD_TOTAL_TIMEOUT = 20 * 60

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
            valid_releases = [
                r for r in releases
                if not r.get("draft") and not r.get("prerelease") and r.get("tag_name")
            ]
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



def _find_parent_desktop_pid() -> int | None:
    """取父进程 PID（仅当其映像名为 LearnFlow.exe，即打包版桌面壳）。

    更新链必须先杀壳再杀后端：壳的 watchdog 检测到后端失联后会用旧安装目录
    重拉后端，与安装器写文件互踩。按 PID /T 终止比按映像名（/IM 会杀掉所有
    同名实例）保守；父进程不可得或映像名不符（开发模式父进程是终端/IDE）时
    返回 None，由调用方退回映像名兜底。
    """
    import ctypes
    import os
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]

    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return None
    try:
        me = os.getpid()
        parent_pid = None
        names: dict[int, str] = {}
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(pe)
        ok = bool(k32.Process32FirstW(snap, ctypes.byref(pe)))
        while ok:
            names[int(pe.th32ProcessID)] = str(pe.szExeFile)
            if int(pe.th32ProcessID) == me:
                parent_pid = int(pe.th32ParentProcessID)
            pe.dwSize = ctypes.sizeof(pe)
            ok = bool(k32.Process32NextW(snap, ctypes.byref(pe)))
    finally:
        k32.CloseHandle(snap)
    if parent_pid and names.get(parent_pid, "").lower() == "learnflow.exe":
        return parent_pid
    return None


def _kill_update_targets() -> None:
    """终止旧版进程（桌面壳 + 后端），释放安装目录文件锁。

    - 桌面壳：backend 由壳 spawn，父进程映像名 = LearnFlow.exe 时按父 PID /T
      （整树，连带 WebView 子进程）终止；否则退回映像名兜底。
      learnflow-desktop.exe 为已废弃旧名，不再处理。
    - 后端：按自身 PID /T 终止（连带编译器/沙箱子进程）；taskkill 不会终止
      自身所在的调用链之外的进程，且打包版该 PID 即 learnflow-backend.exe。

    所有 taskkill 带超时且吞异常：退出路径绝不能被外部命令挂起卡死。
    """
    import os
    import subprocess

    def _run(cmd, **kw) -> None:
        try:
            subprocess.run(cmd, capture_output=True, timeout=10, **kw)
        except Exception:  # noqa: BLE001  含 TimeoutExpired/FileNotFoundError
            pass

    desktop_pid = _find_parent_desktop_pid()
    if desktop_pid:
        _run(["taskkill", "/F", "/T", "/PID", str(desktop_pid)])
    else:
        _run("taskkill /F /IM LearnFlow.exe >nul 2>&1", shell=True)
    _run(["taskkill", "/F", "/T", "/PID", str(os.getpid())])


def _launch_installer_and_exit(installer_path: "Path") -> None:
    """唤起已下载的最新安装包界面并平稳退出当前旧版本进程，彻底释放文件锁。

    两次唤起都失败时抛出异常：绝不能在没启动安装包的情况下自杀退出旧版本——
    那会让用户既没更新成功、应用也没了。
    """
    import os
    import socket
    import subprocess
    import sys
    import threading
    import time
    from pathlib import Path

    installer_str = str(installer_path.resolve())
    logger.info("准备唤起新版本安装程序: %s", installer_str)

    # 1. 使用 Windows 系统外壳独立打开安装包（脱离当前进程树，兼容 UAC 提权）；
    #    两次尝试都抛异常时直接向上传播，绝不安排退出
    try:
        os.startfile(installer_str)
    except Exception as e:
        logger.warning("os.startfile 唤起失败，尝试调用 explorer.exe: %s", e)
        subprocess.Popen(["explorer.exe", installer_str])

    # 2. 主动确认旧版本已停止服务后终止，而非盲等固定秒数
    def _delayed_exit():
        import subprocess
        import sys

        # 生成管线在跑则等它收尾（最多 30s）：硬杀会截断半生成的章节与 DB 事务
        try:
            from app.services.generation import pipeline as _pipeline

            for _ in range(30):
                if not _pipeline.any_running():
                    break
                time.sleep(1)
        except Exception:  # noqa: BLE001
            pass

        if sys.platform == "win32":
            try:
                _kill_update_targets()
                # 主动确认后端健康检查消失（最多 10s），而非固定 sleep。
                # 打包版上一步 taskkill /T 已把本进程带走，轮询随进程消亡（属预期）；
                # 存活到这里说明后端不在壳进程树下（如开发模式），等它真正失联，
                # 超时照旧强杀兜底
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", app_settings.port), timeout=0.5):
                            time.sleep(0.3)  # 端口仍可连 = 后端还在服务，继续等
                    except OSError:
                        break  # 健康检查消失：后端确已停止
                for _cmd in (
                    "taskkill /F /IM LearnFlow.exe >nul 2>&1",
                    "taskkill /F /IM learnflow-backend.exe >nul 2>&1",
                ):
                    try:
                        subprocess.run(_cmd, shell=True, timeout=10)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                # 清理链路任何一步出问题都不能阻止退出（否则旧版残留锁死安装目录）
                logger.exception("旧版本退出清理失败，仍将强制退出")
        # sys.exit 在非主线程只结束本线程（开发模式后端会存活锁文件），必须硬退出进程
        os._exit(0)

    t = threading.Thread(target=_delayed_exit, daemon=True)
    t.start()
    logger.info("已启动安装向导并安排旧进程退出: %s", installer_str)


def _allowed_download_hosts() -> set[str]:
    """下载源域名白名单：仅官方 GitHub 域。

    该接口执行下载并唤起安装包，direct_url 不做白名单校验就是任意下载执行链
    （回环免令牌 + GET，浏览器任意页面均可触发）。镜像域不再参与安装包下载
    ——完整性锚点是 GitHub API 官方 digest，镜像路径可能被整体替换。
    """
    return {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "codeload.github.com",
    }


def _sanitize_version(version: str) -> str:
    """版本号只允许数字与点（防止拼进落盘文件名的路径穿越）。"""
    import re

    v = (version or "").strip().lstrip("vV")
    if not re.fullmatch(r"\d+(\.\d+)*", v):
        raise ValueError(f"非法版本号：{version!r}")
    return v


def _canonical_exe(repo: str, clean_v: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{clean_v}/LearnFlow_{clean_v}_x64-setup.exe"


def _direct_url_allowed(candidate: str, raw_github_exe: str) -> bool:
    """direct_url 只接受 canonical 官方安装包 URL 本身。

    仅按域名白名单校验不够：github.com 域下任意仓库/路径的 exe 也会被下载执行，
    等于把"更新"变成任意下载执行链（回环免令牌，本地任意网页可触发）。
    镜像前缀变体一律不再参与安装包下载（镜像仅保留为 check_update 的
    latest.json 回退源），故只放行官方 canonical URL。
    """
    return candidate == raw_github_exe


async def _fetch_release_asset_sha256(repo: str, tag: str, filename: str) -> str | None:
    """从 GitHub API 读取该 release 资产的官方 sha256（digest 字段）。

    拿不到（API 不可达/限流/老资产无 digest）时返回 None，调用方 fail-closed
    终止安装：安装包要被下载执行，无官方 digest 可比对时绝不放行下载。
    """
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    headers = {"User-Agent": "LearnFlow-Update-Check", "Accept": "application/vnd.github+json"}
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            for asset in resp.json().get("assets", []):
                if asset.get("name") == filename:
                    digest = str(asset.get("digest") or "")
                    if digest.lower().startswith("sha256:"):
                        return digest.split(":", 1)[1].lower()
    except Exception as e:  # noqa: BLE001
        logger.info("无法获取 %s 的官方 sha256（%s），跳过完整性校验", filename, e)
    return None


async def _stream_installer(url: str, installer_path: "Path", headers: dict[str, str]):
    """单源下载安装包（流式，产出 SSE 进度事件行；异常上抛由调用方换源）。

    超限防护：content-length 超体积上限直接报错换源（不落盘）；落盘超过上限
    中断并删除半截文件。单连接卡死由 httpx 180s 超时兜底，整体时长由调用方
    的 deadline（经 asyncio.wait_for）约束。
    """
    import json

    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")

            total = int(resp.headers.get("content-length", 0))
            if total > _INSTALLER_MAX_BYTES:
                raise RuntimeError(
                    f"安装包体积超过 {_INSTALLER_MAX_BYTES // (1024 * 1024)}MB 上限"
                    f"（{total // (1024 * 1024)}MB），已跳过该源"
                )
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
                    if downloaded > _INSTALLER_MAX_BYTES:
                        raise RuntimeError(
                            f"下载超过 {_INSTALLER_MAX_BYTES // (1024 * 1024)}MB 上限，已中断并删除半截文件"
                        )

                    now = time.time()
                    if now - t_last >= 0.25:
                        dt = now - t_last
                        speed_mb = round(((downloaded - bytes_last) / dt) / (1024 * 1024), 2)
                        t_last = now
                        bytes_last = downloaded
                        pct = round((downloaded / total) * 100) if total > 0 else None
                        yield f"data: {json.dumps({'type': 'progress', 'downloaded': downloaded, 'total': total, 'percent': pct, 'speed_mb': speed_mb}, ensure_ascii=False)}\n\n"


async def stream_download_and_install(target_version: str, direct_url: str | None = None):
    """流式下载官方最新安装包，向前端实时推送进度，并在完成后以静默模式触发安装。

    完整性 fail-closed：仅当能从 GitHub API 取到官方 sha256 时才允许下载与校验；
    镜像不再参与安装包下载（仅保留为 check_update 的 latest.json 回退源）。
    """
    import hashlib
    import json
    import tempfile
    from pathlib import Path
    from urllib.parse import urlparse

    repo = _effective_repo() or "zxxhz/LearnFlow"
    try:
        clean_v = _sanitize_version(target_version)
    except ValueError as e:
        yield f"data: {json.dumps({'type': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n"
        return

    # 防降级/重装：目标版本必须高于当前版本（相等也拒绝）
    if _ver_tuple(f"v{clean_v}") <= _ver_tuple(APP_VERSION):
        detail = f"目标版本 v{clean_v} 不高于当前版本 {APP_VERSION}，已拒绝安装"
        logger.warning(detail)
        yield f"data: {json.dumps({'type': 'error', 'detail': detail}, ensure_ascii=False)}\n\n"
        return

    # 域名白名单校验：direct_url 只接受官方域
    allowed_hosts = _allowed_download_hosts()
    raw_github_exe = _canonical_exe(repo, clean_v)

    # 确定候选下载 URL 列表：仅官方 canonical 安装包 URL（direct_url 校验通过即与之相同）
    urls_to_try: list[str] = []
    if direct_url and direct_url.strip():
        candidate = direct_url.strip()
        parsed = urlparse(candidate)
        if (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and parsed.hostname.lower() in allowed_hosts
            and _direct_url_allowed(candidate, raw_github_exe)
        ):
            urls_to_try.append(candidate)
        else:
            logger.warning("拒绝白名单或路径校验外的 direct_url: %s", candidate)
    if raw_github_exe not in urls_to_try:
        urls_to_try.append(raw_github_exe)

    temp_dir = Path(tempfile.gettempdir()) / "LearnFlow_Update"
    temp_dir.mkdir(parents=True, exist_ok=True)
    # 清理历史残留的半截安装包（只清 1 小时前的旧文件，避免误删并发下载的在途文件）
    import uuid

    now_ts = time.time()
    for stale in temp_dir.glob("LearnFlow_*-setup.exe"):
        try:
            if now_ts - stale.stat().st_mtime > 3600:
                stale.unlink()
        except OSError:
            pass
    # 文件名带随机后缀：并发触发两次安装互不覆盖、互不删对方的在途文件
    installer_path = temp_dir / f"LearnFlow_{clean_v}_{uuid.uuid4().hex[:8]}_x64-setup.exe"

    # 完整性校验 fail-closed：取不到官方 sha256（API 不可达/限流/资产无 digest）
    # 时直接终止，绝不下载执行无法验证完整性的安装包
    expected_sha256 = await _fetch_release_asset_sha256(repo, f"v{clean_v}", f"LearnFlow_{clean_v}_x64-setup.exe")
    if not expected_sha256:
        detail = "无法验证安装包完整性，请稍后重试或使用应用内更新（Tauri updater）"
        logger.error("拒绝安装 v%s：%s", clean_v, detail)
        yield f"data: {json.dumps({'type': 'error', 'detail': detail}, ensure_ascii=False)}\n\n"
        return

    headers = {"User-Agent": "LearnFlow-InAppUpdater/1.0"}
    success = False
    last_error = ""
    dl_deadline = time.monotonic() + _DOWNLOAD_TOTAL_TIMEOUT

    for url in urls_to_try:
        if time.monotonic() > dl_deadline:
            last_error = "下载总时长超过 20 分钟上限，已中止"
            break
        try:
            logger.info("尝试从下载源拉取安装包: %s", url)
            yield f"data: {json.dumps({'type': 'start', 'url': url, 'message': '正在建立加速通道…'}, ensure_ascii=False)}\n\n"

            gen = _stream_installer(url, installer_path, headers)
            try:
                while True:
                    remaining = dl_deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("下载总时长超过 20 分钟上限，已中止")
                    try:
                        event = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
                    except StopAsyncIteration:
                        break
                    yield event
            finally:
                await gen.aclose()

            if installer_path.exists() and installer_path.stat().st_size > 10 * 1024 * 1024:
                h = hashlib.sha256()
                with open(installer_path, "rb") as vf:
                    for block in iter(lambda: vf.read(1024 * 1024), b""):
                        h.update(block)
                if h.hexdigest() != expected_sha256:
                    installer_path.unlink(missing_ok=True)
                    last_error = "安装包 sha256 校验失败（来源不可信），已拒绝安装"
                    logger.error(last_error)
                    yield f"data: {json.dumps({'type': 'retry', 'message': last_error}, ensure_ascii=False)}\n\n"
                    continue
                success = True
                break
            else:
                last_error = "下载文件不完整，正在切换备用节点重试…"
                logger.warning(last_error)
        except Exception as e:
            last_error = str(e)
            installer_path.unlink(missing_ok=True)  # 超限/中断的半截文件不留
            logger.warning("下载源 %s 失败: %s，正在切换下一个下载源…", url, e)
            yield f"data: {json.dumps({'type': 'retry', 'message': '当前线路响应较慢，正在切换下一个下载源…'}, ensure_ascii=False)}\n\n"

    if not success:
        yield f"data: {json.dumps({'type': 'error', 'detail': f'安装包下载失败：{last_error}'}, ensure_ascii=False)}\n\n"
        return

    # 下载成功：推送准备安装事件
    yield f"data: {json.dumps({'type': 'ready', 'percent': 100, 'message': '下载完成，正在打开新安装包…'}, ensure_ascii=False)}\n\n"

    # 唤起安装包并安排安全退出
    try:
        _launch_installer_and_exit(installer_path)
        yield f"data: {json.dumps({'type': 'installing', 'message': '新安装包已启动，旧客户端即将关闭…'}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.exception("启动安装程序异常: %s", e)
        yield f"data: {json.dumps({'type': 'error', 'detail': f'启动安装程序失败：{e}'}, ensure_ascii=False)}\n\n"
