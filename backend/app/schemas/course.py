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
    scope: str | None = None
    outline: list[OutlineItem] = []
    status: str
    course_settings: dict = {}
    created_at: str
    updated_at: str

    @field_validator("outline", mode="before")
    @classmethod
    def _parse_outline(cls, v):
        if isinstance(v, str):
            import json

            return json.loads(v) if v else []
        return v

    @field_validator("course_settings", mode="before")
    @classmethod
    def _parse_settings(cls, v):
        if isinstance(v, str):
            import json

            return json.loads(v) if v else {}
        return v


class CourseSettingsUpdate(BaseModel):
    # 传入即改名（去空格后须非空）；不传则只更新 course_settings
    title: str | None = None
    auto_create_cards: bool | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("课程名称不能为空")
        return v[:200]


class ChapterProgress(BaseModel):
    document_id: str
    chapter_index: int
    title: str
    status: str
    version: int
    error: str | None = None
    source: str = "generated"


class CourseDetailOut(CourseOut):
    documents: list[ChapterProgress] = []


class CourseListItem(CourseOut):
    done_chapters: int = 0
    total_chapters: int = 0


class OutlineUpdate(BaseModel):
    outline: list[OutlineItem]


class RegenerateRequest(BaseModel):
    instruction: str | None = None
