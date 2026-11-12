"""统一「AI 助教」服务（v0.5.0）：全站唯一的答疑 Agent。

三层记忆组装：
- L0 常驻：已学知识骨架目录（build_learned_knowledge_index）+ 分学科认知画像；
- L1 按需：lookup_learned_section / lookup_past_mistakes / run_sandbox_code / render_math_plot 工具；
- L2 现场：当前场景上下文（讲义小节原文 / 练习题+实时判题 / 题库题目+作答）+ 会话历史。

同一章节内「看讲义」与「做练习」共用 document 会话，上下文自然延续；
练习未通过时自动上苏格拉底护栏（不泄答案），讲解/已通关场景放开直答。
v0.5.1：模型自主沙箱运行须学员授权（会话级记忆）；护栏下沉为服务端工具字段白名单。
"""
import asyncio
import json
import logging
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BankQuestion,
    Conversation,
    Course,
    Document,
    Exercise,
    KnowledgePoint,
    Message,
    Section,
)
from app.models.exercise import EXERCISE_CODE
from app.models.conversation import CONVERSATION_KIND_ASSISTANT
from app.services.agent_tools import stream_agent_with_tools
from app.services.agent_tools.registry import select_tool_schemas
from app.services.context import build_learned_knowledge_index
from app.services.execution.runner import run_code
from app.services.exercise import normalize_output
from app.services.profile import (
    discipline_for_document,
    discipline_for_text,
    format_profile_for_prompt,
)
from app.services.prompt import render_prompt
from app.services.sections_text import get_section_text

logger = logging.getLogger(__name__)

ASSISTANT_CONTEXT_TYPES = ("document", "bank_question", "global")
ASSISTANT_SCENE_KINDS = ("reading", "exercise", "bank", "global")

# ===== 模型自主沙箱运行的一次性授权（v0.5.1 体检 P1）=====
# 单用户本地产品：授权状态按会话存内存（进程生命周期），不落库不跨端；
# 未授权时每个 run_sandbox_code 工具调用先向学员要一次许可，超时/拒绝即跳过——
# 导入内容里的间接提示注入在无人值守场景下永远拿不到授权。
CONFIRM_TIMEOUT_SECONDS = 180
_pending_tool_confirms: dict[str, "asyncio.Future[bool]"] = {}
_sandbox_allowed_conversations: set[str] = set()

# 苏格拉底护栏文本：注入练习未通过 / 未作答场景（防泄题），其余场景为空（放开直答）
_GUARDRAIL_SOCRATIC = """## 场景护栏（最高优先级，覆盖其他一切准则）
学员当前这道练习**尚未通过**，此刻他需要的是自己想明白，而不是被告知答案：
1. **绝对禁止给出完整可运行的答案代码、最终计算结果或选项字母**，最后一步必须留给他亲手改出来；
2. 可以引用他代码/作答里的某一行，直接指出「问题出在这一行」；可以讲思路、画导图、翻旧知类比、跑沙箱演示**别的例子**；
3. 单点聚焦：只抓一个最前置或最致命的卡点（编译语法 > 崩溃 > 核心逻辑 > 输出格式），抛出一个引导他下一步动手的反问。"""

_GUARDRAIL_FREE = "（学员当前处于讲解/讨论场景，可自由完整地解答。）"


async def get_or_create_assistant_session(
    db: AsyncSession, context_type: str, context_id: str
) -> Conversation:
    """按归属域幂等取回助教会话：同一章节/同一道题/全局永远只有一条连续会话流。

    单用户产品，user_id 由模型默认值（local）承接。
    """
    if context_type not in ASSISTANT_CONTEXT_TYPES:
        raise ValueError(f"不支持的会话归属域：{context_type}")
    norm_context_id = (context_id or "").strip() or "global"
    conv = (
        await db.scalars(
            select(Conversation)
            .where(
                Conversation.kind == CONVERSATION_KIND_ASSISTANT,
                Conversation.context_type == context_type,
                Conversation.context_id == norm_context_id,
            )
            .order_by(Conversation.created_at)
            .limit(1)
        )
    ).first()
    if conv is not None:
        return conv
    conv = Conversation(
        kind=CONVERSATION_KIND_ASSISTANT,
        annotation_id=None,
        context_type=context_type,
        context_id=norm_context_id,
    )
    db.add(conv)
    try:
        await db.commit()
    except IntegrityError:
        # 并发首访（局域网两台设备同时打开同一章节）撞唯一索引：回滚重查最早一条，
        # 防止产生重复会话导致消息黑洞（v0.5.1 体检 P2）
        await db.rollback()
        conv = (
            await db.scalars(
                select(Conversation)
                .where(
                    Conversation.kind == CONVERSATION_KIND_ASSISTANT,
                    Conversation.context_type == context_type,
                    Conversation.context_id == norm_context_id,
                )
                .order_by(Conversation.created_at)
                .limit(1)
            )
        ).first()
        if conv is None:
            raise
        return conv
    await db.refresh(conv)
    return conv


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _reading_scene_block(db: AsyncSession, scene: dict[str, Any]) -> str:
    parts: list[str] = ["【场景：阅读讲义提问】"]
    document_id = str(scene.get("document_id") or "")
    doc = await db.get(Document, document_id) if document_id else None
    if doc is not None:
        course = await db.get(Course, doc.course_id)
        parts.append(f"课程：《{course.title}》　章节：第{doc.chapter_index}章《{doc.title}》")
        section_id = str(scene.get("section_id") or "")
        if section_id:
            sec = (
                await db.scalars(
                    select(Section).where(
                        Section.document_id == doc.id, Section.id == section_id
                    )
                )
            ).first()
            if sec is not None:
                try:
                    hp = json.loads(sec.heading_path) if sec.heading_path else []
                except Exception:  # noqa: BLE001
                    hp = []
                heading = " > ".join(str(x) for x in hp)
                if heading:
                    parts.append(f"所在小节：{heading}")
        selected = str(scene.get("selected_text") or "").strip()
        if selected:
            parts.append(f"学员划选引用的片段：\n{_clip(selected, 400)}")
            # 引用片段所在小节的原文一并带上，保证「沿用语境」答疑
            if section_id:
                sec_text = await get_section_text(db, doc, section_id)
                if sec_text:
                    parts.append(f"该小节原文（供参照语境）：\n{_clip(sec_text, 1600)}")
        else:
            parts.append("（学员未划选具体片段，就本章节内容自由提问）")
    else:
        parts.append("（文档上下文缺失，就学员的问题直接回答）")
    return "\n".join(parts)


async def _exercise_scene_block(
    db: AsyncSession, scene: dict[str, Any]
) -> tuple[str, str]:
    """返回 (场景块, 护栏)。练习未通过或未作答 → 苏格拉底护栏。"""
    exercise_id = str(scene.get("exercise_id") or "")
    ex = await db.get(Exercise, exercise_id) if exercise_id else None
    if ex is None:
        return "【场景：练习辅导】（练习题上下文缺失，就学员的问题直接回答。）", _GUARDRAIL_FREE

    kp = (
        await db.get(KnowledgePoint, ex.knowledge_point_id)
        if ex.knowledge_point_id
        else None
    )
    doc = await db.get(Document, ex.document_id) if ex.document_id else None
    course = await db.get(Course, doc.course_id) if doc is not None else None

    parts = [f"【场景：课后练习辅导】（课程：《{course.title}》 第{doc.chapter_index}章《{doc.title}》）" if course and doc else "【场景：课后练习辅导】"]
    if kp is not None:
        parts.append(f"关联知识点：{kp.title}")
    parts.append(f"题型：{ex.kind}　题目标题：{ex.title}")
    parts.append(f"题目要求：\n{_clip(ex.task_md, 1200)}")
    if ex.kind == EXERCISE_CODE:
        parts.append(f"目标输出（逐字符一致）：\n{_clip(ex.expected_output, 400)}")
        code = str(scene.get("user_code") or "").strip()
        if not code:
            parts.append("学员当前代码：（还没写，正在思考起步思路）")
            guardrail = _GUARDRAIL_SOCRATIC  # 未作答也不许剧透
        else:
            parts.append(f"学员当前代码：\n```{ex.language or ''}\n{_clip(code, 3000)}\n```")
            # 实时沙箱判一次，给助教真实的运行事实（与旧 tutor 一致）
            run_res = await run_code(ex.language or "python", code)
            status = run_res.get("status")
            if status == "success":
                same = normalize_output(run_res.get("stdout", "")) == normalize_output(
                    ex.expected_output
                )
                exec_status = (
                    "运行成功，输出与目标完全一致（逻辑已正确）"
                    if same
                    else "运行成功退出，但输出与目标不一致"
                )
            else:
                exec_status = f"运行失败：{status}（退出码 {run_res.get('exit_code')}）"
            out_parts = []
            if run_res.get("stdout"):
                out_parts.append(f"[stdout]\n{run_res['stdout'][:800]}")
            if run_res.get("stderr"):
                out_parts.append(f"[stderr]\n{run_res['stderr'][:800]}")
            parts.append(
                f"实时判题状态：{exec_status}\n" + ("\n".join(out_parts) or "（无输出）")
            )
            judge = str(scene.get("judge_status") or "").strip()
            guardrail = _GUARDRAIL_FREE if judge == "passed" else _GUARDRAIL_SOCRATIC
    else:
        ans = str(scene.get("user_answer") or "").strip()
        parts.append(
            f"学员当前作答：{_clip(ans, 800) if ans else '（还没作答）'}"
        )
        if str(scene.get("judge_status") or "") == "passed":
            parts.append(f"参考答案（供对照讲评）：{_clip(ex.reference_answer or ex.answer, 400)}")
            guardrail = _GUARDRAIL_FREE
        else:
            guardrail = _GUARDRAIL_SOCRATIC
    return "\n".join(parts), guardrail


async def _bank_scene_block(db: AsyncSession, scene: dict[str, Any]) -> tuple[str, str]:
    question_id = str(scene.get("bank_question_id") or "")
    q = await db.get(BankQuestion, question_id) if question_id else None
    if q is None:
        return "【场景：题库刷题】（题目上下文缺失，就学员的问题直接回答。）", _GUARDRAIL_FREE

    parts = [f"【场景：题库刷题】（题库第 {q.seq} 题，题型：{q.qtype}，难度：{q.difficulty or '未知'}）"]
    parts.append(f"题面：\n{_clip(q.title, 1200)}")
    if q.options and q.options not in ("[]", ""):
        try:
            opts = json.loads(q.options)
            letters = "ABCDEFGH"
            opt_lines = [
                f"{letters[i]}. {o}" for i, o in enumerate(opts) if str(o).strip()
            ]
            if opt_lines:
                parts.append("选项：\n" + "\n".join(opt_lines))
        except Exception:  # noqa: BLE001
            pass
    user_answer = str(scene.get("user_answer") or "").strip()
    judge = str(scene.get("judge_status") or "").strip()
    if user_answer:
        # 学员作答一律裁剪：scene 来自请求体任意字段，超长内容原样拼入会随历史反复膨胀上下文
        parts.append(f"学员的作答：{_clip(user_answer, 800)}（判题：{'通过' if judge == 'passed' else '未通过' if judge == 'failed' else '未提交'}）")
    if judge == "passed":
        # 已做对：放开讲透，包括深挖易混项
        parts.append(f"正确答案：{q.answer_raw or q.answer}")
        if (q.explanation or q.ai_explanation).strip():
            parts.append(f"已有解析（可深挖或纠偏）：{_clip(q.explanation or q.ai_explanation, 800)}")
        return "\n".join(parts), _GUARDRAIL_FREE
    # 未通过 / 未提交：引导他找到正确项，不直接报答案
    return "\n".join(parts), _GUARDRAIL_SOCRATIC


async def build_assistant_messages(
    db: AsyncSession, conv: Conversation, scene: dict[str, Any]
) -> tuple[list[dict], str, str, str]:
    """组装助教消息序列。返回 (messages, evolve_scope, document_id, guardrail_mode)。

    document_id 供工具现场排除当前章节（lookup 不再翻正在读的这节）；
    guardrail_mode ∈ {"socratic", "free"} 同步下沉给工具层做服务端防泄题白名单。
    """
    kind = str(scene.get("kind") or "global")
    if kind not in ASSISTANT_SCENE_KINDS:
        kind = "global"

    exclude_doc_id = ""
    evolve_scope = "general"
    guardrail = _GUARDRAIL_FREE

    if kind == "reading":
        scene_block = await _reading_scene_block(db, scene)
        document_id = str(scene.get("document_id") or "")
        if document_id:
            doc = await db.get(Document, document_id)
            if doc is not None:
                exclude_doc_id = doc.id
                evolve_scope = await discipline_for_document(db, doc)
    elif kind == "exercise":
        scene_block, guardrail = await _exercise_scene_block(db, scene)
        exercise_id = str(scene.get("exercise_id") or "")
        ex = await db.get(Exercise, exercise_id) if exercise_id else None
        if ex is not None and ex.document_id:
            doc = await db.get(Document, ex.document_id)
            if doc is not None:
                exclude_doc_id = doc.id
                evolve_scope = await discipline_for_document(db, doc)
    elif kind == "bank":
        scene_block, guardrail = await _bank_scene_block(db, scene)
        question_id = str(scene.get("bank_question_id") or "")
        q = await db.get(BankQuestion, question_id) if question_id else None
        if q is not None:
            from app.models import QuestionBank

            bank = await db.get(QuestionBank, q.bank_id)
            if bank is not None:
                evolve_scope = discipline_for_text(bank.name)
    else:
        scene_block = "【场景：全局提问】（学员在任意页面呼出助教，可能是跨课程问题、学习规划或概念闲问。结合画像与知识目录回答。）"

    learned_index = await build_learned_knowledge_index(db, exclude_document_id=exclude_doc_id or None)
    profile_text = await format_profile_for_prompt(db, scope=evolve_scope)
    system = render_prompt(
        "assistant_agent",
        LEARNED_INDEX=learned_index,
        LEARNER_PROFILE=profile_text,
        SCENE_BLOCK=scene_block,
        GUARDRAIL=guardrail,
    )

    history = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(30)
        )
    ).all()
    messages = [{"role": "system", "content": system}]
    # 历史回放逐条裁剪：一条超长消息若原样保留，会被后续 29 轮反复原样带入撑爆上下文
    messages += [{"role": m.role, "content": _clip(m.content, 4000)} for m in reversed(history)]
    guardrail_mode = "socratic" if guardrail is _GUARDRAIL_SOCRATIC else "free"
    return messages, evolve_scope, exclude_doc_id, guardrail_mode


async def resolve_scene_scope(db: AsyncSession, scene: dict[str, Any]) -> str:
    """轻量解析画像演进学科域：只做归属查询，绝不触发沙箱运行或全文组装。

    供消息流结束后计算 evolve_scope 用——修复 v0.5.1 体检 P2「每条练习消息跑两次沙箱」：
    此前为取 scope 重复执行了整趟 build_assistant_messages（含实时判题）。
    """
    kind = str(scene.get("kind") or "global")
    if kind == "reading":
        document_id = str(scene.get("document_id") or "")
        doc = await db.get(Document, document_id) if document_id else None
        return await discipline_for_document(db, doc) if doc is not None else "general"
    if kind == "exercise":
        exercise_id = str(scene.get("exercise_id") or "")
        ex = await db.get(Exercise, exercise_id) if exercise_id else None
        if ex is not None and ex.document_id:
            doc = await db.get(Document, ex.document_id)
            if doc is not None:
                return await discipline_for_document(db, doc)
        return "general"
    if kind == "bank":
        question_id = str(scene.get("bank_question_id") or "")
        q = await db.get(BankQuestion, question_id) if question_id else None
        if q is not None:
            from app.models import QuestionBank

            bank = await db.get(QuestionBank, q.bank_id)
            if bank is not None:
                return discipline_for_text(bank.name)
        return "general"
    return "general"


def _make_confirm_callback(conv_id: str):
    """敏感工具（run_sandbox_code）的一次性授权回调。

    会话已授权 → 直接放行；否则注册 pending Future 等学员响应（SSE confirm 事件由
    runner 的 tool_call 事件承载，API 层 /tool-confirm 端点落结果），超时/拒绝返回 False。
    """

    async def confirm(name: str, args: dict, seq: int) -> bool:
        if conv_id in _sandbox_allowed_conversations:
            return True
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        _pending_tool_confirms[conv_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout=CONFIRM_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.info("沙箱授权等待超时（conv=%s seq=%s），跳过工具执行", conv_id, seq)
            return False
        finally:
            if _pending_tool_confirms.get(conv_id) is fut:
                _pending_tool_confirms.pop(conv_id, None)

    return confirm


def resolve_tool_confirm(conv_id: str, approve: bool, remember: bool) -> bool:
    """落学员的授权决定。返回 False 表示当前没有等待中的授权请求。"""
    fut = _pending_tool_confirms.get(conv_id)
    if fut is None or fut.done():
        return False
    if approve and remember:
        _sandbox_allowed_conversations.add(conv_id)
    if not fut.done():
        fut.set_result(bool(approve))
    return True


async def stream_assistant_reply(
    db: AsyncSession,
    conv: Conversation,
    scene: dict[str, Any],
    adapter,
) -> AsyncIterator[dict[str, Any]]:
    """运行统一助教 Agent 并流式产出 SSE 事件字典。

    事件：user_ack（由 API 层先发）/ tool_call / tool_result / reference / delta / done / error。
    """
    try:
        messages, _scope, exclude_doc, guardrail_mode = await build_assistant_messages(db, conv, scene)
    except Exception:  # noqa: BLE001
        logger.exception("助教上下文组装失败")
        yield {"type": "error", "detail": "助教上下文组装失败，请稍后重试"}
        return

    agent_stream = stream_agent_with_tools(
        adapter,
        messages,
        db=db,
        # v0.5.6 全量工具扩权：按会话归属域裁剪注入的工具集（读类全量直调，
        # 写类经 runner 层确认卡放行），并放宽工具步数支持连环操作
        tools=select_tool_schemas(str(conv.context_type or "global")),
        max_tool_steps=6,
        context={"exclude_document_id": exclude_doc, "guardrail": guardrail_mode},
        confirm_sensitive=_make_confirm_callback(conv.id),
    )
    try:
        async for evt in agent_stream:
            if evt.get("type") == "tool_result" and isinstance(evt.get("result"), dict):
                result = evt["result"]
                if result.get("hits"):
                    # 检索类工具命中：把来源引用单独推给前端渲染跳转标签
                    refs = []
                    for hit in result["hits"]:
                        refs.extend(hit.get("references") or [])
                    if refs:
                        yield {"type": "reference", "references": refs}
                elif result.get("references"):
                    # v0.5.6 读/写类工具直接携带 references（课程/题库/导图/修订落点等）
                    yield {"type": "reference", "references": result["references"]}
            yield evt
    except Exception as e:  # noqa: BLE001
        logger.exception("助教流式生成异常")
        detail = getattr(e, "message", None) or "助教服务暂时不可用，请稍后再试"
        yield {"type": "error", "detail": detail}
        return
    finally:
        try:
            await agent_stream.aclose()
        except Exception:
            pass


def build_evolution_interaction(
    user_content: str, reply_text: str, scene: dict[str, Any]
) -> tuple[str, str]:
    """画像演进的 (context, interaction) 文本对。"""
    kind = str(scene.get("kind") or "global")
    if kind == "exercise":
        context = f"练习辅导场景，学员提问：{user_content[:200]}"
    elif kind == "bank":
        context = f"题库刷题场景，学员提问：{user_content[:200]}"
    elif kind == "reading":
        context = f"讲义阅读提问：{user_content[:200]}（划选：{str(scene.get('selected_text') or '')[:120]}）"
    else:
        context = f"全局提问：{user_content[:200]}"
    return context, f"学生提问：{user_content}\n助教解答：{reply_text[:300]}"


__all__ = [
    "ASSISTANT_CONTEXT_TYPES",
    "ASSISTANT_SCENE_KINDS",
    "CONFIRM_TIMEOUT_SECONDS",
    "build_assistant_messages",
    "build_evolution_interaction",
    "get_or_create_assistant_session",
    "resolve_scene_scope",
    "resolve_tool_confirm",
    "stream_assistant_reply",
]
