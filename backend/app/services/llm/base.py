"""LLM 适配层抽象。业务只依赖 LLMAdapter 接口，不感知具体供应商（PRD §7.3）。"""
import json
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator, TypeVar

from pydantic import BaseModel

from app.services.llm.errors import LLMParseError

T = TypeVar("T", bound=BaseModel)

JsonShape = list[dict] | None


class LLMAdapter(ABC):
    """统一对话接口。stream=True 时返回异步字符串增量迭代器。"""

    model: str

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str | AsyncIterator[str]:
        ...

    async def chat_json(
        self,
        messages: list[dict],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_retries: int = 2,
    ) -> T:
        """请求结构化 JSON 输出并用 Pydantic 校验；失败自动重试（PRD §7.3）。"""
        prompt = messages[:]
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            extra: list[dict] = []
            if attempt > 0:
                extra = [
                    {
                        "role": "user",
                        "content": f"上一次输出无法解析（{last_err}）。"
                        "请严格只输出符合要求的 JSON，不要包含任何其他文字或代码块标记。",
                    }
                ]
            raw = await self.chat(  # type: ignore[misc]
                prompt + extra,
                stream=False,
                temperature=temperature,
                json_mode=True,
            )
            try:
                return schema.model_validate(extract_json(raw))  # type: ignore[arg-type]
            except Exception as e:  # 解析/校验失败继续重试
                last_err = e
        raise LLMParseError(str(last_err))


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def extract_json(raw: str) -> dict | list:
    """从模型输出中尽力提取 JSON 对象：代码块 → 首尾大括号截取。"""
    raw = raw.strip()
    for m in _JSON_BLOCK_RE.finditer(raw):
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    start = min(
        (i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1
    )
    if start >= 0:
        end = max(raw.rfind("}"), raw.rfind("]"))
        if end > start:
            return json.loads(raw[start : end + 1])
    return json.loads(raw)
