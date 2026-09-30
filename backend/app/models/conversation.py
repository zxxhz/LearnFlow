from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Timestamps, UUIDPk, UserIdMixin


class Conversation(UUIDPk, UserIdMixin, CreatedAt, Base):
    """统一对话模型：划线答疑与费曼共用。"""

    __tablename__ = "conversations"

    # annotation / feynman
    kind: Mapped[str] = mapped_column(String(20))
    annotation_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("annotations.id"), nullable=True, index=True
    )
    feynman_session_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("feynman_sessions.id"), nullable=True, index=True
    )


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
