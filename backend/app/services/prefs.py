"""本地偏好与日期小工具（原 review 模块的公共部分，复习模块移除后独立成档）。"""
import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

logger = logging.getLogger(__name__)


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
    if not row or not row.preferences:
        return {}
    try:
        return json.loads(row.preferences)
    except json.JSONDecodeError:
        # 偏好 JSON 损坏不能让所有依赖偏好的功能 500：按未配置处理，设置页保存即覆盖修复
        # （对齐 openai_compat 对损坏设置的自愈策略）
        logger.warning("偏好设置 JSON 损坏，已回落为空配置：%r", row.preferences[:200])
        return {}
