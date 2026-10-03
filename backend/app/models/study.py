"""学习数据：每日阅读时长聚合 + LLM Token 用量流水。"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin, utcnow_iso


class StudyDay(Base):
    """按本地日期聚合的阅读时长（秒）。day = 本地日期 ISO 字符串，全局单行单日。"""

    __tablename__ = "study_days"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso, onupdate=utcnow_iso)


class LLMUsage(UUIDPk, CreatedAt, Base):
    """每次 LLM 调用的 Token 用量（成功返回时记录；流式取末块 usage，缺失则跳过）。"""

    __tablename__ = "llm_usages"

    scene: Mapped[str] = mapped_column(String(20), default="chat")
    model: Mapped[str] = mapped_column(String(100), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Quiz(UUIDPk, UserIdMixin, CreatedAt, Base):
    """随堂小测：跨知识点组卷，题目复用 Exercise（quiz_id 回指本表）。"""

    __tablename__ = "quizzes"

    document_id: Mapped[str] = mapped_column(String(32), index=True)
    course_id: Mapped[str] = mapped_column(String(32), default="")
    # 出题时选择的知识点 id 列表（JSON 数组）
    kp_ids: Mapped[str] = mapped_column(Text, default="[]")
    title: Mapped[str] = mapped_column(String(200), default="随堂小测")
