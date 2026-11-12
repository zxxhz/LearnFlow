"""更新检查（PRD 实现备注 15）：查询 GitHub Releases 最新版并与 APP_VERSION 比较。

- 仓库来源：环境变量 APP_GITHUB_REPO → 内置默认 zxxhz/LearnFlow（无需配置）
- 非阻塞：短超时（5s），任何失败都优雅降级为不可用，绝不影响应用启动与使用
- 节流：自动检查（打开应用时前端触发）1 小时内不重复请求；设置页按钮可强制刷新
- 跨版本日志聚合：若当前版本为 0.0.1，最新版本为 0.0.4，将聚合中间所有已发布版本的更新说明，跳过无日志或不存在的版本
"""
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import asyncio
import logging
import re
import time
from urllib.parse import urlparse

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



def _launch_installer_and_exit(installer_path: "Path") -> None:
    """唤起已下载的最新安装包界面并平稳退出当前旧版本进程，彻底释放文件锁。"""
    import os
    import subprocess
    import sys
    import threading
    import time
    from pathlib import Path

    installer_str = str(installer_path.resolve())
    logger.info("准备唤起新版本安装程序: %s", installer_str)

    # 1. 以完全脱离当前进程树的独立方式启动安装向导
    #    优先使用 os.startfile，回退 cmd /c start ""，完全交由 Windows Shell 独立运行，
    #    绝不作为后端的子进程，避免旧版本退出或 taskkill 时误伤安装程序
    started = False
    try:
        os.startfile(installer_str)
        started = True
    except Exception as e:
        logger.warning("os.startfile 唤起失败，尝试调用 cmd start: %s", e)

    if not started:
        try:
            # cmd /c start "" 启动的程序属于全新会话组，脱离当前进程树；
            # 列表形式参数不经 shell 二次解析（防注入）：文件名由 _sanitize_version
            # （仅数字与点）+ uuid 构造，不含空格与 cmd 元字符，外部不可控
            subprocess.Popen(["cmd", "/c", "start", "", installer_str])
            started = True
        except Exception as e:
            logger.warning("cmd start 唤起失败，尝试调用 explorer: %s", e)
            subprocess.Popen(["explorer.exe", installer_str])
            started = True

    # 2. 延迟 2.5 秒后安全关闭旧版本进程，给安装向导留出充分的启动与 UAC 窗口初始化时间
    def _delayed_exit():
        # 等待进行中的生成管线（最多 10s）
        try:
            from app.services.generation import pipeline as _pipeline

            for _ in range(10):
                if not _pipeline.any_running():
                    break
                time.sleep(1)
        except Exception:  # noqa: BLE001
            pass

        # 留足 2.5 秒缓冲时间，确保安装向导窗口已稳定弹出显示给用户
        time.sleep(2.5)

        if sys.platform == "win32":
            try:
                # 仅针对旧版桌面壳与后端映像名做非递归清理（严禁带 /T，防止误伤刚启动的安装包向导）；
                # 带 timeout：退出路径绝不能被外部命令挂起卡死
                subprocess.run("taskkill /F /IM LearnFlow.exe >nul 2>&1", shell=True, timeout=10)
                subprocess.run("taskkill /F /IM learnflow-backend.exe >nul 2>&1", shell=True, timeout=10)
            except Exception:  # noqa: BLE001
                logger.exception("旧版本退出清理异常")

        # 彻底退出当前后端进程，释放安装目录下的全部文件占用
        os._exit(0)

    t = threading.Thread(target=_delayed_exit, daemon=True)
    t.start()
    logger.info("已启动安装向导并安排旧进程退出: %s", installer_str)


def _allowed_download_hosts() -> set[str]:
    """下载源域名白名单：官方 GitHub 域 + 已配置合法镜像源的域。"""
    hosts = {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "codeload.github.com",
    }
    for prefix in get_ordered_mirror_prefixes():
        try:
            host = urlparse(prefix if "://" in prefix else f"https://{prefix}").hostname
            if host:
                hosts.add(host.lower())
        except Exception:  # noqa: BLE001
            continue
    return hosts


def _sanitize_version(version: str) -> str:
    """版本号只允许 ASCII 数字与点（防止拼进落盘文件名的路径穿越）。

    v0.5.8 体检 P2：\\d 默认匹配 Unicode 数字（全角 １.２.３ 可通过校验流入
    GitHub URL 与安装包文件名），显式用 [0-9] 收紧。
    """
    import re

    v = (version or "").strip().lstrip("vV")
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)*", v):
        raise ValueError(f"非法版本号：{version!r}")
    return v


def _canonical_exe(repo: str, clean_v: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{clean_v}/LearnFlow_{clean_v}_x64-setup.exe"


def _direct_url_allowed(candidate: str, raw_github_exe: str) -> bool:
    """direct_url 只接受 canonical 官方安装包 URL 本身或其合法镜像前缀变体。

    仅放行指向 LearnFlow 对应版本的官方安装包路径，杜绝指向任意未授权 URL。
    """
    if candidate == raw_github_exe:
        return True
    for prefix in get_ordered_mirror_prefixes():
        if prefix and candidate == f"{prefix}{raw_github_exe}":
            return True
    return candidate == apply_mirror(raw_github_exe)


async def _fetch_release_asset_sha256(repo: str, tag: str, filename: str) -> str | None:
    """获取官方安装包 SHA-256：优先 GitHub API digest，备选官方 latest.json 中的 sha256 字段。

    安全红线：sha256 只从官方域（api.github.com / github.com）获取，**绝不从镜像取**——
    镜像同时供给锚点与安装包即自洽通过，等价于无校验（完整性锚点必须与被校验对象无共同信任源）。
    拿不到官方 sha256 时由调用方降级为仅官方直连下载源（镜像不参与该次更新）。
    """
    headers = {"User-Agent": "LearnFlow-Update-Check", "Accept": "application/vnd.github+json"}

    # 1. 尝试从 GitHub API 读取
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
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
        logger.info("GitHub API 未直接返回 sha256（%s），尝试从官方 latest.json 获取...", e)

    # 2. 备选：仅官方 latest.json（镜像路径一律不信——镜像可能整体替换内容）
    candidates = [
        f"https://github.com/{repo}/releases/download/{tag}/latest.json",
        f"https://raw.githubusercontent.com/{repo}/{tag}/latest.json",
    ]
    for c_url in candidates:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(c_url, headers=headers)
                r.raise_for_status()
                data = r.json()
                sha = data.get("platforms", {}).get("windows-x86_64", {}).get("sha256")
                if sha and isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha.strip()):
                    return sha.strip().lower()
        except Exception:  # noqa: BLE001
            continue

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

    完整性 fail-closed（真实现）：仅当能从 GitHub API 取到官方 sha256 时才允许下载；
    下载完成后强比对，取不到官方 sha256 时直接拒绝安装并引导手动下载。
    镜像可参与安装包下载以提升可达性，但 SHA-256 强比对是唯一完整性锚点，
    镜像与官方源不共享任何信任根；latest.json 回退链仅限官方域。
    """
    import hashlib
    import json
    import tempfile
    from pathlib import Path

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

    # 确定候选下载 URL 列表（首选用已加速链接或当前最优镜像，随后按测速优先级排序）
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

    active_accelerated = apply_mirror(raw_github_exe)
    if active_accelerated not in urls_to_try:
        urls_to_try.append(active_accelerated)

    for prefix in get_ordered_mirror_prefixes():
        p_url = f"{prefix}{raw_github_exe}" if prefix else raw_github_exe
        if p_url not in urls_to_try:
            urls_to_try.append(p_url)

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

    # 完整性校验（真 fail-closed）：仅当能从 GitHub API 取到官方 sha256 时才允许下载安装。
    # 拿不到官方摘要时绝不静默降级为「无校验直装」——那条路径在 TLS 被解代理劫持时
    # 会同时骗过 api 与下载源，构成供应链风险（v0.5.1 体检 P1）；此时引导手动下载核验。
    expected_sha256 = await _fetch_release_asset_sha256(repo, f"v{clean_v}", f"LearnFlow_{clean_v}_x64-setup.exe")
    if not expected_sha256:
        detail = (
            f"无法从 GitHub API 获取 v{clean_v} 安装包的官方 SHA-256，已中止应用内更新。"
            "为防供应链篡改，未通过完整性基线的安装包不会被执行；请前往 GitHub Releases 页面手动下载并核对校验和后安装。"
        )
        logger.error("fail-closed：未获取到官方 sha256，拒绝应用内安装 v%s", clean_v)
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
                if expected_sha256:
                    h = hashlib.sha256()
                    with open(installer_path, "rb") as vf:
                        for block in iter(lambda: vf.read(1024 * 1024), b""):
                            h.update(block)
                    if h.hexdigest().lower() != expected_sha256.lower():
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
                # 半截文件必须立刻删除：留到 1 小时惰性清理会被用户误双击，
                # NSIS 解包到一半读 EOF 报"Error writing temporary file"极具迷惑性
                installer_path.unlink(missing_ok=True)
        except Exception as e:
            last_error = str(e)
            installer_path.unlink(missing_ok=True)  # 超限/中断的半截文件不留
            logger.warning("下载源 %s 失败: %s，正在切换下一个下载源…", url, e)
            yield f"data: {json.dumps({'type': 'retry', 'message': '当前线路响应较慢，正在切换下一个下载源…'}, ensure_ascii=False)}\n\n"

    if not success:
        installer_path.unlink(missing_ok=True)  # 兜底：任何失败路径都不给 Temp 留半截 exe
        yield f"data: {json.dumps({'type': 'error', 'detail': f'安装包下载失败：{last_error}'}, ensure_ascii=False)}\n\n"
        return

    # 下载成功：推送准备安装事件
    yield f"data: {json.dumps({'type': 'ready', 'percent': 100, 'message': '下载完成，正在打开新安装包…'}, ensure_ascii=False)}\n\n"

    # 唤起安装包并安排安全退出。
    # installing 事件必须在唤起**成功之后**发：若先发再唤起，唤起失败的 error 事件
    # 会被前端 settled 标志吞掉（Promise 已定格），弹窗永久卡死且旧进程也不退出
    try:
        _launch_installer_and_exit(installer_path)
        yield f"data: {json.dumps({'type': 'installing', 'message': '新安装包已启动，请按向导完成安装…'}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.exception("启动安装程序异常: %s", e)
        yield f"data: {json.dumps({'type': 'error', 'detail': f'启动安装程序失败：{e}'}, ensure_ascii=False)}\n\n"
