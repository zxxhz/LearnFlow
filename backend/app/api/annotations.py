from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Annotation, Conversation, Document, Message, Section
from app.models.base import utcnow_iso
from app.schemas.annotation import (
    AnnotationCreatedOut,
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
)

router = APIRouter(tags=["annotations"])


async def _get_annotation(db: AsyncSession, annotation_id: str) -> Annotation:
    ann = await db.get(Annotation, annotation_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="标注不存在")
    return ann


@router.get("/documents/{document_id}/annotations", response_model=list[AnnotationOut])
async def list_annotations(document_id: str, db: AsyncSession = Depends(get_db)):
    anns = (
        await db.scalars(
            select(Annotation)
            .where(Annotation.document_id == document_id)
            .order_by(Annotation.created_at)
        )
    ).all()
    return [AnnotationOut.model_validate(a) for a in anns]


@router.post("/documents/{document_id}/annotations", response_model=AnnotationCreatedOut)
async def create_annotation(
    document_id: str, body: AnnotationCreate, db: AsyncSession = Depends(get_db)
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not body.exact.strip():
        raise HTTPException(status_code=400, detail="划线内容为空")
    # section 必须属于该文档当前索引（防前端过期，PRD §9.2）
    sec = (
        await db.scalars(
            select(Section).where(
                Section.document_id == document_id, Section.id == body.section_id
            )
        )
    ).first()
    if sec is None:
        raise HTTPException(status_code=400, detail="划线位置无效，请刷新页面后重试")

    ann = Annotation(
        document_id=document_id,
        section_id=body.section_id,
        version=doc.version,
        exact=body.exact,
        prefix=body.prefix,
        suffix=body.suffix,
        start_offset=body.start_offset,
        end_offset=body.end_offset,
        color=body.color,
        status="active",
    )
    db.add(ann)
    await db.flush()
    conv = Conversation(kind="annotation", annotation_id=ann.id)
    db.add(conv)
    ann.updated_at = utcnow_iso()
    await db.commit()
    return AnnotationCreatedOut(
        annotation=AnnotationOut.model_validate(ann), conversation_id=conv.id
    )


@router.patch("/annotations/{annotation_id}", response_model=AnnotationOut)
async def update_annotation(
    annotation_id: str, body: AnnotationUpdate, db: AsyncSession = Depends(get_db)
):
    ann = await _get_annotation(db, annotation_id)
    if body.color is not None:
        ann.color = body.color
    if body.note is not None:
        ann.note = body.note
    if body.status is not None:
        ann.status = body.status
    if body.anchor is not None:
        # 重新挂载（PRD §9.3）：原位更新五元组，保留对话与创建时间
        ann.section_id = body.anchor.section_id
        ann.exact = body.anchor.exact
        ann.prefix = body.anchor.prefix
        ann.suffix = body.anchor.suffix
        ann.start_offset = body.anchor.start_offset
        ann.end_offset = body.anchor.end_offset
        ann.status = "active"
    ann.updated_at = utcnow_iso()
    await db.commit()
    return AnnotationOut.model_validate(ann)


@router.get("/annotations/{annotation_id}/conversation")
async def annotation_conversation(annotation_id: str, db: AsyncSession = Depends(get_db)):
    ann = await _get_annotation(db, annotation_id)
    conv = (
        await db.scalars(
            select(Conversation).where(Conversation.annotation_id == annotation_id)
        )
    ).first()
    if conv is None:
        conv = Conversation(kind="annotation", annotation_id=ann.id)
        db.add(conv)
        await db.commit()
    return {"conversation_id": conv.id}


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, db: AsyncSession = Depends(get_db)):
    ann = await _get_annotation(db, annotation_id)
    convs = (
        await db.scalars(
            select(Conversation).where(Conversation.annotation_id == annotation_id)
        )
    ).all()
    conv_ids = [c.id for c in convs]
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
    await db.delete(ann)
    await db.commit()
    return {"ok": True}
