"""自有 Markdown 导入 API（PRD 实现备注 12）。

POST /api/courses/import/analyze  上传 md → 章节切分预览（+LLM 修饰课程标题）
POST /api/courses/import          按确认的切片创建课程（原文归档 + 知识点提取 + 自动出卡）
"""
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models import Course, Document, KnowledgePoint, ReviewCard, Section
from app.models.base import utcnow_iso
from app.schemas.common import OutlineItem
from app.schemas.course import CourseOut
from app.services.docparser import parse_blocks
from app.services.generation.indexing import rebuild_sections
from app.services.generation.knowledge import ChapterMeta
from app.services.imports import (
    MAX_FILES,
    MAX_FILE_BYTES,
    MD_EXTENSIONS,
    decode_text,
    detect_chapters,
    safe_filename,
    slice_text,
)
from app.services.llm import (
    OpenAICompatAdapter,
    create_adapter_from_settings,
    get_llm_temperature,
)
from app.services.prompt import render_prompt
from app.services.review import get_preferences

logger = logging.getLogger(__name__)
router = APIRouter(tags=["imports"])


class ImportChapterSpec(BaseModel):
    file_index: int
    title: str
    start_line: int
    end_line: int

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("章节标题为空")
        return v


class ImportSpec(BaseModel):
    title: str
    chapters: list[ImportChapterSpec]

    @field_validator("chapters")
    @classmethod
    def _non_empty(cls, v: list[ImportChapterSpec]) -> list[ImportChapterSpec]:
        if not v:
            raise ValueError("至少需要一个章节")
        return v


class ImportTitleLLM(BaseModel):
    title: str


async def _read_uploads(files: list[UploadFile]) -> tuple[list[str], list[str]]:
    """返回 (texts, safe_names)。校验数量/大小/扩展名。"""
    if not files:
        raise HTTPException(status_code=400, detail="请选择至少一个 Markdown 文件")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"一次最多导入 {MAX_FILES} 个文件")
    texts: list[str] = []
    names: list[str] = []
    for f in files:
        name = safe_filename(f.filename or "document.md")
        if not name.lower().endswith(MD_EXTENSIONS):
            raise HTTPException(
                status_code=400, detail=f"仅支持 Markdown 文件（.md 等），收到：{name}"
            )
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail=f"文件过大（上限 5MB）：{name}")
        texts.append(decode_text(data))
        names.append(name)
    return texts, names


async def _llm_title(db: AsyncSession, chapter_titles: list[str]) -> str | None:
    """LLM 修饰课程标题；未配置/失败返回 None（降级为文件名）。

    导入本身不依赖 LLM，这里捕获一切异常：LLM 层任何故障都不允许让导入 500。
    """
    try:
        adapter: OpenAICompatAdapter = await create_adapter_from_settings(db, scene="generation")
        listing = "\n".join(f"- {t}" for t in chapter_titles[:40])
        result = await adapter.chat_json(
            [{"role": "user", "content": render_prompt("import_title", CHAPTERS=listing)}],
            ImportTitleLLM,
        )
        return result.title.strip() or None
    except Exception as e:
        logger.warning("import title suggestion skipped: %r", e)
        return None


async def _extract_kp(
    db: AsyncSession, adapter: OpenAICompatAdapter, content: str
) -> ChapterMeta | None:
    try:
        temperature = await get_llm_temperature(db)
        return await adapter.chat_json(
            [
                {
                    "role": "user",
                    "content": render_prompt("import_extract", CONTENT=content[:24_000]),
                }
            ],
            ChapterMeta,
            temperature=temperature,
        )
    except Exception as e:
        logger.warning("import kp extraction skipped: %r", e)
        return None


@router.post("/courses/import/analyze")
async def import_analyze(
    files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)
):
    texts, names = await _read_uploads(files)

    chapters: list[dict] = []
    for i, md in enumerate(texts):
        chapters.extend(detect_chapters(md, file_index=i, filename=names[i]))
    if not chapters:
        raise HTTPException(status_code=400, detail="未能从文件中识别出任何内容")

    llm_available = True
    llm_title = None
    try:
        await create_adapter_from_settings(db)
    except Exception:  # 未配置或读取配置失败 → 视为不可用，机械切章不受影响
        llm_available = False
    if llm_available:
        llm_title = await _llm_title(db, [c["title"] for c in chapters])

    fallback_title = (
        names[0].rsplit(".", 1)[0] if len(names) == 1 else f"导入课程（{len(names)} 个文件）"
    )
    return {
        "title": llm_title or fallback_title,
        "title_from_llm": llm_title is not None,
        "llm_available": llm_available,
        "files": [{"name": n} for n in names],
        "chapters": chapters,
    }


@router.post("/courses/import", response_model=CourseOut)
async def import_confirm(
    files: list[UploadFile] = File(...),
    spec: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    texts, names = await _read_uploads(files)
    try:
        spec_obj = ImportSpec.model_validate_json(spec)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导入参数无效：{e}")

    prefs = await get_preferences(db)
    auto_cards = bool(prefs.get("auto_create_cards", True))
    adapter: OpenAICompatAdapter | None = None
    try:
        adapter = await create_adapter_from_settings(db, scene="generation")
    except Exception:  # 未配置 LLM：跳过知识点提取，导入本身仍可用
        adapter = None

    course = Course(
        title=spec_obj.title.strip() or "导入课程",
        topic=f"导入自：{'、'.join(names)}",
        outline="[]",
        status="ready",
    )
    db.add(course)
    await db.flush()

    # 原件归档（用户磁盘上的源文件只读不写）
    originals_dir = settings.courses_dir / course.id / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)

    outline_items: list[OutlineItem] = []
    kp_extracted = 0
    for j, ch in enumerate(spec_obj.chapters):
        if ch.file_index < 0 or ch.file_index >= len(texts):
            raise HTTPException(status_code=400, detail="章节引用的文件不存在")
        content = slice_text(texts[ch.file_index], ch.start_line, ch.end_line)
        if not content.strip():
            raise HTTPException(status_code=400, detail=f"章节「{ch.title}」内容为空")

        doc = Document(
            course_id=course.id,
            chapter_index=j + 1,
            title=ch.title,
            version=1,
            status="done",
            source="imported",
        )
        db.add(doc)
        await db.flush()

        doc_dir = settings.courses_dir / course.id / doc.id
        doc_dir.mkdir(parents=True, exist_ok=True)
        current = doc_dir / "current.md"
        current.write_text(content, encoding="utf-8")
        doc.file_path = current.relative_to(settings.data_dir).as_posix()

        await rebuild_sections(db, doc, content, 1)

        # 大纲要点：章内的二级标题
        blocks = parse_blocks(content)
        points = [
            b.text
            for b in blocks
            if b.block_type == "heading"
            and (len(b.raw) - len(b.raw.lstrip("#"))) == 2
        ][:8]
        outline_items.append(OutlineItem(index=j + 1, title=ch.title, points=points))

        # 知识点提取 + 自动出卡（LLM 不可用时静默跳过）
        if adapter is not None:
            meta = await _extract_kp(db, adapter, content)
            if meta:
                doc.summary = meta.summary
                kp_extracted += len(meta.knowledge_points)
                rows = (
                    await db.scalars(
                        select(Section).where(Section.document_id == doc.id)
                    )
                ).all()
                section_by_heading: dict[str, str] = {}
                for row in rows:
                    hp = json.loads(row.heading_path)
                    if hp:
                        section_by_heading.setdefault(hp[-1], row.id)
                for item in meta.knowledge_points:
                    sec_ids = (
                        [section_by_heading[item.heading]]
                        if item.heading and item.heading in section_by_heading
                        else []
                    )
                    kp = KnowledgePoint(
                        document_id=doc.id,
                        title=item.title,
                        summary=item.summary,
                        section_ids=json.dumps(sec_ids, ensure_ascii=False),
                    )
                    db.add(kp)
                    await db.flush()
                    if auto_cards:
                        db.add(
                            ReviewCard(
                                source_type="knowledge_point",
                                knowledge_point_id=kp.id,
                                front=f"请解释：{item.title}",
                                back=f"{item.summary}\n\n（来自《{course.title}》· 导入文档）",
                                state="new",
                            )
                        )

    course.outline = json.dumps([o.model_dump() for o in outline_items], ensure_ascii=False)
    course.updated_at = utcnow_iso()

    for i, name in enumerate(names):
        (originals_dir / f"{i:02d}_{name}").write_text(texts[i], encoding="utf-8")

    await db.commit()
    logger.info(
        "imported course %s: %d chapters, %d knowledge points",
        course.id,
        len(outline_items),
        kp_extracted,
    )
    return CourseOut.model_validate(course)
