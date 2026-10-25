"""Agent 工具调度执行器：多轮 Tool Calling 闭环与流式生成。"""
import asyncio
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
    final_content: str | None = None

    for _ in range(max_tool_steps):
        try:
            msg = await adapter.chat_raw(history, tools=tools_to_use)
        except Exception as e:
            logger.warning(f"Tool Calling 评估失败，降级到纯文本流式: {e}")
            break

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            # 模型未触发工具，已在当前轮次获得完整回答内容
            final_content = msg.content or ""
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

            # 大体积二进制产物（如 SVG 图像）只走前端事件，不进 LLM 历史，防止撑爆上下文
            history_result = {k: v for k, v in result.items() if k != "svg"}
            if "svg" in result:
                history_result["note"] = "函数图像已生成并实时展示给学生，请基于该图像继续讲解"
            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(history_result, ensure_ascii=False),
            })

    # 若已有完整的生成文本，以平滑打字机分块推送，避免二次调用 LLM 产生双倍费用和额外等待
    if final_content:
        chunk_size = 12
        for i in range(0, len(final_content), chunk_size):
            yield {"type": "delta", "text": final_content[i:i + chunk_size]}
            if len(final_content) > chunk_size:
                await asyncio.sleep(0.01)
        yield {"type": "done"}
        return

    # 工具交互完成或未获得预生成文本时，进行流式回答
    deltas = await adapter.chat(history, stream=True)
    async for delta in deltas:
        yield {"type": "delta", "text": delta}
    yield {"type": "done"}
