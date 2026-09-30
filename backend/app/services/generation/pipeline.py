"""逐章生成流水线（PRD §10.3）：任务注册表 + 进度事件总线 + 断点续生成。"""
import asyncio
import json
import logging
import shutil

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory
from app.models import (
    Annotation,
    CodeExecution,
    Conversation,
    Course,
    Document,
    FeynmanSession,
    KnowledgePoint,
    Message,
    ReviewCard,
    Section,
)
from app.models.base import utcnow_iso
from app.services.generation.indexing import rebuild_sections
from app.services.generation.knowledge import parse_chapter_output
from app.services.llm import create_adapter_from_settings, get_llm_temperature
from app.services.llm.errors import LLMError
from app.services.prompt import render_prompt
from app.services.review import get_preferences

logger = logging.getLogger(__name__)

# 课程级任务注册表：course_id -> Task（含单章重生成任务，同用课程 id 键）
_tasks: dict[str, asyncio.Task] = {}
# 进度事件总线：course_id -> 订阅队列集合（SSE 推送）
_subscribers: dict[str, set[asyncio.Queue]] = {}


def publish(course_id: str, evt: dict) -> None:
    for q in _subscribers.get(course_id, set()):
        q.put_nowait(evt)


def subscribe(course_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(course_id, set()).add(q)
    return q


def unsubscribe(course_id: str, q: asyncio.Queue) -> None:
    _subscribers.get(course_id, set()).discard(q)


def is_running(course_id: str) -> bool:
    t = _tasks.get(course_id)
    return t is not None and not t.done()


def cancel(course_id: str) -> None:
    t = _tasks.pop(course_id, None)
    if t and not t.done():
        t.cancel()


async def run_chapter(
    db: AsyncSession, course: Course, doc: Document, instruction: str | None = None
) -> None:
    """生成单章：LLM → 落盘 → 重建索引 → 知识点/出卡 → 状态推进。异常向上抛。"""
    doc.status = "generating"
    doc.error = None
    doc.updated_at = utcnow_iso()
    await db.commit()
    publish(course.id, {"type": "chapter_start", "index": doc.chapter_index, "title": doc.title})

    outline = json.loads(course.outline) if course.outline else []
    item = next((o for o in outline if o.get("index") == doc.chapter_index), None)
    points_text = (
        "\n".join(f"- {p}" for p in item.get("points", [])) if item else "（围绕章标题展开）"
    )
    prev_docs = (
        await db.scalars(
            select(Document)
            .where(
                Document.course_id == course.id,
                Document.chapter_index < doc.chapter_index,
                Document.status == "done",
            )
            .order_by(Document.chapter_index)
        )
    ).all()
    prev_summaries = (
        "\n".join(f"第{d.chapter_index}章 {d.title}：{d.summary or '（无摘要）'}" for d in prev_docs)
        or "（这是第一章）"
    )
    prefs = await get_preferences(db)
    prompt = render_prompt(
        "chapter_doc",
        INDEX=str(doc.chapter_index),
        COURSE_TITLE=course.title,
        COURSE_TOPIC=course.topic,
        CHAPTER_TITLE=doc.title,
        CHAPTER_POINTS=points_text,
        PREV_SUMMARIES=prev_summaries,
        LENGTH=str(int(prefs.get("chapter_length", 3000))),
    )
    if instruction:
        prompt += f"\n\n## 本次重新生成的额外要求\n{instruction}\n请在保持上述输出格式的前提下满足该要求。"

    adapter = await create_adapter_from_settings(db)
    temperature = await get_llm_temperature(db)
    raw = await adapter.chat([{"role": "user", "content": prompt}], temperature=temperature)
    body, meta = parse_chapter_output(raw)
    if not body.strip():
        raise LLMError("模型未返回正文内容")

    # 落盘：旧版本快照 → 新 current.md（PRD FR-1.5）
    doc_dir = settings.courses_dir / course.id / doc.id
    (doc_dir / "versions").mkdir(parents=True, exist_ok=True)
    current = doc_dir / "current.md"
    if current.exists() and doc.version >= 1:
        shutil.copy2(current, doc_dir / "versions" / f"v{doc.version}.md")
    current.write_text(body, encoding="utf-8")

    new_version = doc.version + 1
    sections = await rebuild_sections(db, doc, body, new_version)
    doc.file_path = current.relative_to(settings.data_dir).as_posix()
    doc.version = new_version
    doc.summary = meta.summary if meta else None
    doc.status = "done"
    doc.updated_at = utcnow_iso()

    # 知识点替换（连带其自动卡）+ heading → section 映射
    old_kps = (
        await db.scalars(select(KnowledgePoint).where(KnowledgePoint.document_id == doc.id))
    ).all()
    old_kp_ids = [k.id for k in old_kps]
    if old_kp_ids:
        await db.execute(
            delete(ReviewCard).where(
                ReviewCard.source_type == "knowledge_point",
                ReviewCard.knowledge_point_id.in_(old_kp_ids),
            )
        )
        await db.execute(delete(KnowledgePoint).where(KnowledgePoint.document_id == doc.id))

    section_by_heading: dict[str, str] = {}
    for s in sections:
        hp = json.loads(s.heading_path)
        if hp:
            section_by_heading.setdefault(hp[-1], s.id)

    auto_cards = bool(prefs.get("auto_create_cards", True))
    course_settings = json.loads(course.course_settings or "{}")
    if course_settings.get("auto_create_cards") is False:
        auto_cards = False

    if meta:
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
                        back=f"{item.summary}\n\n（来自《{course.title}》第{doc.chapter_index}章）",
                        state="new",
                    )
                )
    await db.commit()
    publish(
        course.id,
        {"type": "chapter_done", "index": doc.chapter_index, "title": doc.title, "document_id": doc.id},
    )


async def _mark_failed(db: AsyncSession, doc: Document, exc: Exception) -> None:
    doc.status = "failed"
    doc.error = getattr(exc, "message", None) or str(exc)
    doc.updated_at = utcnow_iso()
    await db.commit()


async def run_course(course_id: str) -> None:
    """顺序生成课程所有未完成章节（断点续生成：跳过 done）。"""
    try:
        async with async_session_factory() as db:
            course = await db.get(Course, course_id)
            if course is None:
                return
            docs = (
                await db.scalars(
                    select(Document)
                    .where(Document.course_id == course_id)
                    .order_by(Document.chapter_index)
                )
            ).all()
            for doc in docs:
                if doc.status == "done":
                    continue
                try:
                    await run_chapter(db, course, doc)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("chapter %s failed", doc.id)
                    await _mark_failed(db, doc, e)
                    publish(
                        course_id,
                        {"type": "chapter_failed", "index": doc.chapter_index, "error": doc.error},
                    )
            course.status = "ready"
            course.updated_at = utcnow_iso()
            await db.commit()
            publish(course_id, {"type": "course_done", "status": course.status})
    except asyncio.CancelledError:
        logger.info("course generation cancelled: %s", course_id)
    finally:
        _tasks.pop(course_id, None)


def start_course_generation(course_id: str) -> None:
    t = _tasks.get(course_id)
    if t is not None and not t.done():
        return
    _tasks[course_id] = asyncio.create_task(run_course(course_id))


async def queue_single_document(document_id: str, instruction: str | None) -> str:
    """单章重新生成：返回 course_id；课程任务在跑时抛 RuntimeError。"""
    async with async_session_factory() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            raise LookupError("文档不存在")
        course_id = doc.course_id
        if is_running(course_id):
            raise RuntimeError("该课程的生成任务正在进行中，请稍后再试")
        doc.status = "pending"
        doc.error = None
        await db.commit()

    async def _run() -> None:
        try:
            async with async_session_factory() as db:
                course = await db.get(Course, course_id)
                doc = await db.get(Document, document_id)
                if course is None or doc is None:
                    return
                try:
                    await run_chapter(db, course, doc, instruction)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("regenerate chapter %s failed", document_id)
                    await _mark_failed(db, doc, e)
                    publish(course_id, {"type": "chapter_failed", "index": doc.chapter_index, "error": doc.error})
                publish(course_id, {"type": "course_done", "status": course.status})
        finally:
            _tasks.pop(course_id, None)

    _tasks[course_id] = asyncio.create_task(_run())
    return course_id


async def resume_pending_generations() -> None:
    """应用启动时恢复中断的生成任务（main.py lifespan 延迟导入调用）。"""
    async with async_session_factory() as db:
        courses = (await db.scalars(select(Course).where(Course.status == "generating"))).all()
        course_ids = [c.id for c in courses]
        if course_ids:
            await db.execute(
                update(Document)
                .where(Document.course_id.in_(course_ids), Document.status == "generating")
                .values(status="pending")
            )
            await db.commit()
    for cid in course_ids:
        logger.info("resuming course generation: %s", cid)
        start_course_generation(cid)


async def purge_course_data(db: AsyncSession, course: Course) -> None:
    """删除课程的全部派生数据（文档/索引/标注/对话/复习卡/文件），保留课程行。"""
    docs = (
        await db.scalars(select(Document).where(Document.course_id == course.id))
    ).all()
    doc_ids = [d.id for d in docs]
    if doc_ids:
        kps = (
            await db.scalars(select(KnowledgePoint).where(KnowledgePoint.document_id.in_(doc_ids)))
        ).all()
        kp_ids = [k.id for k in kps]
        anns = (
            await db.scalars(select(Annotation).where(Annotation.document_id.in_(doc_ids)))
        ).all()
        ann_ids = [a.id for a in anns]
        sessions = (
            await db.scalars(select(FeynmanSession).where(FeynmanSession.document_id.in_(doc_ids)))
        ).all()
        session_conv_ids = [s.conversation_id for s in sessions]
        ann_conv_ids = [
            c.id
            for c in (
                await db.scalars(
                    select(Conversation).where(Conversation.annotation_id.in_(ann_ids))
                )
            ).all()
        ]
        conv_ids = list({*session_conv_ids, *ann_conv_ids})
        if conv_ids:
            await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        if session_conv_ids:
            await db.execute(delete(Conversation).where(Conversation.id.in_(session_conv_ids)))
        if ann_conv_ids:
            await db.execute(delete(Conversation).where(Conversation.id.in_(ann_conv_ids)))
        if sessions:
            await db.execute(
                delete(FeynmanSession).where(FeynmanSession.id.in_([s.id for s in sessions]))
            )
        if kp_ids or ann_ids:
            cond = []
            if kp_ids:
                cond.append(ReviewCard.knowledge_point_id.in_(kp_ids))
            if ann_ids:
                cond.append(ReviewCard.annotation_id.in_(ann_ids))
            from sqlalchemy import or_

            await db.execute(delete(ReviewCard).where(or_(*cond)))
        if ann_ids:
            await db.execute(delete(Annotation).where(Annotation.id.in_(ann_ids)))
        if kp_ids:
            await db.execute(delete(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids)))
        await db.execute(delete(Section).where(Section.document_id.in_(doc_ids)))
        await db.execute(delete(CodeExecution).where(CodeExecution.document_id.in_(doc_ids)))
        await db.execute(delete(Document).where(Document.id.in_(doc_ids)))
    shutil.rmtree(settings.courses_dir / course.id, ignore_errors=True)
