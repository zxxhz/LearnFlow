// 高亮的 DOM 实现：在已渲染（KaTeX 之后）的块元素内，
// 按标注区间用 TreeWalker 切分文本节点并包裹 <mark>（PRD §9.2 渲染流程）。
import { locateAnnotation } from "../../lib/anchor";
import type { Annotation } from "../../lib/types";

export interface HighlightedAnn {
  annotation: Annotation;
  confidence: "exact" | "fuzzy";
}

/** 清除块内全部高亮（还原文本节点）。 */
export function removeHighlights(blockEl: HTMLElement): void {
  const marks = Array.from(blockEl.querySelectorAll("mark.hl"));
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  }
}

/** 在块内应用全部标注高亮。重复调用会先清除。 */
export function applyHighlights(
  blockEl: HTMLElement,
  annotations: Annotation[]
): HighlightedAnn[] {
  removeHighlights(blockEl);
  const text = blockEl.textContent ?? "";
  const applied: HighlightedAnn[] = [];
  for (const a of annotations) {
    if (a.status !== "active") continue;
    const range = locateAnnotation(text, a);
    if (!range) continue;
    if (wrapRange(blockEl, range.start, range.end, a)) {
      applied.push({ annotation: a, confidence: range.confidence });
    }
  }
  return applied;
}

function wrapRange(el: HTMLElement, start: number, end: number, a: Annotation): boolean {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let wrapped = false;
  let offset = 0;
  const targets: { node: Text; start: number; end: number }[] = [];
  let n: Node | null;
  while ((n = walker.nextNode())) {
    const len = n.textContent?.length ?? 0;
    const nodeStart = offset;
    const nodeEnd = offset + len;
    if (nodeEnd > start && nodeStart < end) {
      targets.push({
        node: n as Text,
        start: Math.max(0, start - nodeStart),
        end: Math.min(len, end - nodeStart),
      });
    }
    offset = nodeEnd;
  }
  for (const t of targets) {
    if (t.node.parentElement?.closest("mark.hl")) continue; // 重叠区间：先到先得
    let target = t.node;
    if (t.end < target.length) target.splitText(t.end);
    if (t.start > 0) target = target.splitText(t.start);
    const mark = document.createElement("mark");
    mark.className = `hl hl-${a.color}`;
    mark.dataset.annId = a.id;
    target.parentNode?.insertBefore(mark, target);
    mark.appendChild(target);
    wrapped = true;
  }
  return wrapped;
}
