from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Annotation, KnowledgePoint, ReviewCard
from app.schemas.review import (
    GradeRequest,
    QueueOut,
    ReviewCardCreate,
    ReviewCardOut,
    ReviewCardUpdate,
    ReviewStatsOut,
)
from app.services import review as review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/queue/today", response_model=QueueOut)
async def queue_today(db: AsyncSession = Depends(get_db)):
    cards, quota, due_count = await review_service.today_queue(db)
    return QueueOut(
        cards=[ReviewCardOut.model_validate(c) for c in cards],
        new_quota_remaining=quota,
        due_total=due_count,
    )


@router.post("/cards/{card_id}/grade", response_model=ReviewCardOut)
async def grade(card_id: str, body: GradeRequest, db: AsyncSession = Depends(get_db)):
    try:
        card = await review_service.grade_card(db, card_id, body.quality)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ReviewCardOut.model_validate(card)


@router.post("/cards", response_model=ReviewCardOut)
async def create_card(body: ReviewCardCreate, db: AsyncSession = Depends(get_db)):
    source_type = "manual"
    if body.knowledge_point_id:
        if await db.get(KnowledgePoint, body.knowledge_point_id) is None:
            raise HTTPException(status_code=404, detail="知识点不存在")
        source_type = "knowledge_point"
    elif body.annotation_id:
        if await db.get(Annotation, body.annotation_id) is None:
            raise HTTPException(status_code=404, detail="标注不存在")
        source_type = "annotation"
    card = ReviewCard(
        source_type=source_type,
        knowledge_point_id=body.knowledge_point_id,
        annotation_id=body.annotation_id,
        front=body.front,
        back=body.back,
    )
    db.add(card)
    await db.commit()
    return ReviewCardOut.model_validate(card)


@router.patch("/cards/{card_id}", response_model=ReviewCardOut)
async def update_card(card_id: str, body: ReviewCardUpdate, db: AsyncSession = Depends(get_db)):
    card = await db.get(ReviewCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="复习卡不存在")
    if body.front is not None:
        card.front = body.front
    if body.back is not None:
        card.back = body.back
    if body.suspended is not None:
        card.suspended = body.suspended
    await db.commit()
    return ReviewCardOut.model_validate(card)


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete

    from app.models import ReviewLog

    card = await db.get(ReviewCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="复习卡不存在")
    await db.execute(delete(ReviewLog).where(ReviewLog.card_id == card_id))
    await db.delete(card)
    await db.commit()
    return {"ok": True}


@router.get("/stats", response_model=ReviewStatsOut)
async def stats(db: AsyncSession = Depends(get_db)):
    data = await review_service.review_stats(db)
    data.pop("_now", None)
    return ReviewStatsOut(**data)


@router.get("/export.csv", response_class=Response)
async def export_anki_csv(db: AsyncSession = Depends(get_db)):
    """复习卡导出 Anki 兼容 CSV（front/back/tags，含未到期卡，不含挂起卡）。"""
    import csv
    import io

    cards = (
        await db.scalars(
            select(ReviewCard).where(ReviewCard.suspended == False).order_by(ReviewCard.created_at)  # noqa: E712
        )
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["front", "back", "tags"])
    for c in cards:
        writer.writerow([c.front.replace("\n", "<br>"), c.back.replace("\n", "<br>"), c.source_type])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="learnflow-review-cards.csv"'},
    )
