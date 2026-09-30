from pydantic import BaseModel, field_validator

from app.schemas.common import ORMModel
from app.schemas.conversation import MessageOut


class FeynmanGap(BaseModel):
    desc: str
    severity: str = "medium"  # high / medium / low
    section_id: str | None = None


class FeynmanEvaluation(BaseModel):
    score: int
    strengths: list[str] = []
    gaps: list[FeynmanGap] = []
    advice: str = ""

    @field_validator("score")
    @classmethod
    def _score_range(cls, v):
        return max(0, min(100, int(v)))


class FeynmanSessionCreate(BaseModel):
    knowledge_point_id: str
    explanation: str


class FeynmanSessionOut(ORMModel):
    id: str
    knowledge_point_id: str
    document_id: str
    conversation_id: str
    status: str
    round_count: int
    evaluation: FeynmanEvaluation | None = None
    created_at: str
    updated_at: str

    @field_validator("evaluation", mode="before")
    @classmethod
    def _parse_eval(cls, v):
        if isinstance(v, str):
            import json

            return json.loads(v) if v else None
        return v


class FeynmanSessionDetailOut(FeynmanSessionOut):
    messages: list[MessageOut] = []
