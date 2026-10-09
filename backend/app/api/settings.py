import json
import logging
import os
import subprocess
import sys
import time

from fastapi import APIRouter, Depends, HTTPException
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


def _masked_out(row: AppSetting) -> SettingsOut:
    llm = LLMConfig(**{k: v for k, v in json.loads(row.llm).items() if k in LLMConfig.model_fields})
    scenes = ScenesConfig(**(json.loads(row.llm).get("scenes") or {}))
    prefs = Preferences(**json.loads(row.preferences))
    return SettingsOut.masked(llm, scenes, prefs)


def _blank_inherit(old_scene: dict, incoming: dict) -> dict:
    """场景字段留空/掩码 → 继承旧值（api_key）或保留空（其余字段由适配层回落主配置）。"""
    merged = dict(incoming)
    old_key = str(old_scene.get("api_key") or "")
    new_key = str(incoming.get("api_key") or "")
    if not new_key or "****" in new_key:
        merged["api_key"] = old_key
    return merged


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    return _masked_out(await _load_row(db))


@router.put("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = await _load_row(db)
    current = json.loads(row.llm)
    if body.llm is not None:
        incoming = body.llm.model_dump()
        # api_key 传空或掩码 → 保留库里旧值（PRD §5.7）
        new_key = incoming.get("api_key") or ""
        if not new_key or "****" in new_key:
            incoming["api_key"] = current.get("api_key", "")
        current.update({k: v for k, v in incoming.items() if v is not None})
        current.pop("temperature", None)  # 兼容：清掉移除温度参数前老库存量的键
    if body.scenes is not None:
        scenes_new = body.scenes.model_dump()
        scenes_old = current.get("scenes") or {}
        current["scenes"] = {
            name: _blank_inherit(scenes_old.get(name) or {}, scenes_new.get(name) or {})
            for name in ("generation", "chat")
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
        adapter = await create_adapter_from_settings(db)
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

    return set_mirror_selection(body.mode, body.selected_id)


@router.post("/settings/mirrors/custom")
async def create_custom_mirror(body: CustomMirrorCreateBody):
    """添加用户自定义镜像源。"""
    from app.services.download_mirrors import add_custom_mirror

    try:
        return add_custom_mirror(body.name, body.prefix, body.desc)
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
    """返回动态注入了最快下载源直链的 latest.json，供 Tauri Updater 极速下载。"""
    import httpx
    from fastapi.responses import JSONResponse, RedirectResponse

    from app.core.config import settings as app_settings
    from app.services.download_mirrors import apply_mirror

    repo = (app_settings.github_repo or "zxxhz/LearnFlow").strip("/")
    url = f"https://github.com/{repo}/releases/latest/download/latest.json"
    headers = {"User-Agent": "LearnFlow-Updater/1.0"}
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            platforms = data.get("platforms", {})
            for plat_info in platforms.values():
                if isinstance(plat_info, dict) and "url" in plat_info:
                    plat_info["url"] = apply_mirror(plat_info["url"])
            return JSONResponse(content=data)
    except Exception as e:
        logger.warning("获取 fast-latest.json 失败: %s", e)
        return RedirectResponse(url)
