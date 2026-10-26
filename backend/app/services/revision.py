"""文档单段落手术式重写与核查纠偏服务（决策4）。"""
from __future__ import annotations

import logging
from typing import Literal
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Course, Document, Section
from app.services.docparser import parse_blocks
from app.services.generation.indexing import rebuild_sections
from app.services.llm import create_adapter_from_settings
from app.services.prompt import render_prompt
from app.services.sections_text import load_document_markdown

logger = logging.getLogger(__name__)


class SectionReviseOutput(BaseModel):
    verification_status: Literal["confirmed_error", "improved", "verified_correct"]
    explanation: str
    revised_markdown: str


async def review_section_revision(
    db: AsyncSession,
    document: Document,
    section: Section,
    instruction: str,
) -> tuple[str, SectionReviseOutput]:
    """使用 LLM 对单段落进行客观审校核查，返回 (原段落Markdown, 审校结果)。"""
    course = await db.get(Course, document.course_id)
    markdown = load_document_markdown(document)
    blocks = parse_blocks(markdown)

    if section.order_index >= len(blocks):
        raise ValueError("段落索引超出当前文档范围，请刷新后重试")

    target_block = blocks[section.order_index]
    original_raw = target_block.raw

    # 上下文：前后各取一块
    prev_raw = blocks[section.order_index - 1].raw if section.order_index > 0 else "（无前序内容，此为首段）"
    next_raw = blocks[section.order_index + 1].raw if section.order_index + 1 < len(blocks) else "（无后续内容，此为末段）"
    surrounding_context = f"【前序段落】\n{prev_raw}\n\n【后续段落】\n{next_raw}"

    prompt = render_prompt(
        "section_revise.md",
        COURSE_TITLE=course.title if course else "未命名课程",
        DOC_TITLE=document.title,
        SURROUNDING_CONTEXT=surrounding_context,
        TARGET_SECTION=original_raw,
        USER_INSTRUCTION=instruction,
    )

    adapter = await create_adapter_from_settings(db, scene="generation")
    result = await adapter.chat_json(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"请针对我的质疑与调整要求进行专业审校并输出修订方案：\n{instruction}"},
        ],
        schema=SectionReviseOutput,
    )
    return original_raw, result


async def apply_section_revision(
    db: AsyncSession,
    document: Document,
    section: Section,
    revised_markdown: str,
) -> str:
    """将修订后的 Markdown 手术式替换到文档文件中，并重建 Section 索引。返回更新后的完整正文。"""
    markdown = load_document_markdown(document)
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks = parse_blocks(markdown)

    if section.order_index >= len(blocks):
        raise ValueError("段落索引超出当前文档范围，请刷新后重试")

    target_block = blocks[section.order_index]
    revised_lines = revised_markdown.replace("\r\n", "\n").split("\n")
    new_lines = lines[: target_block.line_start] + revised_lines + lines[target_block.line_end :]
    new_markdown = "\n".join(new_lines)

    if not document.file_path:
        raise ValueError("文档未关联正文文件，无法应用修订")

    file_path = settings.data_dir / document.file_path
    file_path.write_text(new_markdown, encoding="utf-8")

    new_version = document.version + 1
    document.version = new_version

    await rebuild_sections(
        db,
        document=document,
        new_markdown=new_markdown,
        new_version=new_version,
        force_inherited={section.order_index: section.id},
    )
    await db.commit()
    logger.info("applied section revision to doc=%s sec=%s v=%d", document.id, section.id, new_version)
    return new_markdown
