from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MessageOut(ORMModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class MessageCreate(BaseModel):
    # 长度上限：防一条超长提问被 30 轮历史反复原样带入撑爆上下文（v0.5.1 体检 P2）
    content: str = Field(max_length=8000)
