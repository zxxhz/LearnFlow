"""学习 Agent 本地工具箱：提供受限沙箱运行、数学函数绘图和关卡自省能力。"""
import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution.runner import run_code

logger = logging.getLogger(__name__)

# OpenAI 兼容协议工具声明定义
AGENT_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "run_sandbox_code",
            "description": (
                "在受限安全沙箱中编译并真实运行 Python 或 C++ 代码，"
                "返回 stdout、stderr、exit_code 和执行状态。用于验证代码、排查错误、重现 bug 或测试运行结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要运行的代码完整文本"},
                    "language": {
                        "type": "string",
                        "enum": ["python", "cpp"],
                        "description": "代码语言（python 或 cpp）",
                    },
                },
                "required": ["code", "language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_math_plot",
            "description": (
                "使用 SymPy 解析并用 Matplotlib 渲染一维数学函数图像为矢量 SVG。"
                "用于帮助学生直观理解函数曲线、极值、奇点和图像性质。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expressions": {
                        "type": "string",
                        "description": "要绘制的函数表达式（多个函数用换行隔开，例如 'sin(x)/x' 或 'x**2'）",
                    },
                    "x_min": {
                        "type": "number",
                        "description": "x 轴起始范围（默认 -10）",
                        "default": -10.0,
                    },
                    "x_max": {
                        "type": "number",
                        "description": "x 轴结束范围（默认 10）",
                        "default": 10.0,
                    },
                },
                "required": ["expressions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_exercise",
            "description": "查询特定练习题或关卡的题面任务、提示信息、预期目标输出和参考实现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_id": {
                        "type": "string",
                        "description": "练习题或关卡的 ID",
                    }
                },
                "required": ["exercise_id"],
            },
        },
    },
]


async def execute_tool(
    name: str,
    arguments: dict[str, Any] | str,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """执行工具并返回结构化结果字典。"""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments or {}

    try:
        if name == "run_sandbox_code":
            code = str(args.get("code") or "")
            lang = str(args.get("language") or "python").lower()
            if not code.strip():
                return {"error": "代码内容为空"}
            res = await run_code(lang, code)
            return {
                "status": res["status"],
                "exit_code": res["exit_code"],
                "stdout": res["stdout"],
                "stderr": res["stderr"],
                "duration_ms": res["duration_ms"],
            }

        elif name == "render_math_plot":
            from app.api.math import render_sync

            exprs = str(args.get("expressions") or "").strip()
            if not exprs:
                return {"error": "函数表达式为空"}
            x_min = float(args.get("x_min", -10.0))
            x_max = float(args.get("x_max", 10.0))
            svg = await asyncio.to_thread(render_sync, exprs, x_min, x_max)
            return {"status": "success", "svg_length": len(svg), "expressions": exprs}

        elif name == "inspect_exercise":
            from app.models import Exercise

            ex_id = str(args.get("exercise_id") or "")
            if not ex_id or db is None:
                return {"error": "缺少 exercise_id 或数据库上下文"}
            exercise = await db.get(Exercise, ex_id)
            if exercise is None:
                return {"error": f"未找到 ID 为 {ex_id} 的关卡"}
            return {
                "id": exercise.id,
                "title": exercise.title,
                "task": exercise.task_md,
                "language": exercise.language,
                "expected_output": exercise.expected_output,
                "reference_code": exercise.reference_code,
                "hints": exercise.hints,
            }

        else:
            return {"error": f"未注册的工具：{name}"}

    except Exception as e:
        logger.exception(f"工具执行异常：{name}")
        return {"error": str(e)}
