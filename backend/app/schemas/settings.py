from pydantic import BaseModel

from app.schemas.common import ORMModel


class LLMConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7


class Preferences(BaseModel):
    daily_new_cards: int = 20
    chapter_length: int = 3000
    feynman_max_rounds: int = 4
    auto_create_cards: bool = True


class SettingsOut(BaseModel):
    llm: LLMConfig
    preferences: Preferences

    @classmethod
    def masked(cls, llm: LLMConfig, preferences: Preferences) -> "SettingsOut":
        key = llm.api_key
        shown = (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("****" if key else "")
        return cls(llm=llm.model_copy(update={"api_key": shown}), preferences=preferences)


class SettingsUpdate(BaseModel):
    llm: LLMConfig | None = None
    preferences: Preferences | None = None


class LLMTestResult(BaseModel):
    ok: bool
    model_reply: str | None = None
    latency_ms: int | None = None
    error: str | None = None
