import json

from pydantic import BaseModel, field_validator

from app.models.exercise import EXERCISE_CODE, EXERCISE_CHOICE, EXERCISE_CONCEPT, EXERCISE_FILL
from app.schemas.common import ORMModel
from app.schemas.execution import LANG_ALIASES

MAX_ATTEMPT_LENGTH = 64_000
CHOICE_LETTERS = "ABCDEFG"


def _normalize_lang_str(v: str) -> str:
    return LANG_ALIASES.get(v.strip().lower(), "")


class ExerciseGenerateRequest(BaseModel):
    """按知识点出题：language 决定代码题语言，count 为 0 时用偏好值。"""

    knowledge_point_id: str
    language: str
    count: int = 0

    @field_validator("language")
    @classmethod
    def _normalize_lang(cls, v: str) -> str:
        lang = _normalize_lang_str(v)
        if not lang:
            raise ValueError(f"暂不支持 {v}，练习目前支持 Python 和 C++")
        return lang

    @field_validator("count")
    @classmethod
    def _clamp_count(cls, v: int) -> int:
        return max(0, min(4, int(v)))


class QuizGenerateRequest(BaseModel):
    """随堂小测：跨知识点组卷（只出可自动判定的题型）。"""

    document_id: str
    kp_ids: list[str]
    language: str = "python"
    per_kp: int = 1

    @field_validator("kp_ids")
    @classmethod
    def _require_kps(cls, v: list[str]) -> list[str]:
        kps = [k for k in v if k.strip()]
        if not kps:
            raise ValueError("至少选择一个知识点")
        return kps

    @field_validator("language")
    @classmethod
    def _normalize_lang(cls, v: str) -> str:
        return _normalize_lang_str(v) or "python"

    @field_validator("per_kp")
    @classmethod
    def _clamp_per_kp(cls, v: int) -> int:
        return max(1, min(3, int(v)))


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
    reference_code: str = ""
    options: str = ""
    answer: str = ""
    quiz_id: str = ""
    order_index: int = 0
    hints: list[str] = []
    created_at: str
    # 闯关状态：同一知识点内前一关通过后才可作答（小测题/非代码题恒为可作答）
    unlocked: bool = True
    ever_passed: bool = False
    kp_title: str | None = None
    latest_attempt: ExerciseAttemptOut | None = None

    @field_validator("hints", mode="before")
    @classmethod
    def _parse_hints(cls, v):
        """库中 hints 存 JSON 字符串，出参统一为列表。"""
        if isinstance(v, str):
            try:
                data = json.loads(v)
            except json.JSONDecodeError:
                return []
            return [str(x) for x in data] if isinstance(data, list) else []
        return v or []


class QuizOut(BaseModel):
    id: str
    document_id: str
    course_id: str
    title: str
    kp_ids: list[str]
    created_at: str
    items: list[ExerciseOut] = []
    total: int = 0
    correct: int = 0


# ---- LLM 结构化输出目标 ----

_KINDS = {EXERCISE_CODE, EXERCISE_CONCEPT, EXERCISE_CHOICE, EXERCISE_FILL}


class ExerciseDraftItem(BaseModel):
    """出题 JSON 中单题的形状（chat_json 校验目标）。"""

    kind: str
    title: str
    task: str
    language: str = ""
    skeleton_code: str = ""
    expected_output: str = ""
    reference_answer: str = ""
    reference_code: str = ""
    # 闯关代码关的渐进提示（按展开顺序）
    hints: list[str] = []
    options: list[str] = []
    answer: str | list[str] = ""
    # 仅组卷出题用：题目归属的知识点序号（1-based，0/缺省 = 由服务端分配）
    kp_index: int = 0

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
        return _normalize_lang_str(v)

    def resolved_language(self, fallback: str) -> str:
        """代码题语言缺失时回落出题请求里选的语言。"""
        return self.language or fallback

    def _answer_list(self) -> list[str]:
        if isinstance(self.answer, list):
            return [str(x) for x in self.answer]
        return [self.answer] if self.answer else []

    def answer_letter(self) -> str:
        """单选题答案归一成大写字母（接受 "A"/"a"/"2" 等形式）。"""
        for raw in self._answer_list():
            t = str(raw).strip().upper().rstrip(".")
            if t in CHOICE_LETTERS:
                return t
            if t.isdigit():
                i = int(t)
                if 1 <= i <= len(CHOICE_LETTERS):
                    return CHOICE_LETTERS[i - 1]
        return ""

    def stored_answer(self) -> str:
        """落库形态：choice → 字母；fill → JSON 数组（可接受答案）；其余空串。"""
        if self.kind == EXERCISE_CHOICE:
            return self.answer_letter()
        if self.kind == EXERCISE_FILL:
            return json.dumps([a for a in self._answer_list() if str(a).strip()], ensure_ascii=False)
        return ""

    def is_complete(self) -> bool:
        if self.kind == EXERCISE_CODE:
            # 闯关关必须有任务与目标输出；参考实现任取其一（组卷题用骨架，闯关题用完整实现）
            return bool(
                self.task.strip()
                and self.expected_output.strip()
                and (self.skeleton_code.strip() or self.reference_code.strip())
            )
        if self.kind == EXERCISE_CHOICE:
            return bool(self.task.strip() and len(self.options) >= 2 and self.answer_letter())
        if self.kind == EXERCISE_FILL:
            return bool(self.task.strip() and any(str(a).strip() for a in self._answer_list()))
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
