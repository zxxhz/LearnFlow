"""练习与作答记录：按知识点出题，代码题自动判定 / 概念题 LLM 评分。"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin

# kind 取值
EXERCISE_CODE = "code"  # 补全代码骨架，stdout 对比自动判定
EXERCISE_CONCEPT = "concept"  # 概念简答题，LLM 按参考答案评分

ATTEMPT_GRADED = "graded"  # 概念题作答完成评分


class Exercise(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "exercises"

    knowledge_point_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_points.id"), index=True
    )
    # 冗余存章节 id，便于按文档列题目（知识点重建时连带删除）
    document_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20), default=EXERCISE_CODE)
    title: Mapped[str] = mapped_column(String(200))
    task_md: Mapped[str] = mapped_column(Text, default="")
    # python / cpp（仅代码题）；概念题为空
    language: Mapped[str] = mapped_column(String(20), default="")
    skeleton_code: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    reference_answer: Mapped[str] = mapped_column(Text, default="")


class ExerciseAttempt(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "exercise_attempts"

    exercise_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("exercises.id"), index=True
    )
    # 提交的代码（代码题）或答案文本（概念题）
    content: Mapped[str] = mapped_column(Text)
    # 代码题复用执行状态；概念题为 graded
    status: Mapped[str] = mapped_column(String(20), default=ATTEMPT_GRADED)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
