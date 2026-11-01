"""章节输出解析：正文 + <LEARNFLOW_META> 分隔符后的 JSON 元数据（PRD 实现备注 5）。"""
import logging

from pydantic import BaseModel

from app.services.llm.base import extract_json

logger = logging.getLogger(__name__)

META_SEPARATOR = "<LEARNFLOW_META>"


class KPItem(BaseModel):
    title: str
    summary: str = ""
    heading: str = ""


class HighlightItem(BaseModel):
    exact: str
    note: str | None = "重点提炼"
    color: str = "yellow"


class ChapterMeta(BaseModel):
    summary: str = ""
    knowledge_points: list[KPItem] = []
    highlights: list[HighlightItem] = []


def parse_chapter_output(raw: str) -> tuple[str, ChapterMeta | None]:
    """返回 (正文 markdown, 元数据|None)。元数据解析失败不致命。"""
    if META_SEPARATOR not in raw:
        return raw.strip(), None
    # rfind 取最后一次出现：正文里若碰巧出现分隔符字样，不会截断正文
    body, meta_part = raw.rsplit(META_SEPARATOR, 1)
    meta_part = meta_part.strip()
    try:
        meta = ChapterMeta.model_validate(extract_json(meta_part))
    except Exception:
        logger.warning("章节 META 解析失败（原文前 200 字符）：%r", meta_part[:200])
        return body.strip(), None
    return body.strip(), meta
