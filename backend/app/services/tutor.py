"""助教伴学服务（Agent 观察与引导）：针对练习作答与卡点提供启发式诊断，严格不泄露完整代码。"""
import json
import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Exercise, KnowledgePoint
from app.models.exercise import EXERCISE_CODE
from app.services.agent_tools import stream_agent_with_tools
from app.services.execution.runner import run_code
from app.services.exercise import normalize_output
from app.services.llm.base import LLMAdapter
from app.services.llm.errors import LLMError
from app.services.prompt import render_prompt



logger = logging.getLogger(__name__)


async def stream_exercise_diagnosis(
    db: AsyncSession,
    exercise: Exercise,
    adapter: LLMAdapter,
    content: str,
    question: str = "",
    mode: str = "socratic",
) -> AsyncIterator[str]:

    """生成并流式推送助教诊断建议（SSE 格式）。"""


    kp = await db.get(KnowledgePoint, exercise.knowledge_point_id) if exercise.knowledge_point_id else None
    kp_title = kp.title if kp else "（通用知识点）"
    kp_summary = kp.summary if kp else ""

    if exercise.kind == EXERCISE_CODE:
        run_res = await run_code(exercise.language, content)
        norm_actual = normalize_output(run_res.get("stdout", ""))
        norm_expected = normalize_output(exercise.expected_output)

        if run_res.get("status") == "success":
            if norm_actual == norm_expected:
                exec_status = "运行成功，且标准输出与目标完全一致（逻辑已正确）"
            else:
                exec_status = "程序成功运行并退出，但输出内容与目标输出不一致"
        else:
            exec_status = f"运行失败：{run_res.get('status')}（退出码：{run_res.get('exit_code')}）"

        exec_parts = []
        if run_res.get("stdout"):
            exec_parts.append(f"[标准输出 stdout]\n{run_res['stdout']}")
        if run_res.get("stderr"):
            exec_parts.append(f"[错误输出 stderr]\n{run_res['stderr']}")
        exec_output_str = "\n".join(exec_parts) or "（无标准输出与错误信息）"
    else:
        exec_status = f"{exercise.kind} 作答"
        exec_output_str = f"学生提交答案: {content}"

    user_question_sec = f"## 学生的具体提问\n{question.strip()}" if question.strip() else ""

    if mode == "direct":
        mode_instructions = "【直接解答模式】：直接指出具体问题点与修改建议，语言简明，控制在 150 字以内。"
    else:
        mode_instructions = (
            "【苏格拉底启发模式】：肯定已有合理思考；绝对禁止直接给出答案代码；"
            "指出核心思维卡点，并抛出 1 个关键反问或反例，引导学生自己推导出修复方案。"
        )

    system = render_prompt(
        "exercise_tutor",
        KP_TITLE=kp_title,
        KP_SUMMARY=kp_summary,
        TASK_MD=exercise.task_md,
        EXPECTED_OUTPUT=exercise.expected_output,
        LANGUAGE=exercise.language or "text",
        STUDENT_CODE=content,
        EXEC_STATUS=exec_status,
        EXEC_OUTPUT=exec_output_str,
        USER_QUESTION_SECTION=user_question_sec,
        MODE_INSTRUCTIONS=mode_instructions,
    )


    agent_stream = stream_agent_with_tools(
        adapter,
        [{"role": "system", "content": system}],
        db=db,
    )

    try:
        async for evt in agent_stream:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
    except LLMError as e:
        yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("助教诊断流异常")
        yield f"data: {json.dumps({'type': 'error', 'detail': '助教服务暂时不可用，请稍后再试。'}, ensure_ascii=False)}\n\n"
        return

