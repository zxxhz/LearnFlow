"""文档块级解析的**唯一权威实现**（PRD §8.3）。

前端 src/lib/markdown.ts 用 markdown-it（默认预设）实现了同规则解析，
两侧分类规则必须保持一致（7 种 block_type，hr/html 等一致跳过）。
generation 索引、答疑上下文、费曼上下文都从本模块取块。
"""
import hashlib
import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

_md = MarkdownIt("js-default")

BLOCK_TYPES = ("heading", "paragraph", "code", "list", "table", "quote", "math")


@dataclass
class ParsedBlock:
    block_type: str
    line_start: int  # 0-based，含（与 markdown-it token.map 一致）
    line_end: int  # 0-based，不含
    text: str  # 归一化纯文本（哈希与摘要依据）
    raw: str


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def parse_blocks(markdown: str) -> list[ParsedBlock]:
    normalized = markdown.replace("\r\n", "\n")
    lines = normalized.split("\n")
    tokens = _md.parse(normalized, {})
    blocks: list[ParsedBlock] = []

    inline_tokens = [
        tk
        for tk in tokens
        if tk.type == "inline" and tk.map is not None
    ]

    for i, t in enumerate(tokens):
        if t.level != 0 or t.nesting not in (0, 1) or t.map is None:
            continue
        s, e = t.map

        if t.type == "heading_open":
            typ = "heading"
        elif t.type == "fence":
            typ = "code"
        elif t.type == "table_open":
            typ = "table"
        elif t.type == "blockquote_open":
            typ = "quote"
        elif t.type in ("bullet_list_open", "ordered_list_open"):
            typ = "list"
        elif t.type == "paragraph_open":
            inline = tokens[i + 1].content if i + 1 < len(tokens) else ""
            stripped = inline.strip()
            typ = (
                "math"
                if stripped.startswith("$$") and stripped.endswith("$$")
                else "paragraph"
            )
        else:
            continue  # hr / html_block 等与前端一致跳过

        raw = "\n".join(lines[s:e])
        if typ == "code":
            text = raw
        else:
            parts = [
                tk.content
                for tk in inline_tokens
                if tk.map[0] >= s and tk.map[1] <= e
            ]
            text = normalize_text(" ".join(parts)) or normalize_text(raw)
        blocks.append(ParsedBlock(typ, s, e, text, raw))

    return blocks
