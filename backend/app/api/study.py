"""学习打点：阅读页心跳上报，按本地日聚合时长。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import StudyDay
from app.models.base import utcnow_iso
from app.services.review import local_today

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
