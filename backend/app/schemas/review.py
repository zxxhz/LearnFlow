from datetime import datetime, timedelta

from pydantic import BaseModel, field_validator

from app.schemas.common import DayCount, ORMModel


class ReviewCardOut(ORMModel):
    id: str
    source_type: str
    knowledge_point_id: str | None
    annotation_id: str | None
    front: str
    back: str
    state: str
    due_at: str
    interval_days: float
    easiness_factor: float
    repetitions: int
    lapses: int
    suspended: bool
    created_at: str
    last_reviewed_at: str | None


class GradeRequest(BaseModel):
    quality: int

    @field_validator("quality")
    @classmethod
    def _valid_q(cls, v):
        if v not in (1, 3, 4, 5):
            raise ValueError("quality 必须是 1/3/4/5")
        return v


class ReviewCardCreate(BaseModel):
    front: str
    back: str = ""
    knowledge_point_id: str | None = None
    annotation_id: str | None = None


class ReviewCardUpdate(BaseModel):
    front: str | None = None
    back: str | None = None
    suspended: bool | None = None


class QueueOut(BaseModel):
    cards: list[ReviewCardOut]
    new_quota_remaining: int
    due_total: int


class ReviewStatsOut(BaseModel):
    today_reviewed: int
    due_remaining: int
    streak_days: int
    total_cards: int
    total_reviews: int
    due_next_7_days: list[DayCount]
