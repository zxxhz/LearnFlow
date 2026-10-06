"""题库刷题 schemas：预览 / 题目 / 作答结果 / 统计。

题目对学习者侧发的两种形态：
- 作答中（BankQuestionOut）：永不下发答案与解析
- 错题复习（BankWrongQuestionOut）：含答案原文与解析
"""
from pydantic import BaseModel, Field, field_validator


class BankSkippedRow(BaseModel):
    row: int
    reason: str


class BankAnalysisOut(BaseModel):
    """导入预览：不含任何答案。"""

    name: str
    source_file: str
    question_count: int
    skipped_total: int
    skipped: list[BankSkippedRow]
    by_type: dict[str, int]
    by_difficulty: dict[str, int]
    samples: list["BankQuestionOut"]


class BankQuestionOut(BaseModel):
    id: str
    seq: int
    qtype: str
    title: str
    options: list[str]  # 按列位的 8 元素数组（含空串），字母 = 下标；判断题为 []
    difficulty: str


class BankWrongQuestionOut(BankQuestionOut):
    """错题复习形态：含答案与解析。"""

    answer: str
    answer_raw: str
    explanation: str


class BankAttemptResult(BaseModel):
    attempt_id: str
    passed: bool
    answer: str  # 字母串（"A" / "A,C"），供前端高亮正确项
    correct_answer: str  # 展示串（判断题 正确/错误，多选顿号连接）
    answer_raw: str
    explanation: str


class BankStatsOut(BaseModel):
    question_count: int
    answered: int  # 答过（有作答记录）的题数
    attempts: int  # 作答流水总数
    correct: int  # 最近一次作答正确的题数
    accuracy: float  # 全部流水的累计正确率（%）
    wrong_count: int  # 错题池大小
    by_type: dict[str, dict]


class BankRenameIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("题库名称不能为空")
        return v[:200]


class BankUpdateIn(BaseModel):
    name: str | None = None
    ai_prompt: str | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v):
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("题库名称不能为空")
        return v[:200]


class BankPromptPolishIn(BaseModel):
    prompt: str = ""
    bank_name: str = ""


class BankPromptPolishOut(BaseModel):
    polished_prompt: str


class BankAiExplainIn(BaseModel):
    picked: list[str] = Field(default_factory=list)


class BankOut(BaseModel):
    id: str
    name: str
    source_file: str
    question_count: int
    ai_prompt: str = ""
    created_at: str
    stats: BankStatsOut


class BankRoundRequest(BaseModel):
    mode: str = Field(default="random", pattern="^(random|wrong)$")
    size: int = Field(default=20, ge=1, le=100)


class BankRoundOut(BaseModel):
    bank_id: str
    mode: str
    questions: list[BankQuestionOut]
    wrong_pool_size: int  # wrong 模式下 = 错题池总量（供「再来一轮」判断）


class BankAttemptRequest(BaseModel):
    question_id: str
    content: list[str] = Field(default_factory=list)  # 提交字母，多选 ["A","C"]
