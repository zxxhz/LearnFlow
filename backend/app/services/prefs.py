"""本地偏好与日期小工具（原 review 模块的公共部分，复习模块移除后独立成档）。"""
import json
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting


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


async def get_preferences(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, "local")
    return json.loads(row.preferences) if row and row.preferences else {}
