"""SM-2 调度器（PRD §10.1）。四按钮映射：忘了=1 / 模糊=3 / 记得=4 / 轻松=5。"""
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, ReviewCard, ReviewLog
from app.models.base import utcnow_iso

RELEARN_MINUTES = 10  # 遗忘后当天重现的间隔


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_today() -> date:
    return datetime.now().astimezone().date()


def local_date_of(dt: datetime) -> date:
    return dt.astimezone().date()


def apply_sm2(card: ReviewCard, q: int, now: datetime | None = None) -> None:
    """纯逻辑（便于测试）：按 SM-2 更新卡片调度字段，不落库。"""
    now = now or datetime.now(timezone.utc)
    card.easiness_factor = max(
        1.3, card.easiness_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    )
    if q >= 3:
        card.repetitions += 1
        if card.repetitions == 1:
            interval = 1.0
        elif card.repetitions == 2:
            interval = 6.0
        else:
            interval = max(1.0, round(card.interval_days * card.easiness_factor))
        card.interval_days = float(interval)
        card.state = "review"
        card.due_at = (now + timedelta(days=interval)).isoformat()
    else:
        card.lapses += 1
        card.repetitions = 0
        card.interval_days = RELEARN_MINUTES / 1440.0
        card.due_at = (now + timedelta(minutes=RELEARN_MINUTES)).isoformat()
        card.state = "learning" if card.state in ("new", "learning") else "relearning"


async def get_preferences(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, "local")
    return json.loads(row.preferences) if row and row.preferences else {}


async def today_queue(db: AsyncSession) -> tuple[list[ReviewCard], int, int]:
    """返回（今日队列, 新卡剩余配额, 到期卡数）。到期卡在前，新卡在后（PRD FR-5.2）。"""
    now = datetime.now(timezone.utc)
    due_all = (
        await db.scalars(
            select(ReviewCard)
            .where(ReviewCard.suspended == False, ReviewCard.state != "new")  # noqa: E712
            .order_by(ReviewCard.due_at)
        )
    ).all()
    due = [c for c in due_all if (parse_dt(c.due_at) or now) <= now]

    daily = int((await get_preferences(db)).get("daily_new_cards", 20))
    today = local_today()
    introduced = (
        await db.scalars(select(ReviewCard).where(ReviewCard.introduced_at.is_not(None)))
    ).all()
    introduced_today = sum(
        1
        for c in introduced
        if (parse_dt(c.introduced_at) is not None and local_date_of(parse_dt(c.introduced_at)) == today)
    )
    quota = max(0, daily - introduced_today)

    news = (
        await db.scalars(
            select(ReviewCard)
            .where(ReviewCard.suspended == False, ReviewCard.state == "new")  # noqa: E712
            .order_by(ReviewCard.created_at)
        )
    ).all()
    return list(due) + list(news[:quota]), quota, len(due)


async def grade_card(db: AsyncSession, card_id: str, q: int) -> ReviewCard:
    card = await db.get(ReviewCard, card_id)
    if card is None:
        raise LookupError("复习卡不存在")
    now = datetime.now(timezone.utc)
    state_before = card.state
    if card.introduced_at is None:
        card.introduced_at = now.isoformat()
    apply_sm2(card, q, now)
    db.add(
        ReviewLog(
            card_id=card.id,
            reviewed_at=now.isoformat(),
            quality=q,
            interval_days=card.interval_days,
            ease_factor=card.easiness_factor,
            state_before=state_before,
            state_after=card.state,
        )
    )
    card.last_reviewed_at = now.isoformat()
    await db.commit()
    return card


async def review_stats(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    today = local_today()

    logs = (await db.scalars(select(ReviewLog))).all()
    log_dates = {local_date_of(parse_dt(l.reviewed_at)) for l in logs if parse_dt(l.reviewed_at)}
    today_reviewed = sum(1 for l in logs if parse_dt(l.reviewed_at) and local_date_of(parse_dt(l.reviewed_at)) == today)

    streak = 0
    cursor = today
    if cursor not in log_dates:
        cursor = cursor - timedelta(days=1)
    while cursor in log_dates:
        streak += 1
        cursor = cursor - timedelta(days=1)

    _, quota_remaining, due_count = await today_queue(db)
    total_cards = len((await db.scalars(select(ReviewCard.id))).all())

    future = (await db.scalars(select(ReviewCard))).all()
    next7: dict[date, int] = {}
    for c in future:
        if c.suspended or c.state == "new":
            continue
        d = parse_dt(c.due_at)
        if d is None:
            continue
        ld = local_date_of(d)
        delta = (ld - today).days
        if 0 <= delta <= 6:
            next7[ld] = next7.get(ld, 0) + 1
    due_next_7_days = [
        {"date": (today + timedelta(days=i)).isoformat(), "count": next7.get(today + timedelta(days=i), 0)}
        for i in range(7)
    ]
    return {
        "today_reviewed": today_reviewed,
        "due_remaining": due_count + quota_remaining,
        "streak_days": streak,
        "total_cards": total_cards,
        "total_reviews": len(logs),
        "due_next_7_days": due_next_7_days,
        "_now": utcnow_iso(),
    }
