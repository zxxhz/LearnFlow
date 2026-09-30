from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, UserIdMixin


class FeynmanSession(UUIDPk, UserIdMixin, Timestamps, Base):
    __tablename__ = "feynman_sessions"

    knowledge_point_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_points.id"), index=True
    )
    # 冗余存 document_id，便于按文档查询
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id")
    )
    # explaining / questioning / evaluating / done
    status: Mapped[str] = mapped_column(String(20), default="explaining")
    round_count: Mapped[int] = mapped_column(Integer, default=0)
    # 评价结果 JSON：{score, strengths[], gaps[{desc,severity,section_id}], advice}
    evaluation: Mapped[str | None] = mapped_column(Text, nullable=True)
