"""冒烟用 mock codebuddy CLI：读 stdin 提示词 → 可选延时/失败 → 产出文件 + JSON 结果。

环境变量开关（由 scripts/workbuddy_mvp_smoke.py 控制）：
- MOCK_CODEBUDDY_SLEEP：先睡 N 秒再干活（测超时树杀路径）
- MOCK_CODEBUDDY_FAIL=1：以退出码 2 结束并往 stderr 写未登录报错（测失败路径）
"""
import json
import os
import sys
import time
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sleep_s = float(os.environ.get("MOCK_CODEBUDDY_SLEEP") or 0)
if sleep_s > 0:
    time.sleep(sleep_s)

prompt = sys.stdin.read()
Path("产出.md").write_text(f"# Mock 产出\n\nprompt 长度：{len(prompt)} 字\n", encoding="utf-8")

if os.environ.get("MOCK_CODEBUDDY_FAIL") == "1":
    print("mock: simulated failure (not logged in)", file=sys.stderr)
    sys.exit(2)

# 复刻实测行为：未登录时 CLI 退出码为 0、stdout 全空、仅 stderr 报错
if os.environ.get("MOCK_CODEBUDDY_AUTH") == "1":
    print(
        "Authentication required. Please use /login command to sign in to your account",
        file=sys.stderr,
    )
    sys.exit(0)

# 退出码 0 但无任何输出（版本不支持 --output-format 等）
if os.environ.get("MOCK_CODEBUDDY_EMPTY") == "1":
    sys.exit(0)

json.dump(
    {
        "result": f"mock 任务完成：收到 prompt {len(prompt)} 字，产出 产出.md",
        "session_id": "mock-session-1",
    },
    sys.stdout,
    ensure_ascii=False,
)
