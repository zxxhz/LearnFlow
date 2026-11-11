from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk, UserIdMixin


class Conversation(UUIDPk, UserIdMixin, CreatedAt, Base):
    """划线答疑 / 统一 AI 助教对话（费曼模块已于 v0.4.0 移除，历史 kind='feynman' 行在迁移时清理）。"""

    __tablename__ = "conversations"

    # annotation（划线答疑）/ assistant（v0.5.0 统一 AI 助教；历史遗留 feynman 值仅存于旧库）
    kind: Mapped[str] = mapped_column(String(20))
    annotation_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("annotations.id"), nullable=True, index=True
    )
    # 助教会话归属域：document（同一章讲义+练习共用）/ bank_question（题库单题）/ global（全局）
    context_type: Mapped[str] = mapped_column(String(20), default="")
    context_id: Mapped[str] = mapped_column(String(64), default="", index=True)


CONVERSATION_KIND_ANNOTATION = "annotation"
CONVERSATION_KIND_ASSISTANT = "assistant"


class Message(UUIDPk, CreatedAt, Base):
    """system prompt 不入库：由服务层按当前模板现组装（PRD §8.2）。"""

    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id"), index=True
    )
    # user / assistant
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # JSON：token 用量、模型名、引用 section_ids 等预留
    meta: Mapped[str] = mapped_column(Text, default="{}")
