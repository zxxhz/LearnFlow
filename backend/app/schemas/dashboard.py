from pydantic import BaseModel

from app.schemas.common import DayCount


class DashboardCourse(BaseModel):
    id: str
    title: str
    status: str
    done_chapters: int
    total_chapters: int
    updated_at: str


class TodayOverview(BaseModel):
    due_reviews: int
    feynman_active: int


class WeakPoint(BaseModel):
    knowledge_point_id: str
    title: str
    document_id: str
    lapses: int
    gap_count: int


class DashboardSummary(BaseModel):
    courses: list[DashboardCourse]
    today: TodayOverview
    weak_points: list[WeakPoint]
    heatmap: list[DayCount]
