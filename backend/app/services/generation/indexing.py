"""Section 派生索引的构建与重建（PRD §8.3）。"""
import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Annotation, Document, Section
from app.services.anchoring import OldSection, align_ids
from app.services.docparser import ParsedBlock, content_hash, parse_blocks

logger = logging.getLogger(__name__)


def build_heading_path(blocks: list[ParsedBlock], upto: int) -> list[str]:
    """前 upto 个块构成的标题栈（h1..h6）。"""
    stack: dict[int, str] = {}
    path: list[str] = []
    for b in blocks[:upto]:
        if b.block_type != "heading":
            continue
        # heading 的级别由 raw 的 # 数决定（ParsedBlock 未存级别，从 raw 推）
        level = len(b.raw) - len(b.raw.lstrip("#")) or 1
        stack[level] = b.text
        for deeper in [k for k in stack if k > level]:
            stack.pop(deeper)
        path = [stack[k] for k in sorted(stack)]
    return path


async def rebuild_sections(
    db: AsyncSession, document: Document, new_markdown: str, new_version: int
) -> list[Section]:
    """重建该文档的 Section 索引：旧块 ID 尽力继承；标注 orphan/恢复由 sweep 完成。

    返回新插入的 Section 行（已 flush，含 id）。
    """
    old_rows = (
        await db.scalars(
            select(Section)
            .where(Section.document_id == document.id)
            .order_by(Section.order_index)
        )
    ).all()
    old = [
        OldSection(id=r.id, content_hash=r.content_hash, text=r.text_excerpt)
        for r in old_rows
    ]
    new_blocks = parse_blocks(new_markdown)
    inherited = align_ids(old, new_blocks)

    await db.execute(delete(Section).where(Section.document_id == document.id))
    await db.flush()

    rows: list[Section] = []
    for i, nb in enumerate(new_blocks):
        inherited_id = inherited[i]
        # 继承旧 ID 或不传 id（由模型 default 生成新 UUID）
        row = Section(
            **(
                {"id": inherited_id}
                if inherited_id
                else {}
            ),
            document_id=document.id,
            version=new_version,
            order_index=i,
            block_type=nb.block_type,
            heading_path=json.dumps(build_heading_path(new_blocks, i), ensure_ascii=False),
            content_hash=content_hash(nb.text),
            text_excerpt=nb.text[:120],
        )
        db.add(row)
        rows.append(row)
    await db.flush()

    # orphan 判定：section_id 不在新集合 → orphan；重新落入 → 恢复 active（PRD §9.2）
    valid_ids = {r.id for r in rows}
    anns = (
        await db.scalars(select(Annotation).where(Annotation.document_id == document.id))
    ).all()
    for a in anns:
        if a.section_id in valid_ids:
            if a.status != "active":
                a.status = "active"
        else:
            a.status = "orphan"
    await db.flush()

    # 全文搜索索引同步（FTS5，幂等替换该文档的全部行）
    from app.services.search import ensure_fts, sync_document_fts

    await ensure_fts(db)
    try:
        await sync_document_fts(
            db,
            document.id,
            [
                (r.id, " > ".join(json.loads(r.heading_path)[-3:]), nb.text[:5000])
                for r, nb in zip(rows, new_blocks)
            ],
        )
    except Exception:  # noqa: BLE001  搜索索引失败不影响主流程
        logger.warning("FTS 同步失败（跳过）：%s", document.id, exc_info=True)

    logger.info(
        "rebuilt sections for %s: %d blocks (v%d)", document.id, len(rows), new_version
    )
    return rows
