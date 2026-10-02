from pydantic import BaseModel, field_validator

from app.models.exercise import EXERCISE_CODE, EXERCISE_CONCEPT
from app.schemas.common import ORMModel
from app.schemas.execution import LANG_ALIASES

MAX_ATTEMPT_LENGTH = 64_000


class ExerciseGenerateRequest(BaseModel):
    """按知识点出题：language 决定代码题语言，count 为 0 时用偏好值。"""

    knowledge_point_id: str
    language: str
    count: int = 0

    @field_validator("language")
    @classmethod
    def _normalize_lang(cls, v: str) -> str:
        lang = LANG_ALIASES.get(v.strip().lower(), "")
        if not lang:
            raise ValueError(f"暂不支持 {v}，练习目前支持 Python 和 C++")
        return lang

    @field_validator("count")
    @classmethod
    def _clamp_count(cls, v: int) -> int:
        return max(0, min(4, int(v)))


class ExerciseSubmitRequest(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def _content_size(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("提交内容为空")
        if len(v) > MAX_ATTEMPT_LENGTH:
            raise ValueError("提交内容过长（上限 64K 字符）")
        return v


class ExerciseAttemptOut(ORMModel):
    id: str
    exercise_id: str
    content: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int | None
    passed: bool | None
    feedback: str
    created_at: str


class ExerciseOut(ORMModel):
    id: str
    knowledge_point_id: str
    document_id: str
    kind: str
    title: str
    task_md: str
    language: str
    skeleton_code: str
    expected_output: str
    reference_answer: str
    created_at: str
    kp_title: str | None = None
    latest_attempt: ExerciseAttemptOut | None = None


# ---- LLM 结构化输出目标 ----

_KINDS = {EXERCISE_CODE, EXERCISE_CONCEPT}


class ExerciseDraftItem(BaseModel):
    """出题 JSON 中单题的形状（chat_json 校验目标）。"""

    kind: str
    title: str
    task: str
    language: str = ""
    skeleton_code: str = ""
    expected_output: str = ""
    reference_answer: str = ""

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        k = v.strip().lower()
        if k not in _KINDS:
            raise ValueError(f"未知的题型 {v}")
        return k

    @field_validator("language")
    @classmethod
    def _normalize_lang(cls, v: str) -> str:
        return LANG_ALIASES.get(v.strip().lower(), "")

    def resolved_language(self, fallback: str) -> str:
        """代码题语言缺失时回落出题请求里选的语言。"""
        return self.language or fallback

    def is_complete(self) -> bool:
        if self.kind == EXERCISE_CODE:
            return bool(self.task.strip() and self.skeleton_code.strip() and self.expected_output.strip())
        return bool(self.task.strip() and self.reference_answer.strip())


class ExerciseDraftSet(BaseModel):
    exercises: list[ExerciseDraftItem] = []

    @field_validator("exercises")
    @classmethod
    def _non_empty(cls, v: list[ExerciseDraftItem]) -> list[ExerciseDraftItem]:
        if not v:
            raise ValueError("模型未返回任何练习题")
        return v


class ConceptGrade(BaseModel):
    """概念题评分结果。"""

    passed: bool
    score: int = 0
    feedback: str = ""

    @field_validator("score")
    @classmethod
    def _score_range(cls, v):
        return max(0, min(100, int(v)))
