"""run_workbuddy_task 真机手动验证：真实 codebuddy CLI + 真实任务跑通全链。

用法：backend/.venv/Scripts/python.exe scripts/workbuddy_real_try.py "任务提示词" [model] [timeout_seconds]
- APP_DATA_DIR 隔离到 backend/.smoke-data/real-e2e，任务目录随跑随清
- 前提：本机已安装 codebuddy 且完成一次登录
"""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE_DATA = ROOT / "backend" / ".smoke-data" / "real-e2e"

os.environ["APP_DATA_DIR"] = str(SMOKE_DATA)
sys.path.insert(0, str(ROOT / "backend"))

from app.services.agent_tools.registry import execute_tool  # noqa: E402


async def main() -> int:
    # 经 cmd 中转时 argv 引号会被切碎，优先用环境变量传参
    prompt = os.environ.get("WB_TRY_PROMPT") or (sys.argv[1] if len(sys.argv) > 1 else "请只回复两个字：收到")
    model = os.environ.get("WB_TRY_MODEL") or (sys.argv[2] if len(sys.argv) > 2 else "")
    timeout = os.environ.get("WB_TRY_TIMEOUT") or (sys.argv[3] if len(sys.argv) > 3 else "")

    args: dict = {"prompt": prompt}
    if model:
        args["model"] = model
    if timeout:
        args["timeout_seconds"] = int(timeout)

    r = await execute_tool("run_workbuddy_task", args)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("status") == "success" else 1


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        shutil.rmtree(SMOKE_DATA, ignore_errors=True)
    sys.exit(code)
