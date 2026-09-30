from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, UserIdMixin


class Annotation(UUIDPk, UserIdMixin, Timestamps, Base):
    """划线标注。锚定五元组见 PRD §9：位置字段仅作提示，非权威。"""

    __tablename__ = "annotations"

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id"), index=True
    )
    section_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    exact: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(Text, default="")
    suffix: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)
    # yellow / green / blue / pink
    color: Mapped[str] = mapped_column(String(20), default="yellow")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active / orphan
    status: Mapped[str] = mapped_column(String(20), default="active")
