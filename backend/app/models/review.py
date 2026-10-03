from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk, UserIdMixin
from app.models.base import utcnow_iso


class ReviewCard(UUIDPk, UserIdMixin, Timestamps, Base):
    __tablename__ = "review_cards"

    # knowledge_point / annotation / feynman_gap / manual / exercise
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    knowledge_point_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("knowledge_points.id"), nullable=True, index=True
    )
    annotation_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("annotations.id"), nullable=True, index=True
    )
    # 练习错题卡溯源：练习做错时自动成卡，练习做对时自动按「记得」过一遍
    exercise_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text, default="")

    # new / learning / review / relearning
    state: Mapped[str] = mapped_column(String(20), default="new", index=True)
    due_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso, index=True)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    easiness_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    # 首次进入学习的时间，用于每日新卡配额
    introduced_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ReviewLog(UUIDPk, CreatedAt, Base):
    __tablename__ = "review_logs"

    card_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("review_cards.id"), index=True
    )
    reviewed_at: Mapped[str] = mapped_column(String(40))
    quality: Mapped[int] = mapped_column(Integer)  # 1 / 3 / 4 / 5
    interval_days: Mapped[float] = mapped_column(Float)
    ease_factor: Mapped[float] = mapped_column(Float)
    state_before: Mapped[str] = mapped_column(String(20))
    state_after: Mapped[str] = mapped_column(String(20))
