"""学习服务：阅读心跳打点与学习者认知画像管理。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Annotation, Course, Document, Exercise, StudyDay
from app.models.bank import BankAttempt
from app.models.base import utcnow_iso
from app.models.study import LearnerMisconception, LearnerProfile
from app.services.prefs import local_today
from app.services.profile import (
    DEFAULT_PROFILE_ID,
    get_active_misconceptions,
    get_or_create_profile,
)

router = APIRouter(prefix="/study", tags=["study"])


class StudyPing(BaseModel):
    seconds: int

    @field_validator("seconds")
    @classmethod
    def _clamp(cls, v: int) -> int:
        # 心跳间隔上限 120s：前端每 30s 一跳，超限视为异常丢弃
        if v <= 0 or v > 120:
            raise ValueError("seconds 须在 1~120 之间")
        return int(v)


@router.post("/ping")
async def ping(body: StudyPing, db: AsyncSession = Depends(get_db)):
    day = local_today().isoformat()
    # 原子累加：读-改-写在两标签页并发心跳时会互相覆盖丢时长，
    # UPDATE ... seconds = seconds + :s 由 SQLite 在同事务内完成，无丢失更新
    from sqlalchemy import update as sa_update
    from sqlalchemy.exc import IntegrityError

    row = await db.get(StudyDay, day)
    if row is None:
        row = StudyDay(day=day, seconds=body.seconds, updated_at=utcnow_iso())
        db.add(row)
        try:
            await db.commit()
            return {"ok": True, "day": day, "seconds": body.seconds}
        except IntegrityError:
            # 跨日第一跳并发插入竞态：另一请求已建行，回滚后走原子累加
            await db.rollback()
    await db.execute(
        sa_update(StudyDay)
        .where(StudyDay.day == day)
        .values(seconds=StudyDay.seconds + body.seconds, updated_at=utcnow_iso())
    )
    await db.commit()
    fresh = await db.get(StudyDay, day)
    return {"ok": True, "day": day, "seconds": fresh.seconds if fresh else body.seconds}


# ---------------- 首页「今天」学习行动中枢 API ----------------


class LastReadChapter(BaseModel):
    course_id: str
    course_title: str
    document_id: str
    chapter_index: int
    chapter_title: str


class HardBoneItem(BaseModel):
    id: str
    title: str
    document_id: str
    kind: str


class ActiveMisconceptionItem(BaseModel):
    id: str
    topic: str
    tag: str | None = None


class TodayStudyHubOut(BaseModel):
    last_read: LastReadChapter | None = None
    hard_bones: list[HardBoneItem] = []
    active_misconceptions: list[ActiveMisconceptionItem] = []
    bank_wrong_count: int = 0
    today_read_seconds: int = 0


@router.get("/today", response_model=TodayStudyHubOut)
async def get_today_hub(db: AsyncSession = Depends(get_db)):
    """首页「今天」学习行动中枢数据聚合（§8）。"""
    day = local_today().isoformat()
    today_row = await db.get(StudyDay, day)
    today_seconds = today_row.seconds if today_row else 0

    # 1. 最近阅读课程与章节
    last_read: LastReadChapter | None = None
    last_ann = (
        await db.scalars(
            select(Annotation).order_by(Annotation.updated_at.desc()).limit(1)
        )
    ).first()
    target_doc_id = last_ann.document_id if last_ann else None

    if not target_doc_id:
        last_done_doc = (
            await db.scalars(
                select(Document).where(Document.status == "done").order_by(Document.updated_at.desc()).limit(1)
            )
        ).first()
        target_doc_id = last_done_doc.id if last_done_doc else None

    if target_doc_id:
        doc = await db.get(Document, target_doc_id)
        if doc:
            course = await db.get(Course, doc.course_id)
            if course:
                last_read = LastReadChapter(
                    course_id=course.id,
                    course_title=course.title,
                    document_id=doc.id,
                    chapter_index=doc.chapter_index,
                    chapter_title=doc.title,
                )

    # 2. 待攻克硬骨头关卡
    hard_bones_rows = (
        await db.scalars(
            select(Exercise).where(Exercise.is_hard_bone.is_(True)).limit(5)
        )
    ).all()
    hard_bones = [
        HardBoneItem(id=e.id, title=e.title, document_id=e.document_id, kind=e.kind)
        for e in hard_bones_rows
    ]

    # 3. 待攻坚活跃认知盲区
    misconceptions = await get_active_misconceptions(db, limit=5)
    active_misconceptions = [
        ActiveMisconceptionItem(id=m.id, topic=m.topic, tag=m.tag)
        for m in misconceptions
    ]

    # 4. 题库待清零错题总数
    rn = func.row_number().over(
        partition_by=BankAttempt.question_id, order_by=BankAttempt.created_at.desc()
    ).label("rn")
    sq = (
        select(
            BankAttempt.question_id.label("qid"),
            BankAttempt.passed.label("ok"),
            BankAttempt.is_doubtful.label("is_doubtful"),
            rn,
        )
        .where(BankAttempt.is_revoked.is_(False))
        .subquery()
    )
    latest_attempts = select(sq.c.qid, sq.c.ok, sq.c.is_doubtful).where(sq.c.rn == 1).subquery()
    bank_wrong_count = (
        await db.scalar(
            select(func.count(latest_attempts.c.qid)).where(
                or_(latest_attempts.c.ok.is_(False), latest_attempts.c.is_doubtful.is_(True))
            )
        )
    ) or 0

    return TodayStudyHubOut(
        last_read=last_read,
        hard_bones=hard_bones,
        active_misconceptions=active_misconceptions,
        bank_wrong_count=bank_wrong_count,
        today_read_seconds=today_seconds,
    )


# ---------------- 学习者画像相关 API ----------------


class MisconceptionOut(BaseModel):
    id: str
    topic: str
    tag: str
    evidence: str
    created_at: str
    scope: str = "general"
    source_type: str = ""
    source_id: str = ""
    # 证据溯源：人类可读出处描述 + 前端跳转路由（取不到留空）
    source_label: str = ""
    source_href: str = ""


async def _misconception_outs(db: AsyncSession, misconceptions) -> list[MisconceptionOut]:
    """盲区出参装配：附带学科域与证据出处（练习/题库/划线对话的回溯信息）。"""
    outs: list[MisconceptionOut] = []
    for m in misconceptions:
        label, href = "", ""
        try:
            if m.source_type == "exercise" and m.source_id:
                from app.models import Document, Exercise

                ex = await db.get(Exercise, m.source_id)
                if ex is not None:
                    label = f"闯关练习：{ex.title[:40]}"
                    doc = await db.get(Document, ex.document_id) if ex.document_id else None
                    if doc is not None:
                        href = f"/courses/{doc.course_id}"
            elif m.source_type == "bank_question" and m.source_id:
                from app.models.bank import BankQuestion

                bq = await db.get(BankQuestion, m.source_id)
                if bq is not None:
                    label = f"题库题目：{bq.title[:40]}"
                    href = f"/bank/{bq.bank_id}"
            elif m.source_type == "conversation" and m.source_id:
                from app.models import Annotation, Conversation

                conv = await db.get(Conversation, m.source_id)
                if conv is not None:
                    label = "划线问答"
                    if conv.annotation_id:
                        ann = await db.get(Annotation, conv.annotation_id)
                        if ann is not None:
                            label = f"划线问答：{ann.exact[:40]}"
                            href = f"/read/{ann.document_id}"
        except Exception:  # noqa: BLE001  溯源信息缺失不阻断画像读取
            label, href = "", ""
        outs.append(
            MisconceptionOut(
                id=m.id,
                topic=m.topic,
                tag=m.tag,
                evidence=m.evidence or "",
                created_at=m.created_at,
                scope=m.scope or "general",
                source_type=m.source_type or "",
                source_id=m.source_id or "",
                source_label=label,
                source_href=href,
            )
        )
    return outs


class LearnerProfileOut(BaseModel):
    id: str
    background_summary: str
    socratic_mode: bool
    updated_at: str
    misconceptions: list[MisconceptionOut]


class UpdateProfileIn(BaseModel):
    background_summary: str | None = None
    socratic_mode: bool | None = None


@router.get("/profile", response_model=LearnerProfileOut)
async def get_profile(db: AsyncSession = Depends(get_db)):
    """获取当前学习者画像及活跃认知盲区。"""
    try:
        profile = await get_or_create_profile(db)
    except LookupError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    misconceptions = await get_active_misconceptions(db, limit=20)
    return LearnerProfileOut(
        id=profile.id,
        background_summary=profile.background_summary or "",
        socratic_mode=profile.socratic_mode,
        updated_at=profile.updated_at,
        misconceptions=await _misconception_outs(db, misconceptions),
    )


@router.put("/profile", response_model=LearnerProfileOut)
async def update_profile(body: UpdateProfileIn, db: AsyncSession = Depends(get_db)):
    """用户手动更新学习者画像（背景描述与苏格拉底教学模式开关）。"""
    try:
        profile = await get_or_create_profile(db)
    except LookupError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if body.background_summary is not None:
        profile.background_summary = body.background_summary.strip()
    if body.socratic_mode is not None:
        profile.socratic_mode = body.socratic_mode
    profile.updated_at = utcnow_iso()
    await db.commit()
    await db.refresh(profile)

    misconceptions = await get_active_misconceptions(db, limit=20)
    return LearnerProfileOut(
        id=profile.id,
        background_summary=profile.background_summary or "",
        socratic_mode=profile.socratic_mode,
        updated_at=profile.updated_at,
        misconceptions=await _misconception_outs(db, misconceptions),
    )


@router.post("/profile/reset", response_model=LearnerProfileOut)
@router.delete("/profile/reset", response_model=LearnerProfileOut)
async def reset_profile(db: AsyncSession = Depends(get_db)):
    """重置学习者画像并清空所有认知盲区，冷启动重新学习。"""
    try:
        profile = await get_or_create_profile(db)
    except LookupError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    profile.background_summary = ""
    profile.socratic_mode = True
    profile.updated_at = utcnow_iso()

    # 清空所有认知盲区
    await db.execute(delete(LearnerMisconception))
    await db.commit()
    await db.refresh(profile)
    return LearnerProfileOut(
        id=profile.id,
        background_summary="",
        socratic_mode=True,
        updated_at=profile.updated_at,
        misconceptions=[],
    )


@router.delete("/profile/misconceptions/{misconception_id}")
async def remove_misconception(misconception_id: str, db: AsyncSession = Depends(get_db)):
    """移除已掌握/纠正的单个认知盲区。

    置 status=resolved 而非物理删除：物理删除后，后台画像演进会在下次交互中
    把同 topic 的盲区原样"复活"，用户的移除操作被静默撤销。resolved 行
    同时作为演进查重的排除依据（见 profile.py）。
    """
    row = await db.get(LearnerMisconception, misconception_id)
    if not row:
        raise HTTPException(status_code=404, detail="认知盲区记录不存在")
    row.status = "resolved"
    row.resolved_at = utcnow_iso()
    await db.commit()
    return {"ok": True}
