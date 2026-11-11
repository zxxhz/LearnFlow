"""划线答疑的上下文组装（PRD FR-3.2：携带划线原文 + 所在章节 + 前后章摘要）。

v0.5.0 新增 L0 个人已学知识骨架索引：把全部课程→章节→知识点（含掌握度）压缩成
一份常驻目录树，让统一 AI 助教「知道学员学过什么」而不撑爆上下文（跨课类比的地基）。
"""
import json

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Annotation,
    Conversation,
    Course,
    Document,
    Exercise,
    ExerciseAttempt,
    KnowledgePoint,
    Message,
    Section,
)
from app.services.profile import discipline_for_course, format_profile_for_prompt
from app.services.prompt import render_prompt
from app.services.sections_text import get_section_text

# L0 目录长度预算（字符）：超限时逐级降级（丢摘要 → 截断尾巴），保证常驻系统提示不失控
LEARNED_INDEX_MAX_CHARS = 4000


async def build_annotation_messages(
    db: AsyncSession, conversation: Conversation
) -> list[dict]:
    """构造 [system] + 历史。调用前 user 消息已入库（历史里含最新一条）。"""
    ann = await db.get(Annotation, conversation.annotation_id) if conversation.annotation_id else None
    if ann is None:
        raise ValueError("标注不存在")
    document = await db.get(Document, ann.document_id)
    course = await db.get(Course, document.course_id)

    section_text = await get_section_text(db, document, ann.section_id)
    sec = (
        await db.scalars(
            select(Section).where(
                Section.document_id == document.id, Section.id == ann.section_id
            )
        )
    ).first()
    heading = " > ".join(json.loads(sec.heading_path)) if sec and sec.heading_path else ""

    neighbors = []
    for offset in (-1, 1):
        n = (
            await db.scalars(
                select(Document).where(
                    Document.course_id == course.id,
                    Document.chapter_index == document.chapter_index + offset,
                )
            )
        ).first()
        if n and n.summary:
            label = "上一章" if offset == -1 else "下一章"
            neighbors.append(f"{label}《{n.title}》摘要：{n.summary}")

    # 按课程学科域过滤盲区注入，防止跨学科串味（如 C++ 盲区混进高数答疑）
    profile_text = await format_profile_for_prompt(db, scope=discipline_for_course(course))
    system = render_prompt(
        "annotation_qa",
        COURSE_TITLE=course.title,
        DOC_TITLE=document.title + (f"（位于：{heading}）" if heading else ""),
        DOC_SUMMARY=document.summary or "（无摘要）",
        NAV_SUMMARIES="\n".join(neighbors) or "（无）",
        LEARNER_PROFILE=profile_text,
        EXACT=ann.exact,
        SECTION_TEXT=section_text or "（原文缺失，请基于划线内容回答）",
    )
    history = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
        )
        .limit(30)
        .all()
    )
    # 超长对话只带最近 30 条（15 轮）；倒序取最新 30 条后正序回排，保证最新提问在上下文末尾
    trimmed = list(reversed(history))
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in trimmed]
    return messages


async def _kp_mastery_map(db: AsyncSession) -> dict[str, str]:
    """按知识点聚合闯关进度 → 掌握度标签（已掌握 / 学习中 / 未测）。

    已掌握 = 该知识点全部闯关练习均已通过过至少一次；学习中 = 部分通过；未测 = 尚无练习。
    随堂小测题（quiz_id 非空）不计入，避免一次测验左右长期掌握度判断。
    """
    totals = dict(
        (
            await db.execute(
                select(Exercise.knowledge_point_id, func.count(Exercise.id))
                .where(Exercise.knowledge_point_id != "")
                .group_by(Exercise.knowledge_point_id)
            )
        ).all()
    )
    passed_rows = (
        await db.execute(
            select(
                Exercise.knowledge_point_id,
                func.count(func.distinct(Exercise.id)),
            )
            .join(ExerciseAttempt, ExerciseAttempt.exercise_id == Exercise.id)
            .where(
                ExerciseAttempt.passed.is_(True),
                Exercise.knowledge_point_id != "",
            )
            .group_by(Exercise.knowledge_point_id)
        )
    ).all()
    passed = {kp_id: int(cnt) for kp_id, cnt in passed_rows}

    mastery: dict[str, str] = {}
    for kp_id, total in totals.items():
        p = passed.get(kp_id, 0)
        if total > 0 and p >= total:
            mastery[kp_id] = "已掌握"
        elif p > 0:
            mastery[kp_id] = "学习中"
        else:
            mastery[kp_id] = "未测"
    return mastery


async def build_learned_knowledge_index(
    db: AsyncSession, exclude_document_id: str | None = None
) -> str:
    """生成 L0「个人已学知识骨架目录」：课程 → 章节 → 知识点（掌握度）紧凑树。

    用途：统一 AI 助教系统提示常驻层——不携带任何讲义正文，只给标题级地图，
    让模型能跨课程类比学员已掌握的旧知识；细节靠 lookup_learned_section 工具按需翻取。
    exclude_document_id：当前正在阅读的章节（其内容已在 L2 现场视野中，目录里标记为当前位置即可）。
    """
    # 只收录已就绪课程与其已完成章节；草稿/生成中的半成品不进知识地图
    course_rows = (
        await db.execute(
            select(Course).where(Course.status == "ready").order_by(Course.created_at)
        )
    ).scalars()
    courses = list(course_rows)
    if not courses:
        return "（学员还没有已就绪的课程）"

    doc_rows = (
        await db.execute(
            select(Document)
            .where(
                Document.status == "done",
                Document.course_id.in_([c.id for c in courses]),
            )
            .order_by(Document.course_id, Document.chapter_index)
        )
    ).scalars()
    docs = list(doc_rows)

    kp_rows = (
        await db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.document_id.in_([d.id for d in docs])
            )
        )
    ).scalars()
    kps = list(kp_rows)
    mastery = await _kp_mastery_map(db)

    kps_by_doc: dict[str, list[KnowledgePoint]] = {}
    for kp in kps:
        kps_by_doc.setdefault(kp.document_id, []).append(kp)
    docs_by_course: dict[str, list[Document]] = {}
    for d in docs:
        docs_by_course.setdefault(d.course_id, []).append(d)

    lines: list[str] = []
    total_len = 0
    truncated = False
    for course in courses:
        course_docs = docs_by_course.get(course.id, [])
        scope_tag = f"［{course.scope}］" if getattr(course, "scope", None) else ""
        head = f"《{course.title}》{scope_tag}"
        lines.append(head)
        total_len += len(head) + 1
        for doc in course_docs:
            is_current = exclude_document_id and doc.id == exclude_document_id
            marker = " ←（当前正在学）" if is_current else ""
            doc_line = f"- 第{doc.chapter_index}章 {doc.title}{marker}："
            kp_list = kps_by_doc.get(doc.id, [])
            if not kp_list:
                doc_line += "（无拆解知识点）"
            else:
                parts = []
                for kp in kp_list:
                    m = mastery.get(kp.id)
                    parts.append(f"{kp.title}（{m}）" if m else kp.title)
                doc_line += "；".join(parts)
            if total_len + len(doc_line) > LEARNED_INDEX_MAX_CHARS:
                truncated = True
                break
            lines.append(doc_line)
            total_len += len(doc_line) + 1
        if truncated:
            break

    if truncated:
        lines.append("…（其余章节从略，需要时可用 lookup_learned_section 工具检索）")
    return "\n".join(lines)
