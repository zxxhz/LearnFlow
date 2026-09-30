"""自有 Markdown 导入（PRD 实现备注 12）：

- 智能识别：按文档顶层标题层级机械切章（≥2 个 h1 按 h1 切，否则 ≥2 个 h2 按 h2 切，
  否则整文件一章）；章内更低层级标题作为大纲要点。LLM 仅用于修饰课程标题与提取知识点。
- 原文保留：章节内容为原文的精确切片（仅统一换行用于行号定位），原件归档到
  courses/{cid}/originals/，用户磁盘上的源文件只读不写；导入文档禁用重新生成。
"""
import re
from dataclasses import dataclass

from app.services.docparser import parse_blocks

MAX_FILES = 20
MAX_FILE_BYTES = 5 * 1024 * 1024
MD_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd")


def decode_text(data: bytes) -> str:
    """中文 Windows 场景：优先 UTF-8，回退 GBK，最后替换式解码。"""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def normalize(md: str) -> str:
    return md.replace("\r\n", "\n").replace("\r", "\n")


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name or "document.md")


@dataclass
class HeadingHit:
    level: int
    title: str
    line_start: int


def _headings(lines: list[str]) -> list[HeadingHit]:
    hits: list[HeadingHit] = []
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            hits.append(HeadingHit(len(m.group(1)), m.group(2).strip(), i))
    return hits


def detect_chapters(markdown: str, file_index: int, filename: str) -> list[dict]:
    """返回章节切片（0-based 行号 [start, end)）与每章的大纲要点（次级标题）。"""
    md = normalize(markdown)
    lines = md.split("\n")
    headings = _headings(lines)

    split_level = 0
    h1 = [h for h in headings if h.level == 1]
    h2 = [h for h in headings if h.level == 2]
    if len(h1) >= 2:
        split_level = 1
    elif len(h2) >= 2:
        split_level = 2

    def points_between(start: int, end: int) -> list[str]:
        return [
            h.title
            for h in headings
            if h.level == split_level + 1 and start <= h.line_start < end
        ][:8] or [
            h.title
            for h in headings
            if h.level > split_level and start <= h.line_start < end
        ][:8]

    if split_level == 0:
        title = headings[0].title if headings else filename.rsplit(".", 1)[0]
        return [
            {
                "file_index": file_index,
                "title": title,
                "start_line": 0,
                "end_line": len(lines),
                "points": [h.title for h in headings[1:]][:8],
            }
        ]

    cuts = [h for h in headings if h.level == split_level]
    chapters: list[dict] = []

    # 首个切分标题之前的内容：非空则作为首章（标题取其首个标题或文件名）
    preamble_end = cuts[0].line_start
    if any(l.strip() for l in lines[:preamble_end]):
        preamble_title = next(
            (h.title for h in headings if h.line_start < preamble_end),
            filename.rsplit(".", 1)[0],
        )
        chapters.append(
            {
                "file_index": file_index,
                "title": preamble_title,
                "start_line": 0,
                "end_line": preamble_end,
                "points": points_between(0, preamble_end),
            }
        )

    for j, cut in enumerate(cuts):
        end = cuts[j + 1].line_start if j + 1 < len(cuts) else len(lines)
        chapters.append(
            {
                "file_index": file_index,
                "title": cut.title,
                "start_line": cut.line_start,
                "end_line": end,
                "points": points_between(cut.line_start, end),
            }
        )
    return chapters


def slice_text(markdown: str, start_line: int, end_line: int) -> str:
    """精确切片（analyze 与 confirm 使用同一 normalize，行号空间一致）。"""
    lines = normalize(markdown).split("\n")
    return "\n".join(lines[start_line:end_line]).strip("\n") + "\n"
