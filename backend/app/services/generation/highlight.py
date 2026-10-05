"""生成章节时自动划重点：从模型元数据提取或根据正文重点提炼，锚定至 Section 并生成 Annotation 与 Conversation。"""
from __future__ import annotations

import html
import logging
import re
from typing import Sequence

from markdown_it import MarkdownIt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Annotation, Conversation, Document, Message, Section
from app.services.docparser import ParsedBlock, parse_blocks
from app.services.generation.knowledge import HighlightItem, KPItem

logger = logging.getLogger(__name__)
_md = MarkdownIt("js-default")

# 重点标注保留前缀/后缀上下文长度
CONTEXT_CHARS = 32
# 章节自动划重点最大数量与最小保障数量
MAX_AUTO_HIGHLIGHTS = 6
MIN_AUTO_HIGHLIGHTS = 3


def get_block_plain_text(raw: str) -> str:
    """提取与浏览器 DOM textContent 一致的纯文本。"""
    h = _md.render(raw)
    plain = html.unescape(re.sub(r"<[^>]+>", "", h))
    return plain.strip()


def clean_highlight_text(text: str) -> str:
    """去除 Markdown 行内格式与外围多余符号。"""
    t = re.sub(r"[*_`#~]", "", text)
    t = t.strip(' \t\r\n"\'“”‘’')
    return re.sub(r"\s+", " ", t)


def _split_sentences(text: str) -> list[str]:
    """将文本切分为自然语句。"""
    parts = re.split(r"([。！？!?\n]+)", text)
    res: list[str] = []
    for i in range(0, len(parts) - 1, 2):
        s = (parts[i] + parts[i + 1]).strip()
        if s:
            res.append(s)
    if len(parts) % 2 == 1 and parts[-1].strip():
        res.append(parts[-1].strip())
    return res


def extract_fallback_candidates(
    blocks: list[ParsedBlock],
) -> list[tuple[str, str, str]]:
    """当模型未提供或划重点数量不足时，从正文提取加粗/避坑/核心法则语句。

    返回列表元素格式：(exact, note, color)
    """
    candidates: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for b in blocks:
        if b.block_type not in ("paragraph", "quote", "list"):
            continue
        plain = get_block_plain_text(b.raw)
        if not plain:
            continue

        # 1. 优先提取加粗重点（**...**）
        bolds = re.findall(r"\*\*([^*]+)\*\*", b.raw)
        for bold in bolds:
            clean = clean_highlight_text(bold)
            if len(clean) >= 8 and clean in plain and clean not in seen:
                note = "避坑要害" if any(w in clean or w in b.raw for w in ("⚠️", "避坑", "不要", "禁止", "切记")) else "重点提炼"
                color = "pink" if note == "避坑要害" else "yellow"
                candidates.append((clean, note, color))
                seen.add(clean)
            elif 3 <= len(clean) < 8:
                # 短加粗词提取所在整句
                for s in _split_sentences(plain):
                    s_clean = clean_highlight_text(s)
                    if clean in s_clean and 10 <= len(s_clean) <= 60 and s_clean not in seen:
                        candidates.append((s_clean, "核心概念", "yellow"))
                        seen.add(s_clean)
                        break

        # 2. 带有明确避坑/警示的完整语句
        if any(w in b.raw for w in ("⚠️", "避坑", "切记", "注意", "黄金法则")):
            for s in _split_sentences(plain):
                s_clean = clean_highlight_text(s)
                if (
                    any(k in s_clean for k in ("切记", "不要", "禁止", "避免", "未定义", "必须", "法则"))
                    and 8 <= len(s_clean) <= 80
                    and s_clean not in seen
                ):
                    candidates.append((s_clean, "避坑要害", "pink"))
                    seen.add(s_clean)

    return candidates


async def create_auto_highlights(
    db: AsyncSession,
    doc: Document,
    sections: Sequence[Section],
    raw_markdown: str,
    meta_highlights: list[HighlightItem] | None = None,
    knowledge_points: list[KPItem] | None = None,
) -> list[Annotation]:
    """为生成的文档自动生成划线重点并落库。"""
    if not sections or not raw_markdown.strip():
        return []

    parsed_blocks = parse_blocks(raw_markdown)
    block_map = {
        s.id: parsed_blocks[s.order_index]
        for s in sections
        if s.order_index < len(parsed_blocks)
    }
    plain_map = {
        sid: get_block_plain_text(b.raw)
        for sid, b in block_map.items()
    }

    # 1. 重新生成章节时：清理旧版本残留且未产生对话问答的自动划线
    existing_auto_anns = (
        await db.scalars(
            select(Annotation).where(
                Annotation.document_id == doc.id,
                Annotation.note.in_(["重点提炼", "核心概念", "避坑要害", "黄金法则", "关键结论"])
                | Annotation.note.startswith("重点"),
            )
        )
    ).all()
    for old_ann in existing_auto_anns:
        conv = (
            await db.scalars(
                select(Conversation).where(Conversation.annotation_id == old_ann.id)
            )
        ).first()
        if conv:
            has_msg = (
                await db.scalars(
                    select(Message).where(Message.conversation_id == conv.id)
                )
            ).first()
            if has_msg:
                continue  # 用户有过问答，保留
            await db.execute(delete(Conversation).where(Conversation.id == conv.id))
        await db.delete(old_ann)
    await db.flush()

    # 2. 收集候选划线列表：模型输出优先 + 文本加粗提炼兜底
    candidates: list[tuple[str, str, str]] = []
    if meta_highlights:
        for it in meta_highlights:
            clean = clean_highlight_text(it.exact)
            if clean:
                color = it.color if it.color in ("yellow", "green", "blue", "pink") else "yellow"
                candidates.append((clean, it.note or "重点提炼", color))

    if len(candidates) < MIN_AUTO_HIGHLIGHTS:
        fallbacks = extract_fallback_candidates(parsed_blocks)
        for fb in fallbacks:
            if not any(c[0] == fb[0] for c in candidates):
                candidates.append(fb)

    # 3. 逐个候选尝试锚定到最合适的小节
    # 记录各 section 已占用的 [start, end] 区间，避免同一块内划线重叠
    occupied_ranges: dict[str, list[tuple[int, int]]] = {s.id: [] for s in sections}
    created_anns: list[Annotation] = []

    # 优先在正文段落/引用/列表中寻找，跳过大标题
    candidate_sections = [
        s for s in sections
        if s.id in plain_map and s.block_type in ("paragraph", "quote", "list")
    ]
    # 若无则补充其他块
    if not candidate_sections:
        candidate_sections = [s for s in sections if s.id in plain_map]

    for exact_text, note, color in candidates:
        if len(created_anns) >= MAX_AUTO_HIGHLIGHTS:
            break
        if len(exact_text) < 6 or len(exact_text) > 120:
            continue

        matched = False
        for sec in candidate_sections:
            plain = plain_map.get(sec.id, "")
            idx = plain.find(exact_text)
            if idx < 0:
                continue

            end_idx = idx + len(exact_text)
            # 重叠检查
            is_overlap = any(
                max(idx, o_start) < min(end_idx, o_end)
                for o_start, o_end in occupied_ranges[sec.id]
            )
            if is_overlap:
                continue

            # 命中并构造五元组
            prefix = plain[max(0, idx - CONTEXT_CHARS) : idx]
            suffix = plain[end_idx : end_idx + CONTEXT_CHARS]

            ann = Annotation(
                document_id=doc.id,
                section_id=sec.id,
                version=doc.version,
                exact=exact_text,
                prefix=prefix,
                suffix=suffix,
                start_offset=idx,
                end_offset=end_idx,
                color=color,
                note=note,
                status="active",
            )
            db.add(ann)
            await db.flush()

            conv = Conversation(kind="annotation", annotation_id=ann.id)
            db.add(conv)

            occupied_ranges[sec.id].append((idx, end_idx))
            created_anns.append(ann)
            matched = True
            break

        if not matched:
            logger.debug("auto-highlight candidate could not be anchored: %s", exact_text[:30])

    await db.flush()
    logger.info("created %d auto-highlights for document %s", len(created_anns), doc.id)
    return created_anns
