import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Annotation, Document, Section
from app.schemas.course import RegenerateRequest
from app.schemas.document import (
    CompareHighlightItem,
    DocumentContentOut,
    DocumentOut,
    HighlightComparisonOut,
    SectionOut,
)
from app.services.generation import pipeline
from app.services.generation.highlight import find_candidate_anchors
from app.services.sections_text import load_document_markdown

router = APIRouter(prefix="/documents", tags=["documents"])


async def _get_doc(db: AsyncSession, document_id: str) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.get("/{document_id}/content", response_model=DocumentContentOut)
async def content(document_id: str, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc(db, document_id)
    markdown = load_document_markdown(doc)
    sections = (
        await db.scalars(
            select(Section)
            .where(Section.document_id == document_id)
            .order_by(Section.order_index)
        )
    ).all()
    blocks = [
        SectionOut(
            id=s.id,
            order_index=s.order_index,
            block_type=s.block_type,
            heading_path=json.loads(s.heading_path) if s.heading_path else [],
        )
        for s in sections
    ]
    return DocumentContentOut(
        document=DocumentOut.model_validate(doc),
        markdown=markdown,
        blocks=blocks,
    )


@router.get("/{document_id}/compare-highlights", response_model=HighlightComparisonOut)
async def compare_highlights(document_id: str, db: AsyncSession = Depends(get_db)):
    """章末自主重点对照：提取 AI 推荐重点与用户当前手动划线进行对比。"""
    doc = await _get_doc(db, document_id)
    markdown = load_document_markdown(doc)
    sections = (
        await db.scalars(
            select(Section)
            .where(Section.document_id == document_id)
            .order_by(Section.order_index)
        )
    ).all()

    candidates_raw = find_candidate_anchors(sections, markdown)

    # 查出用户自己在本章的所有有效划线标注
    user_anns = (
        await db.scalars(
            select(Annotation).where(
                Annotation.document_id == document_id,
                Annotation.status == "active",
            )
        )
    ).all()

    candidates: list[CompareHighlightItem] = []
    for c in candidates_raw:
        # 重叠与匹配判定：同一 section 内有重叠或子串包含
        is_matched = False
        for u in user_anns:
            if u.section_id == c["section_id"]:
                c_start, c_end = c["start_offset"], c["end_offset"]
                u_start, u_end = u.start_offset, u.end_offset
                if max(c_start, u_start) < min(c_end, u_end) or c["exact"] in u.exact or u.exact in c["exact"]:
                    is_matched = True
                    break
        candidates.append(
            CompareHighlightItem(
                section_id=c["section_id"],
                exact=c["exact"],
                prefix=c["prefix"],
                suffix=c["suffix"],
                start_offset=c["start_offset"],
                end_offset=c["end_offset"],
                note=c["note"],
                color=c["color"],
                is_matched=is_matched,
            )
        )

    user_count = len(user_anns)
    ai_count = len(candidates)
    matched_count = sum(1 for c in candidates if c.is_matched)
    missed_count = ai_count - matched_count

    if user_count == 0:
        summary = f"你尚未在本章手动划线。AI 提炼出 {ai_count} 处核心概念与避坑要害，建议在阅读中自主标出重点，或点击下方采纳。"
    elif missed_count == 0:
        summary = f"太棒了！你标出的 {user_count} 处重点已完全覆盖 AI 识别的 {ai_count} 处核心要害！"
    else:
        summary = f"本章你标出了 {user_count} 处重点，与核心要害重合 {matched_count} 处；AI 建议额外关注 {missed_count} 处关键点。"

    return HighlightComparisonOut(
        user_highlight_count=user_count,
        ai_candidate_count=ai_count,
        matched_count=matched_count,
        missed_count=missed_count,
        summary=summary,
        candidates=candidates,
    )


@router.post("/{document_id}/regenerate")
async def regenerate(document_id: str, body: RegenerateRequest, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc(db, document_id)
    if doc.source == "imported":
        raise HTTPException(
            status_code=400,
            detail="导入的文档保留原文，不支持重新生成；如需 AI 重写，请新建课程后学习。",
        )
    try:
        await pipeline.queue_single_document(
            document_id, body.instruction, auto_highlight=body.auto_highlight
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@router.get("/{document_id}/knowledge-points")
async def knowledge_points(document_id: str, db: AsyncSession = Depends(get_db)):
    from app.models import KnowledgePoint
    from app.schemas.knowledge import KnowledgePointOut

    await _get_doc(db, document_id)
    kps = (
        await db.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.document_id == document_id)
            .order_by(KnowledgePoint.created_at)
        )
    ).all()
    return [KnowledgePointOut.model_validate(k).model_dump() for k in kps]
