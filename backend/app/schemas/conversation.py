from pydantic import BaseModel

from app.schemas.common import ORMModel


class MessageOut(ORMModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class MessageCreate(BaseModel):
    content: str
