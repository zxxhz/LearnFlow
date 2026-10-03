"""全局搜索：SQLite FTS5 词法检索（非向量方案，符合 PRD 非目标 4 的边界）。

索引随 rebuild_sections 同步维护；老库首次升级时在启动时回填一次。
"""
import json
import logging
import re

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Document, Section
from app.services.docparser import parse_blocks
from app.services.sections_text import load_document_markdown

logger = logging.getLogger(__name__)

_MD_NOISE = re.compile(r"[*_`>#\[\]()!]|```[\w]*\n?|\$\$?")


async def ensure_fts(db: AsyncSession) -> None:
    """建虚表（幂等）。"""
    await db.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts_sections USING fts5("
            "document_id UNINDEXED, section_id UNINDEXED, heading, body)"
        )
    )
    await db.commit()


async def sync_document_fts(db: AsyncSession, document_id: str, blocks_text: list[tuple[str, str, str]]) -> None:
    """把某文档的 (section_id, heading, body) 列表整体替换进 FTS。"""
    await db.execute(text("DELETE FROM fts_sections WHERE document_id = :d"), {"d": document_id})
    for sid, heading, body in blocks_text:
        await db.execute(
            text("INSERT INTO fts_sections (document_id, section_id, heading, body) VALUES (:d, :s, :h, :b)"),
            {"d": document_id, "s": sid, "h": heading, "b": body},
        )


def _clean(text_: str) -> str:
    return _MD_NOISE.sub(" ", text_)


async def reindex_document(db: AsyncSession, document: Document) -> None:
    """从正文文件重建该文档的 FTS 行（与 Section.order_index 对齐）。"""
    blocks = parse_blocks(load_document_markdown(document))
    bodies = [_clean(b.text)[:5000] for b in blocks]
    sections = (
        await db.scalars(
            select(Section).where(Section.document_id == document.id).order_by(Section.order_index)
        )
    ).all()
    payload = []
    for i, sec in enumerate(sections):
        body = bodies[i] if i < len(bodies) else _clean(sec.text_excerpt)[:5000]
        try:
            path = json.loads(sec.heading_path or "[]")
        except json.JSONDecodeError:
            path = []
        payload.append((sec.id, " > ".join(path[-3:]), body))
    await sync_document_fts(db, document.id, payload)


async def backfill_fts(db: AsyncSession) -> None:
    """老库升级回填：FTS 为空但已有章节内容时，全量重建一次。"""
    await ensure_fts(db)
    row = (
        await db.execute(text("SELECT count(*) FROM fts_sections"))
    ).scalar()
    if (row or 0) > 0:
        return
    docs = (await db.scalars(select(Document).where(Document.status == "done"))).all()
    for d in docs:
        try:
            await reindex_document(db, d)
        except Exception:  # noqa: BLE001 文件缺失等
            logger.warning("FTS 回填失败（跳过）：%s", d.id)
    await db.commit()


async def search(db: AsyncSession, query: str, limit: int = 30) -> list[dict]:
    await ensure_fts(db)
    # FTS5 查询语法容错：按词拆分 AND，引号包住防注入语法
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return []
    match = " AND ".join('"%s"' % t.replace('"', '""') for t in terms)
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT document_id, section_id, heading, snippet(fts_sections, 3, '<mark>', '</mark>', '…', 12) "
                    "FROM fts_sections WHERE fts_sections MATCH :q ORDER BY rank LIMIT :l"
                ),
                {"q": match, "l": limit},
            )
        ).all()
    except Exception:  # noqa: BLE001 语法不支持等
        return []

    docs = {d.id: d for d in (await db.scalars(select(Document))).all()}
    courses = {c.id: c for c in (await db.scalars(select(Course))).all()}
    results = []
    for document_id, section_id, heading, snippet in rows:
        d = docs.get(document_id)
        if d is None:
            continue
        c = courses.get(d.course_id)
        results.append(
            {
                "course_id": d.course_id,
                "course_title": c.title if c else "",
                "document_id": document_id,
                "document_title": d.title,
                "section_id": section_id,
                "heading": heading,
                "snippet": snippet,
            }
        )
    return results
