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
    # 练习信号：最近一次作答失败的题数
    exercise_fail: int = 0
    # 掌握度 0-100（复习间隔/费曼评分/练习通过率合成；无信号的维度按其余维度归一）
    mastery: int = 50


class RetentionBucket(BaseModel):
    """遗忘曲线：按复习时设定间隔分桶的留存率（该次 quality≥3 记通过，其后相邻一次 <3 记遗忘）。"""

    label: str
    total: int
    passed: int


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
    today: TodayOverview
    weak_points: list[WeakPoint]
    heatmap: list[DayCount]
    retention: list[RetentionBucket] = []
    study_days: list[StudyDayOut] = []
    study_minutes_7d: int = 0
    llm_usage: LLMUsageSummary | None = None
