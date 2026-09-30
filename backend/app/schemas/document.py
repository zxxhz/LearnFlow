import json

from pydantic import BaseModel, field_validator

from app.schemas.common import ORMModel


class DocumentOut(ORMModel):
    id: str
    course_id: str
    chapter_index: int
    title: str
    version: int
    status: str
    source: str = "generated"
    summary: str | None
    updated_at: str


class SectionOut(BaseModel):
    id: str
    order_index: int
    block_type: str
    heading_path: list[str] = []

    @field_validator("heading_path", mode="before")
    @classmethod
    def _parse(cls, v):
        if isinstance(v, str):
            return json.loads(v) if v else []
        return v


class DocumentContentOut(BaseModel):
    document: DocumentOut
    markdown: str
    blocks: list[SectionOut]
