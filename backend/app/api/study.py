"""学习服务：阅读心跳打点与学习者认知画像管理。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import StudyDay
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
    row = await db.get(StudyDay, day)
    if row is None:
        row = StudyDay(day=day, seconds=body.seconds, updated_at=utcnow_iso())
        db.add(row)
    else:
        row.seconds += body.seconds
        row.updated_at = utcnow_iso()
    await db.commit()
    return {"ok": True, "day": day, "seconds": row.seconds}


# ---------------- 学习者画像相关 API ----------------


class MisconceptionOut(BaseModel):
    id: str
    topic: str
    tag: str
    evidence: str
    created_at: str


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
    profile = await get_or_create_profile(db)
    misconceptions = await get_active_misconceptions(db, limit=20)
    return LearnerProfileOut(
        id=profile.id,
        background_summary=profile.background_summary or "",
        socratic_mode=profile.socratic_mode,
        updated_at=profile.updated_at,
        misconceptions=[
            MisconceptionOut(
                id=m.id,
                topic=m.topic,
                tag=m.tag,
                evidence=m.evidence or "",
                created_at=m.created_at,
            )
            for m in misconceptions
        ],
    )


@router.put("/profile", response_model=LearnerProfileOut)
async def update_profile(body: UpdateProfileIn, db: AsyncSession = Depends(get_db)):
    """用户手动更新学习者画像（背景描述与苏格拉底教学模式开关）。"""
    profile = await get_or_create_profile(db)
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
        misconceptions=[
            MisconceptionOut(
                id=m.id,
                topic=m.topic,
                tag=m.tag,
                evidence=m.evidence or "",
                created_at=m.created_at,
            )
            for m in misconceptions
        ],
    )


@router.post("/profile/reset", response_model=LearnerProfileOut)
@router.delete("/profile/reset", response_model=LearnerProfileOut)
async def reset_profile(db: AsyncSession = Depends(get_db)):
    """重置学习者画像并清空所有认知盲区，冷启动重新学习。"""
    profile = await get_or_create_profile(db)
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
    """移除已掌握/纠正的单个认知盲区。"""
    row = await db.get(LearnerMisconception, misconception_id)
    if not row:
        raise HTTPException(status_code=404, detail="认知盲区记录不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
