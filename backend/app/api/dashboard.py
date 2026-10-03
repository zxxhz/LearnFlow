import json
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import (
    Course,
    Document,
    Exercise,
    ExerciseAttempt,
    FeynmanSession,
    KnowledgePoint,
    LLMUsage,
    Message,
    ReviewCard,
    ReviewLog,
    StudyDay,
)
from app.schemas.dashboard import (
    DashboardSummary,
    LLMUsageSummary,
    RetentionBucket,
    SceneUsage,
    StudyDayOut,
    WeakPoint,
)
from app.services.review import (
    get_preferences,
    local_date_of,
    local_today,
    parse_dt,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

RETENTION_BUCKETS = [(1, "1天"), (3, "3天"), (7, "7天"), (14, "14天"), (21, "21天"), (30, "30天+")]


def _bucket_of(interval_days: float) -> int | None:
    for hi, _label in RETENTION_BUCKETS:
        if interval_days <= hi:
            return hi
    return 30


def _card_mastery(cards: list[ReviewCard]) -> float | None:
    """复习信号：活卡按「当前间隔 / 21 天」取均值（0..1）。"""
    live = [c for c in cards if not c.suspended and c.state != "new"]
    if not live:
        return None
    return sum(min(1.0, max(0.0, c.interval_days / 21.0)) for c in live) / len(live)


def _feynman_mastery(sessions: list[FeynmanSession]) -> float | None:
    """费曼信号：历次评价分数均值（0..1）。"""
    scores: list[float] = []
    for s in sessions:
        if not s.evaluation:
            continue
        try:
            sc = json.loads(s.evaluation).get("score")
        except json.JSONDecodeError:
            continue
        if isinstance(sc, (int, float)):
            scores.append(max(0.0, min(100.0, float(sc))) / 100.0)
    return sum(scores) / len(scores) if scores else None


def _mastery(review_part: float | None, feynman_part: float | None, exercise_part: float | None) -> int:
    """三信号加权合成（复习 .4 / 费曼 .3 / 练习 .3），缺失维度按其余归一；全缺 → 50。"""
    parts = [(review_part, 0.4), (feynman_part, 0.3), (exercise_part, 0.3)]
    avail = [(v, w) for v, w in parts if v is not None]
    if not avail:
        return 50
    wsum = sum(w for _, w in avail)
    return round(sum(v * w for v, w in avail) / wsum * 100)


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

    # 薄弱知识点 + 掌握度：复习遗忘 + 费曼漏洞 + 练习未通过 三信号
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

    # 每题最近一次作答（窗口函数），聚合出练习通过率与失败题数
    rn = func.row_number().over(
        partition_by=ExerciseAttempt.exercise_id, order_by=ExerciseAttempt.created_at.desc()
    ).label("rn")
    sq = (
        select(ExerciseAttempt.exercise_id.label("eid"), ExerciseAttempt.passed.label("ok"), rn)
        .subquery()
    )
    latest_rows = (await db.execute(select(sq.c.eid, sq.c.ok).where(sq.c.rn == 1))).all()
    latest_ok: dict[str, bool | None] = {r.eid: r.ok for r in latest_rows}
    exercises = (await db.scalars(select(Exercise))).all()
    fail_by_kp: dict[str, int] = {}
    attempt_total: dict[str, list[bool | None]] = {}
    for e in exercises:
        ok = latest_ok.get(e.id)
        attempt_total.setdefault(e.knowledge_point_id, []).append(ok)
        if ok is False:
            fail_by_kp[e.knowledge_point_id] = fail_by_kp.get(e.knowledge_point_id, 0) + 1

    cards_by_kp: dict[str, list[ReviewCard]] = {}
    for c in cards:
        if c.knowledge_point_id:
            cards_by_kp.setdefault(c.knowledge_point_id, []).append(c)
    sessions_by_kp: dict[str, list[FeynmanSession]] = {}
    for s in sessions:
        sessions_by_kp.setdefault(s.knowledge_point_id, []).append(s)

    weak = []
    for kp in kps:
        kp_cards = cards_by_kp.get(kp.id, [])
        kp_sessions = sessions_by_kp.get(kp.id, [])
        oks = [o for o in attempt_total.get(kp.id, []) if o is not None]
        # 完全没有学习信号的知识点不进薄弱榜（无法判断强弱）
        if not kp_cards and not kp_sessions and not oks:
            continue
        lapses = sum(c.lapses for c in kp_cards)
        gap_count = gap_by_kp.get(kp.id, 0)
        ex_fail = fail_by_kp.get(kp.id, 0)
        exercise_part = (sum(1 for o in oks if o) / len(oks)) if oks else None
        mastery = _mastery(
            _card_mastery(kp_cards),
            _feynman_mastery(kp_sessions),
            exercise_part,
        )
        if mastery >= 85 and lapses == 0 and gap_count == 0 and ex_fail == 0:
            continue
        weak.append(
            WeakPoint(
                knowledge_point_id=kp.id,
                title=kp.title,
                document_id=kp.document_id,
                lapses=lapses,
                gap_count=gap_count,
                exercise_fail=ex_fail,
                mastery=mastery,
            )
        )
    weak.sort(key=lambda w: (w.mastery, -(w.lapses + w.gap_count * 2 + w.exercise_fail)))

    # 遗忘曲线：quality≥3 的复习之后，紧邻的下一次 <3 记遗忘，按间隔分桶
    logs = (await db.scalars(select(ReviewLog))).all()
    by_card: dict[str, list[ReviewLog]] = {}
    for l in logs:
        by_card.setdefault(l.card_id, []).append(l)
    bucket_stat: dict[int, list[int]] = {}
    for cl in by_card.values():
        cl.sort(key=lambda x: x.reviewed_at)
        for i, l in enumerate(cl[:-1]):
            if l.quality < 3:
                continue
            b = _bucket_of(l.interval_days)
            if b is None:
                continue
            stat = bucket_stat.setdefault(b, [0, 0])
            stat[0] += 1
            if cl[i + 1].quality >= 3:
                stat[1] += 1
    retention = [
        RetentionBucket(label=label, total=bucket_stat[b][0], passed=bucket_stat[b][1])
        for b, label in RETENTION_BUCKETS
        if b in bucket_stat and bucket_stat[b][0] >= 3
    ]

    # 热力图：复习日志 + 用户消息，按本地日期聚合
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

    # 学习时长：按本地日聚合的阅读分钟数
    study_rows = (await db.scalars(select(StudyDay))).all()
    seconds_by_day = {r.day: r.seconds for r in study_rows}
    study_days = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        study_days.append(
            StudyDayOut(date=day.isoformat(), minutes=seconds_by_day.get(day.isoformat(), 0) // 60)
        )
    study_minutes_7d = sum(
        seconds_by_day.get((today - timedelta(days=i)).isoformat(), 0) for i in range(7)
    ) // 60

    # LLM Token 用量（近 30 天）
    since = (parse_dt(utcnow_iso()) - timedelta(days=30)).isoformat()
    usage_rows = (
        await db.scalars(select(LLMUsage).where(LLMUsage.created_at >= since))
    ).all()
    llm_usage = None
    if usage_rows:
        by_scene: dict[str, list[int]] = {}
        for u in usage_rows:
            stat = by_scene.setdefault(u.scene, [0, 0])
            stat[0] += 1
            stat[1] += u.prompt_tokens + u.completion_tokens
        llm_usage = LLMUsageSummary(
            calls=len(usage_rows),
            prompt_tokens=sum(u.prompt_tokens for u in usage_rows),
            completion_tokens=sum(u.completion_tokens for u in usage_rows),
            by_scene=[
                SceneUsage(scene=scene, calls=calls, tokens=tokens)
                for scene, (calls, tokens) in sorted(by_scene.items())
            ],
        )

    return DashboardSummary(
        courses=course_items,
        today={"due_reviews": due_count + max(0, daily - introduced_today), "feynman_active": feynman_active},
        weak_points=weak[:10],
        heatmap=heatmap,
        retention=retention,
        study_days=study_days,
        study_minutes_7d=study_minutes_7d,
        llm_usage=llm_usage,
    )
