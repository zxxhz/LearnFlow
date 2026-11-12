"""系统 API：备份/恢复 + 局域网访问信息（平板场景）。"""
import os
import sys
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
    # v0.5.8 体检 P2：lan_mode 改为纯标志驱动（报告用户设置本身）。绑定面已收窄为
    # 「启动时按标志决定」——开启开关后需重启应用才真正监听 0.0.0.0，此端口径依旧自洽
    lan_mode = lan_enabled
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
    try:
        system_service.rotate_access_token()
    except RuntimeError as e:  # 令牌写入失败等带用户文案的运行时错误直接透传
        raise HTTPException(status_code=500, detail=str(e))
    return await access_info()


@router.post("/backup")
async def create_backup():
    import asyncio

    try:
        # zip + WAL checkpoint 是重阻塞 IO，放线程池避免冻结事件循环（SSE/心跳全部卡住）
        p = await asyncio.to_thread(system_service.create_backup)
    except Exception as e:  # noqa: BLE001
        logger.exception("创建备份失败")
        # 不透传内部异常细节（可能含路径等），给用户可行动的提示即可
        raise HTTPException(status_code=500, detail="备份失败：请检查磁盘剩余空间与数据目录写入权限") from e
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


import logging

logger = logging.getLogger(__name__)


class OpenUrlIn(BaseModel):
    url: str


@router.post("/open-url")
async def open_url(payload: OpenUrlIn):
    """在操作系统默认浏览器中打开指定链接（仅允许 http/https 协议）。"""
    url = payload.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="仅允许打开 http/https 链接")
    if os.environ.get("APP_SMOKE_TEST") == "1":
        return {"ok": True}
    import webbrowser

    # Windows 用 ShellExecute（os.startfile）：直接把 URL 交给系统默认浏览器，
    # 严禁经 cmd.exe /c start —— URL 里的 & 等元字符会被 cmd 当作命令拼接（命令注入）
    if sys.platform == "win32":
        try:
            os.startfile(url)  # noqa: S606
            return {"ok": True}
        except Exception as e:
            logger.warning("startfile 打开链接失败: %s", e)

    try:
        ok = webbrowser.open(url)
        return {"ok": bool(ok)}
    except Exception as e:  # noqa: BLE001
        logger.exception("打开浏览器失败: %s", url)
        raise HTTPException(status_code=500, detail="打开浏览器失败，请手动复制链接到浏览器打开") from e

