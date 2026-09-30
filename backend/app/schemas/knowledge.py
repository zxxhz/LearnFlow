import json

from pydantic import field_validator

from app.schemas.common import ORMModel


class KnowledgePointOut(ORMModel):
    id: str
    document_id: str
    title: str
    summary: str
    section_ids: list[str] = []
    tags: list[str] = []
    created_at: str

    @field_validator("section_ids", "tags", mode="before")
    @classmethod
    def _parse(cls, v):
        if isinstance(v, str):
            return json.loads(v) if v else []
        return v
