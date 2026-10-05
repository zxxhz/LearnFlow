"""章节输出解析：正文 + <LEARNFLOW_META> 分隔符后的 JSON 元数据（PRD 实现备注 5）。"""
import json
from pydantic import BaseModel

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
    body, _, meta_part = raw.partition(META_SEPARATOR)
    meta_part = meta_part.strip()
    # 兼容模型把 JSON 包进代码块的情况
    if meta_part.startswith("```"):
        meta_part = meta_part.strip("`")
        if meta_part.startswith("json"):
            meta_part = meta_part[4:]
        meta_part = meta_part.strip()
    try:
        meta = ChapterMeta.model_validate(json.loads(meta_part))
    except Exception:
        return body.strip(), None
    return body.strip(), meta
