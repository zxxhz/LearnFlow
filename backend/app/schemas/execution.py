from pydantic import BaseModel, field_validator

from app.schemas.common import ORMModel

SUPPORTED_LANGUAGES = ("python", "cpp")
# 前端 fence 语言标注 → 规范化语言
LANG_ALIASES = {
    "python": "python",
    "py": "python",
    "python3": "python",
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
}


class CodeRunRequest(BaseModel):
    document_id: str
    section_id: str
    language: str
    code: str

    @field_validator("language")
    @classmethod
    def _normalize_lang(cls, v: str) -> str:
        lang = LANG_ALIASES.get(v.strip().lower(), "")
        if not lang:
            raise ValueError(f"暂不支持运行 {v}，目前支持 Python 和 C++")
        return lang

    @field_validator("code")
    @classmethod
    def _code_size(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("代码为空")
        if len(v) > 64_000:
            raise ValueError("代码过长（上限 64K 字符）")
        return v


class CodeExecutionOut(ORMModel):
    id: str
    document_id: str
    section_id: str
    document_version: int
    language: str
    code: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int | None
    created_at: str
