from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin, utcnow_iso


class Document(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "documents"

    course_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.id"), index=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    # 0 = 尚未生成成功过；每次成功生成 +1
    version: Mapped[int] = mapped_column(Integer, default=0)
    # 相对 data_dir 的正文路径，如 courses/{cid}/{did}/current.md
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 本章内容摘要（≤300字），供后续章节生成的上下文传递
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending / generating / done / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    updated_at: Mapped[str] = mapped_column(
        String(40), default=utcnow_iso, onupdate=utcnow_iso
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Section(UUIDPk, UserIdMixin, CreatedAt, Base):
    """文档块级派生索引：可由正文随时重建；ID 跨版本尽力保持（见 PRD §8.3）。"""

    __tablename__ = "sections"

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer)
    # heading / paragraph / code / list / table / quote / math
    block_type: Mapped[str] = mapped_column(String(20))
    heading_path: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    content_hash: Mapped[str] = mapped_column(String(32), index=True)
    text_excerpt: Mapped[str] = mapped_column(Text, default="")
