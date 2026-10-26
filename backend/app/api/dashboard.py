from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import (
    BankAttempt,
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
    # 章节进度按 course_id 聚合（SQL COUNT/GROUP BY 替代把全部文档拉入内存再过滤）
    total_rows = (
        await db.execute(
            select(Document.course_id, func.count().label("total")).group_by(Document.course_id)
        )
    ).all()
    doc_totals = {r.course_id: int(r.total) for r in total_rows}

    done_rows = (
        await db.execute(
            select(Document.course_id, func.count().label("done"))
            .where(Document.status == "done")
            .group_by(Document.course_id)
        )
    ).all()
    doc_done = {r.course_id: int(r.done) for r in done_rows}

    courses = (
        await db.scalars(select(Course).where(Course.status != "archived").order_by(Course.updated_at.desc()))
    ).all()
    course_items = []
    for c in courses:
        course_items.append(
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "done_chapters": doc_done.get(c.id, 0),
                "total_chapters": doc_totals.get(c.id, 0),
                "updated_at": c.updated_at,
            }
        )

    # 薄弱知识点：闯关练习通过率（最近一次作答）+ 失败题数，全部在 SQL 内聚合：
    # 最近一次作答窗口函数 → outer join 练习 → 按 kp 分组统计有作答数/通过数/失败数
    rn = func.row_number().over(
        partition_by=ExerciseAttempt.exercise_id, order_by=ExerciseAttempt.created_at.desc()
    ).label("rn")
    ranked = (
        select(ExerciseAttempt.exercise_id.label("eid"), ExerciseAttempt.passed.label("ok"), rn)
        .subquery()
    )
    latest = (
        select(ranked.c.eid, ranked.c.ok).where(ranked.c.rn == 1).subquery().alias("latest")
    )
    kp_stats_rows = (
        await db.execute(
            select(
                Exercise.knowledge_point_id.label("kpid"),
                func.sum(case((latest.c.eid.isnot(None), 1), else_=0)).label("answered_n"),
                func.sum(cast(latest.c.ok, Integer)).label("passed_n"),
                func.sum(case((latest.c.ok.is_(False), 1), else_=0)).label("failed_n"),
            )
            .outerjoin(latest, latest.c.eid == Exercise.id)
            .group_by(Exercise.knowledge_point_id)
        )
    ).all()
    kp_answered = {r.kpid: int(r.answered_n or 0) for r in kp_stats_rows}
    kp_passed = {r.kpid: int(r.passed_n or 0) for r in kp_stats_rows}
    kp_failed = {r.kpid: int(r.failed_n or 0) for r in kp_stats_rows}

    kps = (await db.scalars(select(KnowledgePoint))).all()
    weak = []
    for kp in kps:
        answered_n = kp_answered.get(kp.id, 0)
        failed_n = kp_failed.get(kp.id, 0)
        # 完全没有练习作答信号的知识点不进薄弱榜（无法判断强弱）
        if answered_n == 0:
            continue
        pass_ratio = kp_passed.get(kp.id, 0) / answered_n
        mastery = _exercise_mastery(pass_ratio)
        if mastery >= 85 and failed_n == 0:
            continue
        weak.append(
            WeakPoint(
                knowledge_point_id=kp.id,
                title=kp.title,
                document_id=kp.document_id,
                exercise_fail=failed_n,
                mastery=mastery,
            )
        )
    weak.sort(key=lambda w: (w.mastery, -w.exercise_fail))

    # 热力图：学习动作 = 用户提问（划线/课程问答）+ 闯关作答 + 题库作答，
    # 与 PRD §5.6「阅读、练习作答、对话研讨」口径一致（此前只数提问，纯阅读/刷题日是 0 格）
    today = local_today()
    counts: dict = {}

    def _acc(rows) -> None:
        for (created_at,) in rows:
            d = parse_dt(created_at)
            if d:
                ld = d.astimezone().date()
                counts[ld] = counts.get(ld, 0) + 1

    _acc((await db.execute(select(Message.created_at).where(Message.role == "user"))).all())
    _acc((await db.execute(select(ExerciseAttempt.created_at))).all())
    _acc((await db.execute(select(BankAttempt.created_at))).all())
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

    # LLM Token 用量（近 30 天，SQL GROUP BY 聚合）
    since = (parse_dt(utcnow_iso()) - timedelta(days=30)).isoformat()
    scene_rows = (
        await db.execute(
            select(
                LLMUsage.scene,
                func.count().label("calls"),
                func.sum(LLMUsage.prompt_tokens + LLMUsage.completion_tokens).label("tokens"),
            )
            .where(LLMUsage.created_at >= since)
            .group_by(LLMUsage.scene)
            .order_by(LLMUsage.scene)
        )
    ).all()
    llm_usage = None
    if scene_rows:
        totals = (
            await db.execute(
                select(func.sum(LLMUsage.prompt_tokens), func.sum(LLMUsage.completion_tokens)).where(
                    LLMUsage.created_at >= since
                )
            )
        ).one()
        llm_usage = LLMUsageSummary(
            calls=sum(int(r.calls) for r in scene_rows),
            prompt_tokens=int(totals[0] or 0),
            completion_tokens=int(totals[1] or 0),
            by_scene=[
                SceneUsage(scene=r.scene, calls=int(r.calls), tokens=int(r.tokens or 0))
                for r in scene_rows
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
