"""Agent 工具调度执行器：多轮 Tool Calling 闭环与流式生成。"""
import json
import logging
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_tools.registry import AGENT_TOOLS_SCHEMA, execute_tool
from app.services.llm.openai_compat import OpenAICompatAdapter

logger = logging.getLogger(__name__)


async def stream_agent_with_tools(
    adapter: OpenAICompatAdapter,
    messages: list[dict],
    *,
    db: AsyncSession | None = None,
    tools: list[dict] | None = None,
    max_tool_steps: int = 2,
) -> AsyncIterator[dict[str, Any]]:
    """支持工具调用的 Agent 执行器。

    事件类型：
    - {"type": "tool_call", "name": str, "args": dict}
    - {"type": "tool_result", "name": str, "result": dict}
    - {"type": "delta", "text": str}
    - {"type": "done"}
    """
    tools_to_use = tools or AGENT_TOOLS_SCHEMA
    history = list(messages)

    for _ in range(max_tool_steps):
        try:
            msg = await adapter.chat_raw(history, tools=tools_to_use)
        except Exception as e:
            logger.warning(f"Tool Calling 评估失败，降级到纯文本流式: {e}")
            break

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            break

        # 存在模型触发的工具调用
        tc_dicts = []
        for tc in tool_calls:
            tc_dicts.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            })

        history.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": tc_dicts,
        })

        for tc in tool_calls:
            fn_name = tc.function.name
            raw_args = tc.function.arguments
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}

            yield {"type": "tool_call", "name": fn_name, "args": args}
            result = await execute_tool(fn_name, args, db=db)
            yield {"type": "tool_result", "name": fn_name, "result": result}

            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    # 工具交互完成后，进行最终的流式回答
    deltas = adapter.chat(history, stream=True)
    async for delta in deltas:
        yield {"type": "delta", "text": delta}
    yield {"type": "done"}
