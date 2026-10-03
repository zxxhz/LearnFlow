"""练习与作答记录：按知识点出题，代码题自动判定 / 概念题 LLM 评分。"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin

# kind 取值
EXERCISE_CODE = "code"  # 从零手写代码的闯关关卡，stdout 对比自动判定
EXERCISE_CONCEPT = "concept"  # 概念简答题，LLM 按参考答案评分
EXERCISE_CHOICE = "choice"  # 单选题，对比选项字母自动判定
EXERCISE_FILL = "fill"  # 填空题，归一化后对比参考答案自动判定

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
    # python / cpp（仅代码题）；其他题型为空
    language: Mapped[str] = mapped_column(String(20), default="")
    skeleton_code: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    # 单选题：JSON 数组 ["选项A文本", ...]；其他题型为空
    options: Mapped[str] = mapped_column(Text, default="")
    # 单选题：正确项字母（"A"）；填空题：JSON 数组的可接受答案列表；其他题型为空
    answer: Mapped[str] = mapped_column(Text, default="")
    # 非空 = 属于某次随堂小测（组卷生成），与普通练习区分展示
    quiz_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    # 闯关链内顺序（同一知识点内 0 起递增；小测题/旧数据为 0，按创建时间兜底排序）
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # 渐进提示（JSON 数组，逐条展开；仅闯关代码关使用）
    hints: Mapped[str] = mapped_column(Text, default="[]")
    # 通关后展示的完整参考实现（旧数据回落 skeleton_code）
    reference_code: Mapped[str] = mapped_column(Text, default="")


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
