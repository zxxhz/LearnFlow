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
    def __init__(self, base_url: str, api_key: str, model: str, scene: str = "chat"):
        self.client = AsyncOpenAI(
            base_url=base_url or None, api_key=api_key or "EMPTY", timeout=180
        )
        self.model = model
        self.scene = scene

    def _record(self, usage, duration_ms: int) -> None:
        """成功调用后记 Token 用量（无 usage 字段的端点静默跳过）。"""
        if usage is None:
            return
        from app.services.llm.usage import record_usage

        record_usage(
            self.scene,
            self.model,
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
            duration_ms,
        )

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
            t0 = time.perf_counter()
            resp = await self.client.chat.completions.create(**kwargs)
            self._record(resp, int((time.perf_counter() - t0) * 1000))
            return resp.choices[0].message.content or ""
        except (LLMServiceError, LLMConnectionError, LLMAuthError, LLMRateLimitError):
            raise
        except Exception as e:
            # 不支持 response_format / stream_options 的端点：去掉后重试一次
            if isinstance(e, BadRequestError) and (
                json_mode or "stream_options" in kwargs
            ):
                kwargs.pop("response_format", None)
                kwargs.pop("stream_options", None)
                try:
                    if stream:
                        return self._stream(kwargs, allow_json_fallback=False)
                    t0 = time.perf_counter()
                    resp = await self.client.chat.completions.create(**kwargs)
                    self._record(resp, int((time.perf_counter() - t0) * 1000))
                    return resp.choices[0].message.content or ""
                except Exception as e2:
                    raise translate_openai_error(e2) from e2
            raise translate_openai_error(e) from e

    async def _stream(
        self, kwargs: dict, *, allow_json_fallback: bool = False
    ) -> AsyncIterator[str]:
        # 尽力请求用量：兼容端点会在末块带 usage；拒绝该参数的由 chat 层降级重试
        t0 = time.perf_counter()
        try:
            stream = await self.client.chat.completions.create(
                **kwargs, stream=True, stream_options={"include_usage": True}
            )
        except Exception as e:
            if isinstance(e, BadRequestError):
                try:
                    stream = await self.client.chat.completions.create(**kwargs, stream=True)
                except Exception as e2:
                    raise translate_openai_error(e2) from e2
            elif allow_json_fallback:
                kwargs.pop("response_format", None)
                try:
                    stream = await self.client.chat.completions.create(
                        **kwargs, stream=True, stream_options={"include_usage": True}
                    )
                except Exception:
                    try:
                        stream = await self.client.chat.completions.create(
                            **kwargs, stream=True
                        )
                    except Exception as e2:
                        raise translate_openai_error(e2) from e2
            else:
                raise translate_openai_error(e) from e
        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    self._record(chunk.usage, int((time.perf_counter() - t0) * 1000))
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
        scene=scene or "chat",
    )


async def get_llm_temperature(db: AsyncSession) -> float:
    row = await db.get(AppSetting, "local")
    cfg = json.loads(row.llm) if row and row.llm else {}
    return float(cfg.get("temperature", 0.7))
