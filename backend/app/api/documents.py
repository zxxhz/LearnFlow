import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Document, Section
from app.schemas.course import RegenerateRequest
from app.schemas.document import DocumentContentOut, DocumentOut, SectionOut
from app.services.generation import pipeline
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
