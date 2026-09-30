import json
import logging
import os
import subprocess
import sys
import time

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import AppSetting
from app.models.base import utcnow_iso
from app.schemas.settings import (
    LLMConfig,
    LLMTestResult,
    Preferences,
    SettingsOut,
    SettingsUpdate,
)
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

DEFAULT_LLM = {"base_url": "", "api_key": "", "model": "", "temperature": 0.7}
DEFAULT_PREFS = {
    "daily_new_cards": 20,
    "chapter_length": 3000,
    "feynman_max_rounds": 4,
    "auto_create_cards": True,
}


async def _load_row(db: AsyncSession) -> AppSetting:
    row = await db.get(AppSetting, "local")
    if row is None:
        row = AppSetting(id="local", llm=json.dumps(DEFAULT_LLM), preferences=json.dumps(DEFAULT_PREFS))
        db.add(row)
        await db.commit()
    return row


def _masked_out(row: AppSetting) -> SettingsOut:
    llm = LLMConfig(**json.loads(row.llm))
    prefs = Preferences(**json.loads(row.preferences))
    return SettingsOut.masked(llm, prefs)


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    return _masked_out(await _load_row(db))


@router.put("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = await _load_row(db)
    if body.llm is not None:
        current = json.loads(row.llm)
        incoming = body.llm.model_dump()
        # api_key 传空或掩码 → 保留旧值（PRD §5.7）
        new_key = incoming.get("api_key") or ""
        if not new_key or "****" in new_key:
            incoming["api_key"] = current.get("api_key", "")
        current.update({k: v for k, v in incoming.items() if v is not None})
        row.llm = json.dumps(current)
    if body.preferences is not None:
        row.preferences = json.dumps(body.preferences.model_dump())
    row.updated_at = utcnow_iso()
    await db.commit()
    return _masked_out(row)


@router.post("/settings/llm/test", response_model=LLMTestResult)
async def test_llm(db: AsyncSession = Depends(get_db)):
    t0 = time.perf_counter()
    try:
        adapter = await create_adapter_from_settings(db)
        reply = await adapter.chat(
            [{"role": "user", "content": "请只回复两个字母：OK"}], temperature=0
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
