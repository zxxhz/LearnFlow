"""题库刷题（独立模块，不进课程体系）：题库 / 题目 / 作答流水。

题目来源为 15 列布局的 .xls/.xlsx（题型/题干/选项A-H/正确答案/…/解析/难度），
解析见 services/bank.py。错题池不维护状态机：由作答流水的「每题最近一次结果」派生。
"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin

# qtype 取值
QUESTION_SINGLE = "single"  # 单选
QUESTION_MULTI = "multi"  # 多选
QUESTION_JUDGE = "judge"  # 判断

# 判断题复用字母作答：A=正确 / B=错误（对齐原刷题应用 JUDGE_KEY_MAP）
JUDGE_OPTIONS = [("A", "正确"), ("B", "错误")]


class QuestionBank(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "question_banks"

    name: Mapped[str] = mapped_column(String(200))
    source_file: Mapped[str] = mapped_column(String(300), default="")
    question_count: Mapped[int] = mapped_column(Integer, default=0)


class BankQuestion(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "bank_questions"

    bank_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("question_banks.id"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # 题库内序号（1 起，稳定排序）
    qtype: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(Text)
    # JSON 数组：选项文本按列位存 8 元素（含空串，字母=下标）；判断题为 "[]"
    options: Mapped[str] = mapped_column(Text, default="[]")
    # single: "A"；multi: 排序字母串 "A,C"；judge: "A"=正确 / "B"=错误
    answer: Mapped[str] = mapped_column(String(20), default="")
    # 展示用原文（"B,C,D" / "正确"）
    answer_raw: Mapped[str] = mapped_column(String(60), default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="")
    explanation: Mapped[str] = mapped_column(Text, default="")


class BankAttempt(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "bank_attempts"

    # bank_id 冗余存储，便于按库聚合统计与级联删除
    bank_id: Mapped[str] = mapped_column(String(32), index=True)
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("bank_questions.id"), index=True
    )
    content: Mapped[str] = mapped_column(String(40), default="")  # 提交字母，多选 "A,C"
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
