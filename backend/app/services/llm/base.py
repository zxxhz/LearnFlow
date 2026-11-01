"""LLM 适配层抽象。业务只依赖 LLMAdapter 接口，不感知具体供应商（PRD §7.3）。"""
import json
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator, TypeVar

from pydantic import BaseModel

from app.services.llm.errors import LLMParseError

T = TypeVar("T", bound=BaseModel)



class LLMAdapter(ABC):
    """统一对话接口。stream=True 时返回异步字符串增量迭代器。"""

    model: str

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> str | AsyncIterator[str]:
        ...

    async def chat_json(
        self,
        messages: list[dict],
        schema: type[T],
        *,
        max_retries: int = 2,
    ) -> T:
        """请求结构化 JSON 输出并用 Pydantic 校验；失败自动重试（PRD §7.3）。"""
        prompt = messages[:]
        last_err: Exception | None = None
        last_raw = ""
        for attempt in range(max_retries + 1):
            extra: list[dict] = []
            if attempt > 0:
                # 附带截断 500 字符的上次原始输出，帮模型定位自己错在哪
                snippet = last_raw.strip()[:500]
                extra = [
                    {
                        "role": "user",
                        "content": f"上一次输出无法解析（{last_err}）。输出片段：{snippet}\n"
                        "请严格只输出符合要求的 JSON，不要包含任何其他文字或代码块标记。",
                    }
                ]
            raw = await self.chat(  # type: ignore[misc]
                prompt + extra,
                stream=False,
                json_mode=True,
            )
            last_raw = raw
            try:
                return schema.model_validate(extract_json(raw))  # type: ignore[arg-type]
            except Exception as e:  # 解析/校验失败继续重试
                last_err = e
        raise LLMParseError(str(last_err))


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def extract_json(raw: str) -> dict | list:
    """从模型输出中尽力提取 JSON 对象：代码块 → 首尾大括号截取（含尾逗号清理兜底）。"""
    raw = raw.strip()

    def _loads(candidate: str):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # 模型常见小毛病：对象/数组最后一项后多一个尾逗号，清理后再试一次
            cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
            return json.loads(cleaned)

    for m in _JSON_BLOCK_RE.finditer(raw):
        candidate = m.group(1).strip()
        try:
            return _loads(candidate)
        except json.JSONDecodeError:
            continue
    start = min(
        (i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1
    )
    if start >= 0:
        end = max(raw.rfind("}"), raw.rfind("]"))
        if end > start:
            return _loads(raw[start : end + 1])
    return _loads(raw)
