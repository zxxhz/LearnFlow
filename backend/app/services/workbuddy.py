"""WorkBuddy（codebuddy CLI）本机配置：持久化到 data_dir/workbuddy_config.json。

机器本地配置刻意不入 app_settings/同步链路：CLI 路径本就因机器而异，默认模型
也是本机 CLI 的属性（见设置页「WorkBuddy 集成」卡）。进程内缓存由写路径主动失效。
"""
import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# cmd 空 = 依次回落 APP_WORKBUDDY_CMD 环境覆盖 / 默认命令名 codebuddy；
# model 空 = 不传 --model，跟随 WorkBuddy 自身默认
DEFAULTS = {"cmd": "", "model": ""}

_cache: dict[str, str] | None = None
_lock = asyncio.Lock()


def _path() -> Path:
    return settings.data_dir / "workbuddy_config.json"


def _load_unlocked() -> dict[str, str]:
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg["cmd"] = str(raw.get("cmd") or "").strip()
            cfg["model"] = str(raw.get("model") or "").strip()
    except (OSError, ValueError):
        # 文件不存在/损坏时回落默认并自愈（下次写入覆盖坏内容）
        logger.warning("WorkBuddy 配置读取失败，使用默认配置：%s", _path())
    return cfg


async def get_config() -> dict[str, str]:
    """读取本机配置（进程内缓存，写路径失效）。"""
    global _cache
    if _cache is None:
        async with _lock:
            if _cache is None:
                _cache = _load_unlocked()
    return dict(_cache)


async def set_config(cmd: str | None = None, model: str | None = None) -> dict[str, str]:
    """更新本机配置并持久化；传 None 表示保持不变，空串表示清除该项。"""
    global _cache
    async with _lock:
        cfg = dict(_cache) if _cache is not None else _load_unlocked()
        if cmd is not None:
            cfg["cmd"] = cmd.strip()
        if model is not None:
            cfg["model"] = model.strip()
        try:
            _path().write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.error("WorkBuddy 配置写入失败：%s", exc)
            raise
        _cache = cfg
        return dict(cfg)


def resolve_cli(configured_cmd: str = "") -> str | None:
    """解析 CLI 路径（registry 工具与 status 端点共用）。

    显式配置（设置卡 → 配置文件 → APP_WORKBUDDY_CMD → 默认 codebuddy）：
    含路径分隔符或带后缀时按文件使用，纯命令名走 PATH 查找（Windows 下
    npm 装的是 codebuddy.cmd，which 兜底补 .cmd 后缀）。
    """
    configured = (configured_cmd or "").strip() or settings.workbuddy_cmd.strip()
    if not configured:
        return None
    if "/" in configured or "\\" in configured or Path(configured).suffix:
        candidate = Path(configured)
        return str(candidate) if candidate.is_file() else None
    return shutil.which(configured) or shutil.which(configured + ".cmd")


def kill_proc_tree(proc) -> None:
    """终止进程树。Windows 下 npm 的 .cmd 启动器会再拉起真实 node 子进程，
    proc.kill() 只杀得到壳，必须 taskkill /T 树杀才不留孤儿进程
    （registry 工具与 llm.codebuddy 适配器共用）。"""
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    else:
        with contextlib.suppress(Exception):
            proc.kill()
