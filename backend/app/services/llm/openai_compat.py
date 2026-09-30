"""OpenAI 兼容协议适配器：智谱 GLM / DeepSeek / OpenAI / Moonshot 等均可接入。"""
import json
import time
from typing import AsyncIterator

from openai import (
    APIConnectionError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting
from app.services.llm.base import LLMAdapter
from app.services.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMNotConfiguredError,
    LLMRateLimitError,
    LLMServiceError,
)


def translate_openai_error(e: Exception) -> Exception:
    if isinstance(e, APIConnectionError):
        return LLMConnectionError(str(e))
    if isinstance(e, AuthenticationError):
        return LLMAuthError(str(e))
    if isinstance(e, RateLimitError):
        return LLMRateLimitError(str(e))
    if isinstance(e, BadRequestError):
        return LLMServiceError(str(e))
    if isinstance(e, LLMServiceError):
        return e
    return LLMServiceError(repr(e))


class OpenAICompatAdapter(LLMAdapter):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = AsyncOpenAI(
            base_url=base_url or None, api_key=api_key or "EMPTY", timeout=180
        )
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ):
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            if stream:
                return self._stream(kwargs, allow_json_fallback=json_mode)
            resp = await self.client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except (LLMServiceError, LLMConnectionError, LLMAuthError, LLMRateLimitError):
            raise
        except Exception as e:
            # 不支持 response_format 的端点：去掉后重试一次
            if json_mode and isinstance(e, BadRequestError):
                kwargs.pop("response_format", None)
                try:
                    resp = await self.client.chat.completions.create(**kwargs)
                    return resp.choices[0].message.content or ""
                except Exception as e2:
                    raise translate_openai_error(e2) from e2
            raise translate_openai_error(e) from e

    async def _stream(
        self, kwargs: dict, *, allow_json_fallback: bool = False
    ) -> AsyncIterator[str]:
        try:
            stream = await self.client.chat.completions.create(**kwargs, stream=True)
        except Exception as e:
            if allow_json_fallback and isinstance(e, BadRequestError):
                kwargs.pop("response_format", None)
                stream = await self.client.chat.completions.create(
                    **kwargs, stream=True
                )
            else:
                raise translate_openai_error(e) from e
        try:
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        except Exception as e:
            raise translate_openai_error(e) from e
        finally:
            await stream.close()


SCENES = ("generation", "chat", "feynman")


async def create_adapter_from_settings(
    db: AsyncSession, scene: str | None = None
) -> OpenAICompatAdapter:
    """从 app_settings 读取配置并构建适配器。

    scene ∈ {generation, chat, feynman}：场景槽位里非空的字段覆盖主配置，
    空字段回落主配置（PRD §5.7：便宜模型做生成、强模型做费曼评价）。
    未配置时抛友好错误。
    """
    row = await db.get(AppSetting, "local")
    cfg = json.loads(row.llm) if row and row.llm else {}
    merged = {
        "base_url": cfg.get("base_url", ""),
        "api_key": cfg.get("api_key", ""),
        "model": cfg.get("model", ""),
    }
    if scene:
        if scene not in SCENES:
            raise LLMServiceError(f"未知场景：{scene}")
        scene_cfg = (cfg.get("scenes") or {}).get(scene) or {}
        for k in ("base_url", "api_key", "model"):
            if str(scene_cfg.get(k) or "").strip():
                merged[k] = str(scene_cfg[k]).strip()
    if not merged["api_key"] or not merged["model"]:
        raise LLMNotConfiguredError()
    return OpenAICompatAdapter(
        base_url=merged["base_url"],
        api_key=merged["api_key"],
        model=merged["model"],
    )


async def get_llm_temperature(db: AsyncSession) -> float:
    row = await db.get(AppSetting, "local")
    cfg = json.loads(row.llm) if row and row.llm else {}
    return float(cfg.get("temperature", 0.7))
