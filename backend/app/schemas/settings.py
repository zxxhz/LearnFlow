from pydantic import BaseModel, field_validator

from app.models.settings import DEFAULT_HL_COLORS
from app.schemas.common import ORMModel


class SceneLLMConfig(BaseModel):
    """场景级覆盖：空字段回落主配置（PRD §5.7）。"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""


class ScenesConfig(BaseModel):
    generation: SceneLLMConfig = SceneLLMConfig()
    chat: SceneLLMConfig = SceneLLMConfig()
    feynman: SceneLLMConfig = SceneLLMConfig()


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
    # 划线高亮四色（hex），缺失/非法项回落默认
    highlight_colors: dict[str, str] = dict(DEFAULT_HL_COLORS)
    # GitHub 仓库 owner/repo；留空回落环境变量 APP_GITHUB_REPO（PRD 实现备注 15）
    github_repo: str = ""

    @field_validator("highlight_colors", mode="before")
    @classmethod
    def _normalize_hl_colors(cls, v):
        merged = dict(DEFAULT_HL_COLORS)
        if isinstance(v, dict):
            for key in DEFAULT_HL_COLORS:
                val = v.get(key)
                if isinstance(val, str) and len(val) == 7 and val.startswith("#"):
                    try:
                        int(val[1:], 16)
                    except ValueError:
                        continue
                    merged[key] = val.lower()
        return merged


def _mask(key: str) -> str:
    return (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("****" if key else "")


def _mask_scene(s: SceneLLMConfig) -> SceneLLMConfig:
    return s.model_copy(update={"api_key": _mask(s.api_key)})


class SettingsOut(BaseModel):
    llm: LLMConfig
    scenes: ScenesConfig
    preferences: Preferences

    @classmethod
    def masked(cls, llm: LLMConfig, scenes: ScenesConfig, preferences: Preferences) -> "SettingsOut":
        return cls(
            llm=llm.model_copy(update={"api_key": _mask(llm.api_key)}),
            scenes=ScenesConfig(
                generation=_mask_scene(scenes.generation),
                chat=_mask_scene(scenes.chat),
                feynman=_mask_scene(scenes.feynman),
            ),
            preferences=preferences,
        )


class SettingsUpdate(BaseModel):
    llm: LLMConfig | None = None
    scenes: ScenesConfig | None = None
    preferences: Preferences | None = None


class LLMTestResult(BaseModel):
    ok: bool
    model_reply: str | None = None
    latency_ms: int | None = None
    error: str | None = None
