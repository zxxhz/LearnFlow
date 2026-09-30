from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin


class KnowledgePoint(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "knowledge_points"

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    # 关联块 ID 列表 JSON（费曼漏洞回链 / 跳转目标）
    section_ids: Mapped[str] = mapped_column(Text, default="[]")
    tags: Mapped[str] = mapped_column(Text, default="[]")
