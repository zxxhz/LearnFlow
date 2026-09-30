from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk, UserIdMixin


class Course(UUIDPk, UserIdMixin, Timestamps, Base):
    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 确认后的课程大纲 JSON: [{index, title, points: [...]}]
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    # draft / generating / ready / archived
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # 课程级覆盖项 JSON（如 auto_create_cards）
    course_settings: Mapped[str] = mapped_column(Text, default="{}")

    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_count: Mapped[int | None] = mapped_column(nullable=True)


COURSE_STATUS = ("draft", "generating", "ready", "archived")
DOC_STATUS = ("pending", "generating", "done", "failed")
