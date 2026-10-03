"""大纲生成（PRD §10.3 第①步）。"""
from pydantic import BaseModel, field_validator

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import OutlineItem
from app.schemas.course import CourseCreate
from app.services.llm import OpenAICompatAdapter
from app.services.prompt import render_prompt


class OutlineChapterLLM(BaseModel):
    title: str
    points: list[str] = []

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("章节标题为空")
        return v


class OutlineLLM(BaseModel):
    title: str
    chapters: list[OutlineChapterLLM]

    @field_validator("chapters")
    @classmethod
    def _chapters(cls, v: list[OutlineChapterLLM]) -> list[OutlineChapterLLM]:
        if not v:
            raise ValueError("大纲为空")
        return v


async def generate_outline(
    db: AsyncSession, adapter: OpenAICompatAdapter, req: CourseCreate
) -> tuple[str, list[OutlineItem]]:
    count = (
        f"{req.chapter_count} 章左右"
        if req.chapter_count
        else "根据主题规模自定（一般 5-12 章）"
    )
    prompt = render_prompt(
        "outline",
        TOPIC=req.topic,
        LEVEL=req.level or "（未填写）",
        SCOPE=req.scope or "（未填写）",
        CHAPTER_COUNT=count,
    )
    result: OutlineLLM = await adapter.chat_json(
        [{"role": "user", "content": prompt}], OutlineLLM
    )
    outline = [
        OutlineItem(index=i + 1, title=c.title, points=[p for p in c.points if p.strip()])
        for i, c in enumerate(result.chapters)
    ]
    return result.title.strip() or req.topic, outline
