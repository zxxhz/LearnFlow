"""WorkBuddy（codebuddy CLI）集成端点：供设置页「WorkBuddy 集成」卡片使用。

status 做 CLI 安装/版本探测（--version 秒级返回，不触发模型调用）；登录态无法
廉价探测（凭据存于系统凭据库，无本地明文文件），由 /test 真实小任务权威验证
——走与助教完全相同的 run_workbuddy_task 工具链路，约 5~30s。
"""
import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.services.workbuddy import get_config, resolve_cli, set_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workbuddy", tags=["workbuddy"])

MODEL_PATTERN = re.compile(r"[\w.\-]+")
# 与 CLI --help 的模型清单对齐（codebuddy v2.184.0）；前端下拉预设
MODEL_PRESETS = [
    "hy4flash",
    "hy4flash-free",
    "hy4std",
    "glm-5.3",
    "glm-5.3-flash",
    "glm-5.2",
    "deepseek-v4.1-flash",
    "deepseek-v4-pro",
    "kimi-k3.1-pro",
    "minimax-m3.1-flash",
    "space-bunny",
    "step-5-preview",
    "mimo-v2.6-pro",
]

INSTALL_HINT = (
    "npm install -g @tencent-ai/codebuddy-code 安装 CLI，"
    "然后在终端运行 codebuddy 进入交互界面输入 /login 登录一次（与 WorkBuddy 桌面端同账号）"
)


async def _cli_version(cli: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            cli,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        text = out.decode("utf-8", "replace").strip()
        return text.splitlines()[0][:40] if text else None
    except Exception as exc:  # 找得到文件但跑不起来（坏安装/被杀软拦截）也如实上报
        logger.warning("WorkBuddy --version 探测失败：%s", exc)
        return None


@router.get("/status")
async def workbuddy_status() -> dict:
    cfg = await get_config()
    cli = resolve_cli(cfg["cmd"])
    installed = cli is not None
    version = await _cli_version(cli) if installed else None
    cmd_source = (
        "db"
        if cfg["cmd"]
        else ("env" if settings.workbuddy_cmd.strip().lower() not in ("", "codebuddy") else "default")
    )
    return {
        "installed": installed,
        "version": version,
        "cmd": cfg["cmd"],
        "cmd_effective": cli or "",
        "cmd_source": cmd_source,
        "model": cfg["model"],
        "model_presets": MODEL_PRESETS,
        "install_hint": INSTALL_HINT,
    }


class WorkBuddyConfigUpdate(BaseModel):
    cmd: str | None = None
    model: str | None = None


@router.put("/config")
async def update_workbuddy_config(payload: WorkBuddyConfigUpdate) -> dict:
    if payload.model and not MODEL_PATTERN.fullmatch(payload.model.strip()):
        raise HTTPException(status_code=422, detail=f"非法模型 ID：{payload.model}")
    # cmd 不做存在性强校验：允许先存后装，status/test 会如实反映可用性
    cfg = await set_config(cmd=payload.cmd, model=payload.model)
    return {"saved": True, "cmd": cfg["cmd"], "model": cfg["model"]}


@router.post("/test")
async def test_workbuddy() -> dict:
    """真实小任务权威验证：复用助教的 run_workbuddy_task 全链路（含登录态判定）。"""
    from app.services.agent_tools.registry import execute_tool

    result = await execute_tool(
        "run_workbuddy_task",
        {"prompt": "请只回复：OK", "timeout_seconds": 120},
    )
    return result
