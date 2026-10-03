from pydantic import BaseModel

from app.schemas.common import DayCount


class DashboardCourse(BaseModel):
    id: str
    title: str
    status: str
    done_chapters: int
    total_chapters: int
    updated_at: str


class WeakPoint(BaseModel):
    knowledge_point_id: str
    title: str
    document_id: str
    # 练习信号：最近一次作答失败的题数
    exercise_fail: int = 0
    # 掌握度 0-100（闯关练习通过率单信号）
    mastery: int = 50


class StudyDayOut(BaseModel):
    date: str
    minutes: int


class SceneUsage(BaseModel):
    scene: str
    calls: int
    tokens: int


class LLMUsageSummary(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    by_scene: list[SceneUsage]


class DashboardSummary(BaseModel):
    courses: list[DashboardCourse]
    weak_points: list[WeakPoint]
    heatmap: list[DayCount]
    study_days: list[StudyDayOut] = []
    study_minutes_7d: int = 0
    llm_usage: LLMUsageSummary | None = None
