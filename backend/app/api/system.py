"""系统 API：备份/恢复 + 局域网访问信息（平板场景）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.services import system as system_service

router = APIRouter(prefix="/system", tags=["system"])


class AccessInfoOut(BaseModel):
    host: str
    port: int
    lan_mode: bool
    lan_enabled: bool
    lan_urls: list[str]
    token: str
    lan_urls_with_token: list[str]


@router.get("/access-info", response_model=AccessInfoOut)
async def access_info():
    lan_enabled = system_service.is_lan_access_enabled()
    lan_mode = (settings.host == "0.0.0.0") and lan_enabled
    token = system_service.get_access_token() if lan_mode else ""
    urls = system_service.lan_urls() if lan_mode else []
    return AccessInfoOut(
        host=settings.host,
        port=settings.port,
        lan_mode=lan_mode,
        lan_enabled=lan_enabled,
        lan_urls=urls,
        token=token,
        lan_urls_with_token=[f"{u}/?token={token}" for u in urls],
    )


@router.post("/lan-access", response_model=AccessInfoOut)
async def set_lan_access(enabled: bool):
    system_service.set_lan_access_enabled(enabled)
    return await access_info()


@router.post("/access-token/rotate", response_model=AccessInfoOut)
async def rotate_token():
    if not system_service.is_lan_access_enabled():
        raise HTTPException(status_code=400, detail="当前未开启局域网模式")
    system_service.rotate_access_token()
    return await access_info()


@router.post("/backup")
async def create_backup():
    try:
        p = system_service.create_backup()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"备份失败：{e}") from e
    return {"name": p.name, "size": p.stat().st_size}


@router.get("/backups")
async def list_backups():
    return system_service.list_backups()


@router.post("/backups/{name}/restore")
async def restore(name: str):
    try:
        system_service.request_restore(name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True, "message": "已标记恢复，重启应用后生效"}


@router.delete("/backups/{name}")
async def remove_backup(name: str):
    system_service.delete_backup(name)
    return {"ok": True}


class OpenUrlIn(BaseModel):
    url: str


@router.post("/open-url")
async def open_url(payload: OpenUrlIn):
    """在操作系统默认浏览器中打开指定链接（仅允许 http/https 协议）。"""
    url = payload.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="仅允许打开 http/https 链接")
    import webbrowser

    try:
        webbrowser.open(url)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"打开浏览器失败：{e}") from e

