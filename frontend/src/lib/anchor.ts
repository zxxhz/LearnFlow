// 划线锚定核心（PRD §9）：
// - 创建：DOM 选区 → (section_id, exact, prefix, suffix, start/end_offset)
// - 渲染：在块文本中定位标注（精确 → 模糊），产出高亮分段
import DiffMatchPatch from "diff-match-patch";
import type { Annotation } from "./types";

const CONTEXT_CHARS = 32;

export interface AnchorRange {
  section_id: string;
  exact: string;
  prefix: string;
  suffix: string;
  start_offset: number;
  end_offset: number;
}

export interface LocatedRange {
  start: number;
  end: number;
  confidence: "exact" | "fuzzy";
}

/** 取包含选区的块元素（带 data-section-id）；跨块选区返回 null。 */
function selectionBlock(): { block: HTMLElement; range: Range } | null {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount !== 1) return null;
  const range = sel.getRangeAt(0);
  const toEl = (n: Node) =>
    n.nodeType === Node.TEXT_NODE
      ? n.parentElement
      : (n as HTMLElement);
  const startBlock = toEl(range.startContainer)?.closest(
    "[data-section-id]"
  ) as HTMLElement | null;
  const endBlock = toEl(range.endContainer)?.closest("[data-section-id]") as HTMLElement | null;
  if (!startBlock || startBlock !== endBlock) return null; // 不支持跨块（PRD FR-3.1）
  if (!range.toString().trim()) return null;
  return { block: startBlock, range };
}

function textLengthTo(block: HTMLElement, container: Node, offset: number): number {
  const r = document.createRange();
  r.selectNodeContents(block);
  try {
    r.setEnd(container, offset);
  } catch {
    return 0;
  }
  return r.toString().length;
}

/** 从当前 DOM 选区构造锚定五元组。 */
export function anchorFromSelection(): AnchorRange | null {
  const hit = selectionBlock();
  if (!hit) return null;
  const { block, range } = hit;
  const sectionId = block.dataset.sectionId!;
  const blockText = blockTextOf(block);
  const start = textLengthTo(block, range.startContainer, range.startOffset);
  const end = textLengthTo(block, range.endContainer, range.endOffset);
  if (end <= start) return null;
  const exact = blockText.slice(start, end);
  if (!exact.trim()) return null;
  return {
    section_id: sectionId,
    exact,
    prefix: blockText.slice(Math.max(0, start - CONTEXT_CHARS), start),
    suffix: blockText.slice(end, end + CONTEXT_CHARS),
    start_offset: start,
    end_offset: end,
  };
}

export function blockTextOf(block: HTMLElement): string {
  return block.textContent ?? "";
}

/**
 * 在块文本中定位一条标注（PRD §9.2）：
 * 1) offset 提示处精确匹配 2) 全文精确匹配 3) diff-match-patch 模糊匹配（阈值 0.8）
 */
export function locateAnnotation(
  blockText: string,
  a: Pick<Annotation, "exact" | "prefix" | "suffix" | "start_offset">
): LocatedRange | null {
  const exact = a.exact;
  if (!exact || !exact.trim()) return null;

  let idx = -1;
  const hint = a.start_offset;
  if (hint >= 0 && hint < blockText.length) {
    idx = blockText.indexOf(exact, Math.max(0, hint - 8));
  }
  if (idx < 0) idx = blockText.indexOf(exact);
  if (idx >= 0) return { start: idx, end: idx + exact.length, confidence: "exact" };

  const dmp = new DiffMatchPatch();
  dmp.Match_Threshold = 0.8;
  dmp.Match_Distance = 8000;
  const pos = dmp.match_main(blockText, exact, Math.min(hint, blockText.length));
  if (pos < 0) return null;
  const matched = blockText.slice(pos, pos + exact.length);
  const ratio = similarity(dmp, exact, matched);
  if (ratio >= 0.7) return { start: pos, end: pos + matched.length, confidence: "fuzzy" };
  return null;
}

function similarity(dmp: DiffMatchPatch, a: string, b: string): number {
  if (!a.length && !b.length) return 1;
  const diffs = dmp.diff_main(a, b);
  dmp.diff_cleanupSemantic(diffs);
  const lev = dmp.diff_levenshtein(diffs);
  return 1 - lev / Math.max(a.length, b.length);
}

export interface TextSegment {
  text: string;
  annotation?: Annotation;
  confidence?: "exact" | "fuzzy";
}

/**
 * 将块文本按标注切分为渲染分段。区间重叠时合并并保留最先遇到的标注
 * （多标注重叠属边界情况，M1 按此降级，PRD §13）。
 */
export function segmentBlockText(
  text: string,
  annotations: Annotation[]
): TextSegment[] {
  const located: { a: Annotation; range: LocatedRange }[] = [];
  for (const a of annotations) {
    const r = locateAnnotation(text, a);
    if (r) located.push({ a, range: r });
  }
  located.sort((x, y) => x.range.start - y.range.start);

  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const { a, range } of located) {
    const start = Math.max(range.start, cursor);
    if (start >= range.end) continue; // 完全被前一个覆盖
    if (start > cursor) segments.push({ text: text.slice(cursor, start) });
    segments.push({
      text: text.slice(start, range.end),
      annotation: a,
      confidence: range.confidence,
    });
    cursor = range.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments;
}
