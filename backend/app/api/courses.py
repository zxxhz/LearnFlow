import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Course, Document
from app.models.base import utcnow_iso
from app.schemas.common import OutlineItem
from app.schemas.course import (
    ChapterProgress,
    CourseCreate,
    CourseDetailOut,
    CourseListItem,
    CourseOut,
    CourseSettingsUpdate,
    OutlineUpdate,
)
from app.services.generation import pipeline
from app.services.generation.outline import generate_outline
from app.services.llm import create_adapter_from_settings

router = APIRouter(prefix="/courses", tags=["courses"])


async def _get_course(db: AsyncSession, course_id: str) -> Course:
    course = await db.get(Course, course_id)
    if course is None or course.status == "archived":
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def _progress_list(docs: list[Document]) -> list[ChapterProgress]:
    return [
        ChapterProgress(
            document_id=d.id,
            chapter_index=d.chapter_index,
            title=d.title,
            status=d.status,
            version=d.version,
            error=d.error,
        )
        for d in sorted(docs, key=lambda x: x.chapter_index)
    ]


@router.post("")
async def create_course(body: CourseCreate, db: AsyncSession = Depends(get_db)):
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="请填写学习主题")
    adapter = await create_adapter_from_settings(db)  # 未配置 → LLMError → 400
    title, outline = await generate_outline(db, adapter, body)
    course = Course(
        title=title,
        topic=body.topic,
        level=body.level,
        scope=body.scope,
        chapter_count=body.chapter_count,
        outline=json.dumps([o.model_dump() for o in outline], ensure_ascii=False),
        status="draft",
    )
    db.add(course)
    await db.commit()
    return {
        "course": CourseOut.model_validate(course),
        "outline": [o.model_dump() for o in outline],
    }


@router.put("/{course_id}/outline", response_model=CourseOut)
async def save_outline(
    course_id: str, body: OutlineUpdate, db: AsyncSession = Depends(get_db)
):
    course = await _get_course(db, course_id)
    if not body.outline:
        raise HTTPException(status_code=400, detail="大纲不能为空")
    items = [
        OutlineItem(index=i + 1, title=o.title.strip(), points=[p for p in o.points if p.strip()])
        for i, o in enumerate(body.outline)
    ]
    course.outline = json.dumps([o.model_dump() for o in items], ensure_ascii=False)
    course.updated_at = utcnow_iso()
    await db.commit()
    return CourseOut.model_validate(course)


def _outline_matches(docs: list[Document], outline: list[dict]) -> bool:
    if len(docs) != len(outline):
        return False
    by_idx = {d.chapter_index: d for d in docs}
    for o in outline:
        d = by_idx.get(o.get("index"))
        if d is None or d.title != o.get("title"):
            return False
    return True


def _create_documents(db: AsyncSession, course: Course, outline: list[dict]) -> None:
    for o in outline:
        db.add(
            Document(
                course_id=course.id,
                chapter_index=int(o.get("index", 0)),
                title=o.get("title", ""),
                status="pending",
            )
        )


@router.post("/{course_id}/generate", response_model=CourseOut)
async def generate(course_id: str, db: AsyncSession = Depends(get_db)):
    course = await _get_course(db, course_id)
    if pipeline.is_running(course_id):
        raise HTTPException(status_code=409, detail="该课程的生成任务正在进行中")
    if not course.outline:
        raise HTTPException(status_code=400, detail="请先保存大纲")
    outline = json.loads(course.outline)
    docs = (
        await db.scalars(select(Document).where(Document.course_id == course_id))
    ).all()

    if not docs:
        _create_documents(db, course, outline)
    elif not _outline_matches(docs, outline):
        # 大纲已变更 → 重建模式：清空派生数据（PRD FR-1.2/FR-1.5）
        await pipeline.purge_course_data(db, course)
        _create_documents(db, course, outline)
    else:
        # 续传模式：仅重置未完成章
        for d in docs:
            if d.status in ("failed", "generating"):
                d.status = "pending"
                d.error = None

    course.status = "generating"
    course.updated_at = utcnow_iso()
    await db.commit()
    pipeline.start_course_generation(course_id)
    return CourseOut.model_validate(course)


@router.get("", response_model=list[CourseListItem])
async def list_courses(db: AsyncSession = Depends(get_db)):
    courses = (
        await db.scalars(
            select(Course).where(Course.status != "archived").order_by(Course.updated_at.desc())
        )
    ).all()
    docs = (await db.scalars(select(Document))).all()
    items = []
    for c in courses:
        mine = [d for d in docs if d.course_id == c.id]
        item = CourseListItem.model_validate(c)
        item.done_chapters = sum(1 for d in mine if d.status == "done")
        item.total_chapters = len(mine)
        items.append(item)
    return items


@router.patch("/{course_id}", response_model=CourseOut)
async def update_course(course_id: str, body: CourseSettingsUpdate, db: AsyncSession = Depends(get_db)):
    """课程级覆盖项（PRD FR-5.1：可在课程设置中关闭自动出卡）。"""
    course = await _get_course(db, course_id)
    merged = json.loads(course.course_settings or "{}")
    if body.auto_create_cards is not None:
        merged["auto_create_cards"] = body.auto_create_cards
    course.course_settings = json.dumps(merged, ensure_ascii=False)
    course.updated_at = utcnow_iso()
    await db.commit()
    return CourseOut.model_validate(course)


@router.get("/{course_id}", response_model=CourseDetailOut)
async def get_course(course_id: str, db: AsyncSession = Depends(get_db)):
    course = await _get_course(db, course_id)
    docs = (
        await db.scalars(
            select(Document).where(Document.course_id == course_id).order_by(Document.chapter_index)
        )
    ).all()
    out = CourseDetailOut.model_validate(course)
    out.documents = _progress_list(list(docs))
    return out


@router.delete("/{course_id}")
async def delete_course(course_id: str, db: AsyncSession = Depends(get_db)):
    course = await _get_course(db, course_id)
    pipeline.cancel(course_id)
    await pipeline.purge_course_data(db, course)
    await db.delete(course)
    await db.commit()
    return {"ok": True}


@router.get("/{course_id}/progress")
async def progress(course_id: str, db: AsyncSession = Depends(get_db)):
    await _get_course(db, course_id)

    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    from app.core.db import async_session_factory

    queue = pipeline.subscribe(course_id)

    async def gen():
        try:
            async with async_session_factory() as s:
                docs = (
                    await s.scalars(
                        select(Document)
                        .where(Document.course_id == course_id)
                        .order_by(Document.chapter_index)
                    )
                ).all()
            snapshot = {
                "type": "snapshot",
                "documents": [p.model_dump() for p in _progress_list(list(docs))],
            }
            yield f"data: {_json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {_json.dumps(evt, ensure_ascii=False)}\n\n"
                    if evt.get("type") in ("course_done", "error"):
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            pipeline.unsubscribe(course_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")
