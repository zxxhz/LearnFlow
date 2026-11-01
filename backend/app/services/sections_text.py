"""共享工具：按 section_id 取块全文（各服务统一入口，PRD §8.3）。"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Document, Section
from app.services.docparser import parse_blocks

logger = logging.getLogger(__name__)


def load_document_markdown(document: Document) -> str:
    if not document.file_path:
        return ""
    # 路径必须落在 courses/ 归档目录内：file_path 若被污染成 ../xx 等越界值，
    # 直接读文件会读到任意本地文件——不满足即拒绝并告警
    courses_dir = settings.courses_dir.resolve()
    path = (settings.data_dir / document.file_path).resolve()
    if not path.is_relative_to(courses_dir):
        logger.warning(
            "document %s file_path 越界，拒绝读取：%s", document.id, document.file_path
        )
        return ""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


async def get_section_text(
    db: AsyncSession, document: Document, section_id: str
) -> str:
    """返回块全文；索引缺失/文件缺失时退化为 120 字摘要。"""
    sec = (
        await db.scalars(
            select(Section).where(
                Section.document_id == document.id, Section.id == section_id
            )
        )
    ).first()
    if sec is None:
        return ""
    blocks = parse_blocks(load_document_markdown(document))
    if sec.order_index < len(blocks):
        return blocks[sec.order_index].text
    return sec.text_excerpt
