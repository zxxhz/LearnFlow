"""run_workbuddy_task 冒烟：mock codebuddy 跑通 注册/成功/空参/未安装/失败/未登录/空输出/超时 八条路径。

用法（backend venv）：backend/.venv/Scripts/python.exe scripts/workbuddy_mvp_smoke.py
- 不碰真实 codebuddy CLI、不碰真实数据目录：APP_DATA_DIR 隔离到 backend/.smoke-data/
- 超时用例约 31s，总耗时 ~35s
"""
import asyncio
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SMOKE_DATA = BACKEND / ".smoke-data" / "workbuddy"

# env 必须先于 app 模块导入注入（settings 在 import 时固化）；
# APP_DATA_DIR 隔离是既有约定，绝不能落到开发数据目录 backend/data
os.environ["APP_DATA_DIR"] = str(SMOKE_DATA)
os.environ["APP_WORKBUDDY_CMD"] = str(ROOT / "scripts" / "mock_codebuddy.cmd")

sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.services.agent_tools.registry import (  # noqa: E402
    AGENT_TOOLS_SCHEMA,
    execute_tool,
)

RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))


async def main() -> int:
    names = {s["function"]["name"] for s in AGENT_TOOLS_SCHEMA}
    check(
        f"schema 注册（共 {len(names)} 个工具）",
        "run_workbuddy_task" in names,
    )

    # 1. 成功路径：stdin 传参、产出文件清单、会话 id、任务目录落盘
    r = await execute_tool("run_workbuddy_task", {"prompt": "生成一份测试讲义，包含 3 道例题"})
    check(
        "成功路径",
        r.get("status") == "success"
        and any(f["path"] == "产出.md" for f in r.get("files", []))
        and r.get("session_id") == "mock-session-1"
        and (SMOKE_DATA / "workbuddy_tasks" / r.get("task_id", "") / "产出.md").is_file(),
        f"result={str(r.get('result', ''))[:40]}",
    )

    # 2. 空参守卫
    r = await execute_tool("run_workbuddy_task", {"prompt": "   "})
    check("空 prompt 守卫", bool(r.get("error")), str(r.get("error", ""))[:40])

    # 3. 未安装 CLI：换一个不存在的命令名
    saved = settings.workbuddy_cmd
    try:
        settings.workbuddy_cmd = "definitely_not_exist_9x7y"
        r = await execute_tool("run_workbuddy_task", {"prompt": "hello"})
        check(
            "未安装守卫",
            "npm install" in str(r.get("error", "")),
            str(r.get("error", ""))[:50],
        )
    finally:
        settings.workbuddy_cmd = saved

    # 4. 失败路径：退出码 2 + stderr 透出
    os.environ["MOCK_CODEBUDDY_FAIL"] = "1"
    try:
        r = await execute_tool("run_workbuddy_task", {"prompt": "hello"})
        check(
            "失败路径",
            r.get("status") == "error"
            and r.get("exit_code") == 2
            and "not logged in" in r.get("stderr_tail", ""),
            f"exit_code={r.get('exit_code')}",
        )
    finally:
        os.environ.pop("MOCK_CODEBUDDY_FAIL", None)

    # 5. 未登录误报防护：复刻实测——退出码 0、stdout 空、仅 stderr 报 auth 错
    os.environ["MOCK_CODEBUDDY_AUTH"] = "1"
    try:
        r = await execute_tool("run_workbuddy_task", {"prompt": "hello"})
        check(
            "未登录误报防护",
            r.get("status") == "error" and "未登录" in str(r.get("error", "")),
            str(r.get("error", ""))[:50],
        )
    finally:
        os.environ.pop("MOCK_CODEBUDDY_AUTH", None)

    # 6. 空输出守卫：退出码 0 但 stdout/stderr 皆无实质内容
    os.environ["MOCK_CODEBUDDY_EMPTY"] = "1"
    try:
        r = await execute_tool("run_workbuddy_task", {"prompt": "hello"})
        check(
            "空输出守卫",
            r.get("status") == "error" and "没有任何输出" in str(r.get("error", "")),
            str(r.get("error", ""))[:50],
        )
    finally:
        os.environ.pop("MOCK_CODEBUDDY_EMPTY", None)

    # 7. 超时路径：mock 睡 35s > 31s 上限 → 树杀 + 可读错误
    os.environ["MOCK_CODEBUDDY_SLEEP"] = "35"
    try:
        r = await execute_tool("run_workbuddy_task", {"prompt": "大任务", "timeout_seconds": 31})
        check(
            "超时路径",
            r.get("status") == "error" and "超时" in str(r.get("message", "")),
            f"task_id={str(r.get('task_id', ''))[:8]}",
        )
    finally:
        os.environ.pop("MOCK_CODEBUDDY_SLEEP", None)

    failed = [n for ok, n in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        shutil.rmtree(SMOKE_DATA, ignore_errors=True)
    sys.exit(code)
