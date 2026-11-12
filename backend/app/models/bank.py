"""题库刷题（独立模块，不进课程体系）：题库 / 题目 / 作答流水。

题目来源为 15 列布局的 .xls/.xlsx（题型/题干/选项A-H/正确答案/…/解析/难度），
解析见 services/bank.py。错题池不维护状态机：由作答流水的「每题最近一次结果」派生。
"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin, utcnow_iso

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
    ai_prompt: Mapped[str] = mapped_column(Text, default="")


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
    ai_explanation: Mapped[str] = mapped_column(Text, default="")
    # 字段级新者胜时间戳（v0.5.8 体检 P1）："" 视为最旧（历史遗留行）；任何字段
    # 变更路径必须刷新，pull 合并据此决定「云端值」是否覆盖「本地值」
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)


class BankAttempt(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "bank_attempts"

    # bank_id 冗余存储，便于按库聚合统计与级联删除
    bank_id: Mapped[str] = mapped_column(String(32), index=True)
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("bank_questions.id"), index=True
    )
    content: Mapped[str] = mapped_column(String(40), default="")  # 提交字母，多选 "A,C"
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_doubtful: Mapped[bool] = mapped_column(Boolean, default=False)
    # 软撤回（误触撤回）：置 True 后统计口径整体排除。不物理删除：同步链路是
    # upsert-only 合并，本地删行会被云端快照拉回复活，字段更新才能自然传播（对齐纠错重判）
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    # 字段级新者胜时间戳（v0.5.8 体检 P1）：撤回/重判等字段变更必须刷新
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)


class SyncTombstone(Base):
    """同步删除墓碑（v0.5.8 体检 P1）：replace 修剪的题与整库删除的题库记录于此。

    push 携带墓碑给云端执行真删除并持久化，pull 侧据其抑制「云端已删条目复活」；
    没有墓碑时云端 upsert-only 合并会把已删数据拉回来并自我强化（push 再送回去）。
    """

    __tablename__ = "sync_tombstones"

    object_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # bank / bank_question（后续可扩展其他资源）
    kind: Mapped[str] = mapped_column(String(32))
    deleted_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)
