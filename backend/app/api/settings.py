import json
import logging
import os
import subprocess
import sys
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import AppSetting
from app.models.base import utcnow_iso
from app.schemas.settings import (
    LLMConfig,
    LLMTestResult,
    Preferences,
    ScenesConfig,
    SettingsOut,
    SettingsUpdate,
)
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

DEFAULT_LLM = {"base_url": "", "api_key": "", "model": "", "scenes": {}}
DEFAULT_PREFS = {
    "chapter_length": 3000,
    "exercises_per_kp": 3,
    "highlight_colors": {
        "yellow": "#fde68a",
        "green": "#bbf7d0",
        "blue": "#bfdbfe",
        "pink": "#fbcfe8",
    },
    "adhd_mode": "off",
    "course_font_size": 16,
    "drill_font_size": 15,
}



async def _load_row(db: AsyncSession) -> AppSetting:
    row = await db.get(AppSetting, "local")
    if row is None:
        row = AppSetting(id="local", llm=json.dumps(DEFAULT_LLM), preferences=json.dumps(DEFAULT_PREFS))
        db.add(row)
        await db.commit()
    return row


def _load_llm_json(row: AppSetting) -> dict:
    """解析库里的 LLM 配置：历史版本/异常进程可能写坏 JSON（截断、非法字符）。

    损坏时回落默认配置并记 warning（对齐 openai_compat 的自愈策略）——
    GET 正常呈现，PUT 成功后即用合法 JSON 覆盖，完成自愈。
    """
    try:
        data = json.loads(row.llm)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("本地设置 llm 字段损坏（%s），已回落默认配置", e)
        return dict(DEFAULT_LLM)
    return data if isinstance(data, dict) else dict(DEFAULT_LLM)


def _masked_out(row: AppSetting) -> SettingsOut:
    llm_data = _load_llm_json(row)
    llm = LLMConfig(**{k: v for k, v in llm_data.items() if k in LLMConfig.model_fields})
    scenes = ScenesConfig(**(llm_data.get("scenes") or {}))
    prefs = Preferences(**json.loads(row.preferences))
    return SettingsOut.masked(llm, scenes, prefs)


def _blank_inherit(old_scene: dict, incoming: dict) -> dict:
    """场景字段留空/掩码 → 继承旧值（api_key）或保留空（其余字段由适配层回落主配置）。
    若变更了服务地址 (base_url)，禁止继承旧密钥，清空以防凭据外泄。"""
    merged = dict(incoming)
    old_key = str(old_scene.get("api_key") or "")
    new_key = str(incoming.get("api_key") or "")
    old_base = (str(old_scene.get("base_url") or "")).rstrip("/")
    new_base = (str(incoming.get("base_url") or "")).rstrip("/")
    if old_base and new_base and old_base != new_base and (not new_key or "****" in new_key):
        merged["api_key"] = ""
    elif not new_key or "****" in new_key:
        merged["api_key"] = old_key
    return merged


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    return _masked_out(await _load_row(db))


@router.put("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = await _load_row(db)
    current = _load_llm_json(row)
    if body.llm is not None:
        incoming = body.llm.model_dump()
        old_base = (str(current.get("base_url") or "")).rstrip("/")
        new_base = (str(incoming.get("base_url") or "")).rstrip("/")
        new_key = incoming.get("api_key") or ""
        # Base URL 变更时禁止静默继承旧密钥，防止攻击者通过篡改 Base URL 窃取旧服务商密钥
        if old_base and new_base and old_base != new_base and (not new_key or "****" in new_key):
            raise HTTPException(
                status_code=400,
                detail="更换服务地址 (Base URL) 时必须重新输入对应的 API Key，不支持继承原服务商密钥",
            )
        # api_key 传空或掩码 → 保留库里旧值（PRD §5.7）
        if not new_key or "****" in new_key:
            incoming["api_key"] = current.get("api_key", "")
        current.update({k: v for k, v in incoming.items() if v is not None})
        current.pop("temperature", None)  # 兼容：清掉移除温度参数前老库存量的键
    if body.scenes is not None:
        scenes_new = body.scenes.model_dump()
        scenes_old = current.get("scenes") or {}
        current["scenes"] = {
            name: _blank_inherit(scenes_old.get(name) or {}, scenes_new.get(name) or {})
            for name in ("generation", "chat", "task")
        }
    if body.preferences is not None:
        row.preferences = json.dumps(body.preferences.model_dump())
    row.llm = json.dumps(current)
    row.updated_at = utcnow_iso()
    await db.commit()
    return _masked_out(row)


@router.post("/settings/llm/test", response_model=LLMTestResult)
async def test_llm(db: AsyncSession = Depends(get_db)):
    t0 = time.perf_counter()
    try:
        # 测试连接用 15s 短超时：不可达的 base_url 不该把"测试"按钮卡住几分钟
        adapter = await create_adapter_from_settings(db, request_timeout=15.0)
        reply = await adapter.chat(
            [{"role": "user", "content": "请只回复两个字母：OK"}]
        )
        latency = int((time.perf_counter() - t0) * 1000)
        return LLMTestResult(ok=True, model_reply=str(reply)[:100], latency_ms=latency)
    except LLMError as e:
        return LLMTestResult(ok=False, error=e.message, latency_ms=int((time.perf_counter() - t0) * 1000))
    except Exception as e:  # 兜底：测试接口不抛 5xx
        logger.warning("LLM test failed: %r", e)
        return LLMTestResult(ok=False, error="测试失败，请检查配置与网络。")


@router.post("/settings/open-data-dir")
async def open_data_dir():
    from app.core.config import settings as app_settings

    path = str(app_settings.data_dir)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True}
    except Exception as e:
        logger.warning("open data dir failed: %r", e)
        return {"ok": False}


@router.post("/settings/open-downloads-dir")
async def open_downloads_dir():
    """打开系统「下载」目录：Windows 优先读已知文件夹注册表（用户移动过下载位置也准）。"""
    from pathlib import Path

    downloads: Path | None = None
    if sys.platform == "win32":
        try:
            import winreg

            # 已知文件夹 GUID：{374DE290-123F-4565-9164-39C4925E467B} = Downloads
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                raw, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                candidate = Path(winreg.ExpandEnvironmentStrings(str(raw)))
                if candidate.is_dir():
                    downloads = candidate
        except Exception as e:
            logger.debug("read downloads known folder failed: %r", e)
    if downloads is None:
        downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home()
    path = str(downloads)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True, "path": path}
    except Exception as e:
        logger.warning("open downloads dir failed: %r", e)
        return {"ok": False, "error": str(e)}


@router.get("/version")
async def version():
    from app.core.config import APP_VERSION

    return {"version": APP_VERSION}


@router.post("/update/check")
async def update_check(force: bool = False, db: AsyncSession = Depends(get_db)):
    """检查新版本（PRD 实现备注 15）。打开应用时前端自动触发（节流 1h），设置页可强制。"""
    from app.services.update import check_update

    return await check_update(db, force=force)


@router.get("/llm/ollama/models")
async def ollama_models():
    """探测本机 Ollama 的已装模型（OpenAI 兼容端点，API Key 随便填非空即可）。"""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            r = await client.get("http://localhost:11434/api/tags")
            r.raise_for_status()
            models = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="未检测到本机 Ollama（http://localhost:11434）。请确认已安装并运行 `ollama serve`。") from None
    return {"models": models}


class MirrorSelectBody(BaseModel):
    mode: str = "auto"
    selected_id: str = "auto"


class CustomMirrorCreateBody(BaseModel):
    name: str
    prefix: str
    desc: str = ""


@router.get("/settings/mirrors")
async def get_mirrors():
    """获取当前所有下载源信息及测速状态。"""
    from app.services.download_mirrors import get_mirrors_status

    return get_mirrors_status()


@router.post("/settings/mirrors/test")
async def test_mirrors():
    """并发对所有下载源（GitHub 官方与各大镜像）进行测速并自动选出最快源。"""
    from app.services.download_mirrors import run_speed_test

    return await run_speed_test()


@router.post("/settings/mirrors/select")
async def select_mirror(body: MirrorSelectBody):
    """设置下载源选择模式与指定源（auto 自动最快或 manual 手动指定）。"""
    from app.services.download_mirrors import set_mirror_selection

    try:
        return set_mirror_selection(body.mode, body.selected_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/settings/mirrors/custom")
async def create_custom_mirror(body: CustomMirrorCreateBody):
    """添加用户自定义镜像源。"""
    from app.services.download_mirrors import add_custom_mirror

    try:
        return add_custom_mirror(body.name, body.prefix, body.desc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/settings/mirrors/custom/{mirror_id}")
async def update_custom_mirror_api(mirror_id: str, body: CustomMirrorCreateBody):
    """修改指定的自定义镜像源。"""
    from app.services.download_mirrors import update_custom_mirror

    try:
        return update_custom_mirror(mirror_id, body.name, body.prefix, body.desc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/settings/mirrors/custom/{mirror_id}")
async def delete_custom_mirror(mirror_id: str):
    """删除指定的自定义镜像源。"""
    from app.services.download_mirrors import remove_custom_mirror

    try:
        return remove_custom_mirror(mirror_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/update/fast-latest.json")
async def fast_latest_json():
    """返回动态注入了最快下载源直链的 latest.json，供 Tauri Updater 极速下载。

    GitHub 直连被墙时本接口也要能用（镜像存在的意义），因此 manifest 本身
    也按测速优先级依次尝试各镜像前缀，全部失败才重定向官方源。
    """
    import httpx
    from fastapi.responses import JSONResponse, RedirectResponse

    from app.core.config import settings as app_settings
    from app.services.download_mirrors import apply_mirror, get_ordered_mirror_prefixes

    repo = (app_settings.github_repo or "zxxhz/LearnFlow").strip("/")
    raw = f"https://github.com/{repo}/releases/latest/download/latest.json"
    headers = {"User-Agent": "LearnFlow-Updater/1.0"}
    candidates = [raw]
    for prefix in get_ordered_mirror_prefixes():
        u = f"{prefix}{raw}" if prefix else raw
        if u not in candidates:
            candidates.append(u)

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        for url in candidates:
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                platforms = data.get("platforms", {})
                for plat_info in platforms.values():
                    if isinstance(plat_info, dict) and "url" in plat_info:
                        plat_info["url"] = apply_mirror(plat_info["url"])
                return JSONResponse(content=data)
            except Exception as e:
                logger.warning("获取 fast-latest.json 失败(%s): %s", url, e)
                continue
    return RedirectResponse(raw)


@router.post("/update/in-app-install")
async def in_app_install(request: Request, target_version: str, url: str | None = None):
    """在软件内流式下载官方最新安装包并自动静默重启安装（SSE 事件流）。

    改为 POST 且强制同源：本端点会下载并执行安装包（重副作用），
    必须排除被浏览器跨站请求（CSRF）或误触 GET 触发的可能。
    """
    from urllib.parse import urlparse

    from fastapi.responses import StreamingResponse
    from app.services.update import stream_download_and_install

    def _hostport(value: str, default_port: int) -> tuple[str, int] | None:
        """host[:port]（含 IPv6 [::1]:8420 形式）规整为 (host, port)。"""
        v = (value or "").strip()
        if not v:
            return None
        if v.startswith("["):  # IPv6
            host, _, rest = v[1:].partition("]")
            if not rest.startswith(":"):
                return host.lower(), default_port
            try:
                return host.lower(), int(rest[1:])
            except ValueError:
                return None
        if ":" in v:
            host, _, port_s = v.rpartition(":")
            try:
                return host.lower(), int(port_s)
            except ValueError:
                return None
        return v.lower(), default_port

    # 同源校验：Origin 带 host:port 时必须与请求的 Host 一致；
    # Sec-Fetch-Site（现代浏览器自动附带）只放行 same-origin / none
    origin = request.headers.get("origin", "").strip()
    if origin:
        op = urlparse(origin)
        oh = _hostport(op.netloc, 443 if op.scheme == "https" else 80) if op.hostname else None
        rh = _hostport(request.headers.get("host", ""), 80)
        if oh is None or oh != rh:
            raise HTTPException(status_code=403, detail="跨源请求已拒绝（仅接受应用自身页面发起的更新）")
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site and fetch_site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="跨站请求已拒绝（仅接受应用自身页面发起的更新）")

    return StreamingResponse(
        stream_download_and_install(target_version, url),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
