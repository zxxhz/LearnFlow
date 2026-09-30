"""模型公共基类与 Mixin。主键一律 UUID hex 字符串；时间戳为 UTC ISO8601 字符串。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class UUIDPk:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class UserIdMixin:
    """为未来多用户预留；当前恒为 local。"""

    user_id: Mapped[str] = mapped_column(String(32), default="local", index=True)


class Timestamps:
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(
        String(40), default=utcnow_iso, onupdate=utcnow_iso
    )


class CreatedAt:
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)
