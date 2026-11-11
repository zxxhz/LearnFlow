"""学习 Agent 本地工具箱：提供受限沙箱运行、数学函数绘图、关卡自省与旧知/错题检索能力。"""
import asyncio
import json
import logging
from typing import Any

from sqlalchemy import or_, select
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
    {
        "type": "function",
        "function": {
            "name": "lookup_learned_section",
            "description": (
                "检索学员已学过的课程章节原文片段（按章节标题/知识点标题/正文关键词匹配）。"
                "用于引用学员以前学过的具体例子、定义或推导来类比当前新概念。"
                "注意：先扫视系统提示中的已学知识骨架目录选好类比锚点，再用本工具取细节。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "检索关键词，如知识点名、章节标题或术语（2~12 字效果最佳）",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_past_mistakes",
            "description": (
                "检索学员以前做错的课程练习与题库错题（按题目标题/题面/作答内容关键词匹配）。"
                "用于发现当前卡点与历史错误的关联，提醒学员不要再踩同一个坑。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "检索关键词，如错误主题、知识点名或术语",
                    }
                },
                "required": ["keyword"],
            },
        },
    },
]


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _tool_lookup_learned_section(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.models import Document, KnowledgePoint, Section

    keyword = str(args.get("keyword") or "").strip()
    if not keyword or db is None:
        return {"error": "缺少检索关键词或数据库上下文"}

    exclude_doc = ""
    ctx = args.get("_ctx") or {}
    if isinstance(ctx, dict):
        exclude_doc = str(ctx.get("exclude_document_id") or "")

    like = f"%{keyword}%"
    cond = [
        Document.title.like(like),
        Document.summary.like(like),
        KnowledgePoint.title.like(like),
        KnowledgePoint.summary.like(like),
        Section.text_excerpt.like(like),
        Section.heading_path.like(like),
    ]
    stmt = (
        select(Section, Document)
        .join(Document, Document.id == Section.document_id)
        .outerjoin(KnowledgePoint, KnowledgePoint.document_id == Document.id)
        .where(Document.status == "done", or_(*cond))
        .order_by(Section.document_id, Section.order_index)
        .limit(12)
    )
    if exclude_doc:
        stmt = stmt.where(Section.document_id != exclude_doc)

    rows = (await db.execute(stmt)).all()

    hits: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for sec, doc in rows:
        if doc.id in seen_docs:
            continue
        seen_docs.add(doc.id)
        heading = ""
        try:
            hp = json.loads(sec.heading_path) if sec.heading_path else []
            heading = " > ".join(str(x) for x in hp)
        except Exception:  # noqa: BLE001
            heading = ""
        excerpt = _clip(sec.text_excerpt or "", 500)
        if not excerpt:
            continue
        references = [
            {
                "label": f"关联已学：《{doc.title}》" + (f" · {heading}" if heading else ""),
                "href": f"/read/{doc.id}?section={sec.id}",
            }
        ]
        hits.append(
            {
                "document_id": doc.id,
                "document_title": doc.title,
                "chapter_index": doc.chapter_index,
                "heading": heading,
                "excerpt": excerpt,
                "references": references,
            }
        )
        if len(hits) >= 3:
            break

    if not hits:
        return {"status": "not_found", "message": f"没有在已学课程中检索到与「{keyword}」相关的章节"}
    return {"status": "success", "hits": hits}


async def _tool_lookup_past_mistakes(
    db: AsyncSession, args: dict[str, Any]
) -> dict[str, Any]:
    from app.models import BankAttempt, BankQuestion, Document, Exercise, ExerciseAttempt, KnowledgePoint

    keyword = str(args.get("keyword") or "").strip()
    if not keyword or db is None:
        return {"error": "缺少检索关键词或数据库上下文"}

    like = f"%{keyword}%"
    hits: list[dict[str, Any]] = []

    # 课程练习错题（只看从未通过的最近一次失败作答）
    ex_rows = (
        await db.execute(
            select(ExerciseAttempt, Exercise, Document)
            .join(Exercise, Exercise.id == ExerciseAttempt.exercise_id)
            .outerjoin(Document, Document.id == Exercise.document_id)
            .outerjoin(KnowledgePoint, KnowledgePoint.id == Exercise.knowledge_point_id)
            .where(
                ExerciseAttempt.passed.is_(False),
                or_(
                    Exercise.title.like(like),
                    Exercise.task_md.like(like),
                    ExerciseAttempt.content.like(like),
                    KnowledgePoint.title.like(like),
                ),
            )
            .order_by(ExerciseAttempt.created_at.desc())
            .limit(6)
        )
    ).all()
    for att, ex, doc in ex_rows:
        href = f"/read/{doc.id}?section={ex.knowledge_point_id}" if doc else ""
        hits.append(
            {
                "source": "course_exercise",
                "title": ex.title,
                "course": doc.title if doc else "",
                "task_excerpt": _clip(ex.task_md, 220),
                "user_answer_excerpt": _clip(att.content, 220),
                "created_at": att.created_at,
                "references": [
                    {
                        "label": f"历史错题：{ex.title}" + (f"（《{doc.title}》）" if doc else ""),
                        "href": href,
                    }
                ],
            }
        )
        if len(hits) >= 3:
            break

    # 题库错题
    if len(hits) < 3:
        bank_rows = (
            await db.execute(
                select(BankAttempt, BankQuestion)
                .join(BankQuestion, BankQuestion.id == BankAttempt.question_id)
                .where(
                    BankAttempt.passed.is_(False),
                    or_(
                        BankQuestion.title.like(like),
                        BankQuestion.ai_explanation.like(like),
                        BankQuestion.explanation.like(like),
                    ),
                )
                .order_by(BankAttempt.created_at.desc())
                .limit(6)
            )
        ).all()
        for att, q in bank_rows:
            hits.append(
                {
                    "source": "bank_question",
                    "title": f"题库第 {q.seq} 题",
                    "course": "",
                    "task_excerpt": _clip(q.title, 220),
                    "user_answer_excerpt": f"学员作答：{att.content}（正确答案：{q.answer_raw or q.answer}）",
                    "created_at": att.created_at,
                    "references": [
                        {
                            "label": f"历史错题：题库第 {q.seq} 题",
                            "href": "/bank",
                        }
                    ],
                }
            )
            if len(hits) >= 3:
                break

    if not hits:
        return {"status": "not_found", "message": f"没有检索到与「{keyword}」相关的历史错题"}
    return {"status": "success", "hits": hits}


async def execute_tool(
    name: str,
    arguments: dict[str, Any] | str,
    db: AsyncSession | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行工具并返回结构化结果字典。context：服务层注入的调用现场（如当前文档 ID）。"""
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
            # 与 API 层 /api/math/render 同一套校验（v0.5.1 体检 P2）：区间合法、跨度受限、10s 超时，
            # 防模型给出的离谱区间卡死 to_thread 线程并让 SSE 永久停在工具步
            try:
                x_min = float(args.get("x_min", -10.0))
                x_max = float(args.get("x_max", 10.0))
            except (TypeError, ValueError):
                x_min, x_max = -10.0, 10.0
            import math as _math

            if not (_math.isfinite(x_min) and _math.isfinite(x_max)) or x_max <= x_min:
                x_min, x_max = -10.0, 10.0
            if (x_max - x_min) > 10000:
                x_min, x_max = -10.0, 10.0
            try:
                svg = await asyncio.wait_for(
                    asyncio.to_thread(render_sync, exprs, x_min, x_max), timeout=10.0
                )
            except asyncio.TimeoutError:
                return {"error": "函数图像渲染超时（10s），已放弃本次绘制"}
            # svg 通过 tool_result 事件透传给前端渲染；进入 LLM 历史前由 runner 剥离避免撑爆上下文
            return {
                "status": "success",
                "svg": svg,
                "svg_length": len(svg),
                "expressions": exprs,
            }

        elif name == "inspect_exercise":
            from app.models import Exercise

            ex_id = str(args.get("exercise_id") or "")
            if not ex_id or db is None:
                return {"error": "缺少 exercise_id 或数据库上下文"}
            exercise = await db.get(Exercise, ex_id)
            if exercise is None:
                return {"error": f"未找到 ID 为 {ex_id} 的关卡"}
            # 服务端防泄题白名单（v0.5.1 体检 P1）：苏格拉底护栏场景下参考实现/预期输出/渐进提示
            # 一律不出服务端——护栏不能只靠提示词，答案字段绝不允许经 tool_result 事件到达浏览器
            guardrail = ""
            if isinstance(context, dict):
                guardrail = str(context.get("guardrail") or "")
            if guardrail == "socratic":
                return {
                    "id": exercise.id,
                    "title": exercise.title,
                    "task": exercise.task_md,
                    "language": exercise.language,
                    "reference_hidden": True,
                    "note": "学员当前练习未通过（启发式辅导场景），参考实现、预期输出与渐进提示已按防泄题策略隐藏；请基于题面与学员作答点拨思路。",
                }
            return {
                "id": exercise.id,
                "title": exercise.title,
                "task": exercise.task_md,
                "language": exercise.language,
                "expected_output": exercise.expected_output,
                "reference_code": exercise.reference_code,
                "hints": exercise.hints,
            }

        elif name == "lookup_learned_section":
            args = {**args, "_ctx": context or {}}
            return await _tool_lookup_learned_section(db, args)

        elif name == "lookup_past_mistakes":
            return await _tool_lookup_past_mistakes(db, args)

        else:
            return {"error": f"未注册的工具：{name}"}

    except Exception as e:
        logger.exception(f"工具执行异常：{name}")
        return {"error": str(e)}
