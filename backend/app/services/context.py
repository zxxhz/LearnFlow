"""划线答疑的上下文组装（PRD FR-3.2：携带划线原文 + 所在章节 + 前后章摘要）。"""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Annotation, Conversation, Course, Document, Message, Section
from app.services.prompt import render_prompt
from app.services.sections_text import get_section_text


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

    system = render_prompt(
        "annotation_qa",
        COURSE_TITLE=course.title,
        DOC_TITLE=document.title + (f"（位于：{heading}）" if heading else ""),
        DOC_SUMMARY=document.summary or "（无摘要）",
        NAV_SUMMARIES="\n".join(neighbors) or "（无）",
        EXACT=ann.exact,
        SECTION_TEXT=section_text or "（原文缺失，请基于划线内容回答）",
    )
    history = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    ).all()
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    return messages
