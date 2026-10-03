"""模型公共基类与 Mixin。主键一律 UUID hex 字符串；时间戳为 UTC ISO8601 字符串。"""
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


# Windows 的系统时间粒度约 15.6ms：同一 tick 内的连续写入会拿到相同时间戳，
# 而"按 created_at 取最新一条"类查询（错题本、最新作答、消息序）在平局时结果不确定。
# 这里保证本进程内发出的时间戳严格递增（必要时 +1µs），排序永远有确定胜负。
_ts_lock = threading.Lock()
_last_us = 0


def utcnow_iso() -> str:
    global _last_us
    with _ts_lock:
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        if now_us <= _last_us:
            now_us = _last_us + 1
        _last_us = now_us
    dt = datetime.fromtimestamp(now_us / 1_000_000, tz=timezone.utc)
    return dt.isoformat(timespec="microseconds")


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
