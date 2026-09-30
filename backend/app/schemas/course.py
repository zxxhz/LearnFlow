from pydantic import BaseModel, field_validator

from app.schemas.common import ORMModel, OutlineItem


class CourseCreate(BaseModel):
    topic: str
    level: str | None = None
    scope: str | None = None
    chapter_count: int | None = None


class CourseOut(ORMModel):
    id: str
    title: str
    topic: str
    level: str | None
    outline: list[OutlineItem] = []
    status: str
    created_at: str
    updated_at: str

    @field_validator("outline", mode="before")
    @classmethod
    def _parse_outline(cls, v):
        if isinstance(v, str):
            import json

            return json.loads(v) if v else []
        return v


class ChapterProgress(BaseModel):
    document_id: str
    chapter_index: int
    title: str
    status: str
    version: int
    error: str | None = None


class CourseDetailOut(CourseOut):
    documents: list[ChapterProgress] = []


class CourseListItem(CourseOut):
    done_chapters: int = 0
    total_chapters: int = 0


class OutlineUpdate(BaseModel):
    outline: list[OutlineItem]


class RegenerateRequest(BaseModel):
    instruction: str | None = None
