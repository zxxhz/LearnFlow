import json
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import (
    Course,
    Document,
    FeynmanSession,
    KnowledgePoint,
    Message,
    ReviewCard,
    ReviewLog,
)
from app.schemas.dashboard import DashboardSummary
from app.services.review import (
    get_preferences,
    local_date_of,
    local_today,
    parse_dt,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: AsyncSession = Depends(get_db)):
    courses = (
        await db.scalars(select(Course).where(Course.status != "archived").order_by(Course.updated_at.desc()))
    ).all()
    docs = (await db.scalars(select(Document))).all()

    course_items = []
    for c in courses:
        cdocs = [d for d in docs if d.course_id == c.id]
        course_items.append(
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "done_chapters": sum(1 for d in cdocs if d.status == "done"),
                "total_chapters": len(cdocs),
                "updated_at": c.updated_at,
            }
        )

    # 今日概览
    from app.models.base import utcnow_iso

    now_dt = parse_dt(utcnow_iso())
    prefs = await get_preferences(db)
    daily = int(prefs.get("daily_new_cards", 20))
    cards = (await db.scalars(select(ReviewCard))).all()
    today = local_today()
    due_count = sum(
        1
        for c in cards
        if not c.suspended and c.state != "new" and (parse_dt(c.due_at) or now_dt) <= now_dt
    )
    introduced_today = sum(
        1
        for c in cards
        if c.introduced_at and local_date_of(parse_dt(c.introduced_at) or now_dt) == today
    )
    feynman_active = len(
        (await db.scalars(select(FeynmanSession).where(FeynmanSession.status != "done"))).all()
    )

    # 薄弱知识点：遗忘次数 + 费曼漏洞数
    kps = (await db.scalars(select(KnowledgePoint))).all()
    sessions = (await db.scalars(select(FeynmanSession))).all()
    gap_by_kp: dict[str, int] = {}
    for s in sessions:
        if not s.evaluation:
            continue
        try:
            gaps = json.loads(s.evaluation).get("gaps", [])
        except json.JSONDecodeError:
            continue
        gap_by_kp[s.knowledge_point_id] = gap_by_kp.get(s.knowledge_point_id, 0) + len(gaps)
    weak = []
    for kp in kps:
        lapses = sum(c.lapses for c in cards if c.knowledge_point_id == kp.id)
        gap_count = gap_by_kp.get(kp.id, 0)
        if lapses == 0 and gap_count == 0:
            continue
        weak.append(
            {
                "knowledge_point_id": kp.id,
                "title": kp.title,
                "document_id": kp.document_id,
                "lapses": lapses,
                "gap_count": gap_count,
            }
        )
    weak.sort(key=lambda w: w["lapses"] + w["gap_count"] * 2, reverse=True)

    # 热力图：复习日志 + 用户消息，按本地日期聚合
    logs = (await db.scalars(select(ReviewLog))).all()
    user_msgs = (
        await db.scalars(select(Message).where(Message.role == "user"))
    ).all()
    counts: dict = {}
    for l in logs:
        d = parse_dt(l.reviewed_at)
        if d:
            ld = local_date_of(d)
            counts[ld] = counts.get(ld, 0) + 1
    for m in user_msgs:
        d = parse_dt(m.created_at)
        if d:
            ld = local_date_of(d)
            counts[ld] = counts.get(ld, 0) + 1
    heatmap = []
    for i in range(83, -1, -1):
        day = today - timedelta(days=i)
        heatmap.append({"date": day.isoformat(), "count": counts.get(day, 0)})

    return DashboardSummary(
        courses=course_items,
        today={"due_reviews": due_count + max(0, daily - introduced_today), "feynman_active": feynman_active},
        weak_points=weak[:10],
        heatmap=heatmap,
    )
