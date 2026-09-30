from pydantic import BaseModel

from app.schemas.common import ORMModel


class AnchorIn(BaseModel):
    section_id: str
    exact: str
    prefix: str = ""
    suffix: str = ""
    start_offset: int = 0
    end_offset: int = 0


class AnnotationCreate(AnchorIn):
    color: str = "yellow"


class AnnotationUpdate(BaseModel):
    color: str | None = None
    note: str | None = None
    status: str | None = None
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
