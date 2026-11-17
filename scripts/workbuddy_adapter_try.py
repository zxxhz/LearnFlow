"""CodebuddyAdapter 真机验证：真实 codebuddy CLI 流式/非流式/JSON 三条路径。

前置：CODEBUDDY_CONFIG_DIR 已由调用方指向 ~/.codebuddy 的项目内副本（agent 沙箱
下 python 子进程写不了 ~/.codebuddy，见 workbuddy-agent-tool 记忆）。
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_DATA_DIR"] = str(ROOT / "backend" / ".smoke-data" / "cb-adapter-test")
os.environ.setdefault("CODEBUDDY_CONFIG_DIR", str(ROOT / "backend" / ".smoke-data" / "cb-config"))
sys.path.insert(0, str(ROOT / "backend"))

from app.services.llm.codebuddy import CodebuddyAdapter  # noqa: E402


async def main() -> int:
    ok = True
    adapter = CodebuddyAdapter(model="hy4flash")

    # 1. 流式：长回复应产生多增量（短回复可能单 delta，属模型行为）
    deltas = []
    gen = await adapter.chat(
        [{"role": "user", "content": "用三句话解释什么是递归，每句都要完整。"}], stream=True
    )
    async for d in gen:
        deltas.append(d)
    text = "".join(deltas)
    print(f"[流式] 增量数={len(deltas)} 全文长度={len(text)}")
    ok &= len(deltas) >= 3 and len(text) > 30

    # 2. 非流式
    raw = await adapter.chat([{"role": "user", "content": "请只回复两个字：好的"}])
    print(f"[非流式] {raw!r}")
    ok &= bool(raw and raw.strip())

    # 3. 多轮转录 + json_mode（经基类 extract_json）
    from pydantic import BaseModel

    class Out(BaseModel):
        answer: str

    out = await adapter.chat_json(
        [
            {"role": "system", "content": "你是一个严谨的助手，总是按要求输出。"},
            {"role": "user", "content": '把"变量与赋值"翻译成英文，输出 JSON：{"answer": "<英文>"}'},
        ],
        Out,
    )
    print(f"[chat_json] {out.model_dump()}")
    ok &= bool(out.answer.strip())

    print("\n全部通过" if ok else "存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
