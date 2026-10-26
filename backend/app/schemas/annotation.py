from typing import Literal

from pydantic import BaseModel, field_validator

from app.schemas.common import ORMModel

# 标注颜色与状态枚举（与前端四色/两种挂载态一一对应，防止任意字符串入库）
AnnotationColor = Literal["yellow", "green", "blue", "pink"]
AnnotationStatus = Literal["active", "orphan"]


class AnchorIn(BaseModel):
    section_id: str
    exact: str
    prefix: str = ""
    suffix: str = ""
    start_offset: int = 0
    end_offset: int = 0

    @field_validator("exact")
    @classmethod
    def _exact_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("划线内容为空")
        return v


class AnnotationCreate(AnchorIn):
    color: AnnotationColor = "yellow"
    note: str | None = None


class AnnotationUpdate(BaseModel):
    color: AnnotationColor | None = None
    note: str | None = None
    status: AnnotationStatus | None = None
    anchor: AnchorIn | None = None


class AnnotationOut(ORMModel):
    id: str
    document_id: str
    section_id: str
    version: int
    exact: str
    prefix: str
    suffix: str
    start_offset: int
    end_offset: int
    color: str
    note: str | None
    status: str
    created_at: str
    updated_at: str


class AnnotationCreatedOut(BaseModel):
    annotation: AnnotationOut
    conversation_id: str
