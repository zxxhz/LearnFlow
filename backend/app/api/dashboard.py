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
    KnowledgePoint,
    LLMUsage,
    Message,
    StudyDay,
)
from app.models.base import utcnow_iso
from app.schemas.dashboard import (
    DashboardSummary,
    LLMUsageSummary,
    SceneUsage,
    StudyDayOut,
    WeakPoint,
)
from app.services.prefs import local_today, parse_dt

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _exercise_mastery(pass_ratio: float | None) -> int:
    """掌握度：练习通过率单信号（0..1 → 0-100），无信号回落 50。"""
    if pass_ratio is None:
        return 50
    return round(max(0.0, min(1.0, pass_ratio)) * 100)


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

    # 薄弱知识点：闯关练习通过率（最近一次作答）+ 失败题数
    kps = (await db.scalars(select(KnowledgePoint))).all()

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

    weak = []
    for kp in kps:
        oks = [o for o in attempt_total.get(kp.id, []) if o is not None]
        ex_fail = fail_by_kp.get(kp.id, 0)
        # 完全没有练习信号的知识点不进薄弱榜（无法判断强弱）
        if not oks:
            continue
        pass_ratio = sum(1 for o in oks if o) / len(oks)
        mastery = _exercise_mastery(pass_ratio)
        if mastery >= 85 and ex_fail == 0:
            continue
        weak.append(
            WeakPoint(
                knowledge_point_id=kp.id,
                title=kp.title,
                document_id=kp.document_id,
                exercise_fail=ex_fail,
                mastery=mastery,
            )
        )
    weak.sort(key=lambda w: (w.mastery, -w.exercise_fail))

    # 热力图：用户消息（划线提问等），按本地日期聚合
    today = local_today()
    user_msgs = (
        await db.scalars(select(Message).where(Message.role == "user"))
    ).all()
    counts: dict = {}
    for m in user_msgs:
        d = parse_dt(m.created_at)
        if d:
            ld = d.astimezone().date()
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
        weak_points=weak[:10],
        heatmap=heatmap,
        study_days=study_days,
        study_minutes_7d=study_minutes_7d,
        llm_usage=llm_usage,
    )
