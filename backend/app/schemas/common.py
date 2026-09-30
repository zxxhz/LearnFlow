from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OutlineItem(BaseModel):
    index: int
    title: str
    points: list[str] = []


class DayCount(BaseModel):
    date: str  # YYYY-MM-DD（本地时区）
    count: int
