// 单块渲染：markdown HTML + KaTeX（同步）+ Shiki（代码，异步）+ 划线高亮
// 顺序约定：KaTeX 先于高亮（偏移以最终 textContent 为准，创建标注时同一 DOM）
import { useEffect, useMemo, useRef } from "react";
import renderMathInElement from "katex/contrib/auto-render";
import { codeToHtml } from "shiki";
import type { Annotation } from "../../lib/types";
import type { ParsedBlock } from "../../lib/markdown";
import { applyHighlights } from "./highlight";

const DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "\\[", right: "\\]", display: true },
  { left: "$", right: "$", display: false },
  { left: "\\(", right: "\\)", display: false },
];

interface Props {
  block: ParsedBlock;
  sectionId: string | undefined;
  annotations: Annotation[];
  activeAnnId: string | null;
  onOpenAnnotation: (a: Annotation) => void;
  flashSectionId: string | null;
}

function stripFence(raw: string): { lang: string; code: string } {
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const first = lines[0] ?? "";
  const lang = first.replace(/^```/, "").trim().split(/\s+/)[0] || "text";
  let end = lines.length;
  if ((lines[end - 1] ?? "").trim() === "```") end -= 1;
  return { lang, code: lines.slice(1, end).join("\n") };
}

export default function BlockView({
  block,
  sectionId,
  annotations,
  activeAnnId,
  onOpenAnnotation,
  flashSectionId,
}: Props) {
  const innerRef = useRef<HTMLDivElement>(null);
  const codeRef = useRef<HTMLDivElement>(null);
  const html = block.html;
  const annKey = useMemo(
    () => annotations.map((a) => `${a.id}:${a.status}:${a.color}:${a.exact.length}`).join("|"),
    [annotations]
  );
  const isCode = block.type === "code";
  const { lang, code } = useMemo(() => (isCode ? stripFence(block.raw) : { lang: "", code: "" }), [block.raw, isCode]);

  // KaTeX（非代码块，同步渲染）
  useEffect(() => {
    if (isCode || !innerRef.current) return;
    renderMathInElement(innerRef.current, { delimiters: DELIMITERS, throwOnError: false });
  }, [html, isCode]);

  // 划线高亮（KaTeX 之后按 textContent 偏移定位）
  useEffect(() => {
    const el = isCode ? codeRef.current : innerRef.current;
    if (!el || !sectionId) return;
    applyHighlights(el, annotations);
    // 激活标注闪示
    if (activeAnnId) {
      el.querySelector(`mark[data-ann-id="${activeAnnId}"]`)?.classList.add("hl-active");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html, annKey, isCode, activeAnnId, sectionId]);

  // Shiki（代码块，异步；失败静默降级为纯 pre）
  useEffect(() => {
    if (!isCode || !codeRef.current) return;
    let cancelled = false;
    const el = codeRef.current;
    el.classList.toggle("ann-code-flag", annotations.some((a) => a.status === "active"));
    codeToHtml(code, { lang: lang || "text", theme: "github-light" })
      .then((out) => {
        if (!cancelled) el.innerHTML = out;
      })
      .catch(() => {
        if (!cancelled) el.innerHTML = `<pre><code>${escapeHtml(code)}</code></pre>`;
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, lang, isCode, annKey]);

  const onClick = (e: React.MouseEvent) => {
    const target = (e.target as HTMLElement).closest("mark.hl") as HTMLElement | null;
    if (target?.dataset.annId) {
      const ann = annotations.find((a) => a.id === target.dataset.annId);
      if (ann) onOpenAnnotation(ann);
    }
  };

  if (!sectionId) {
    // 未对齐的块（罕见）：正常渲染但不可标注
    return isCode ? (
      <div ref={codeRef} className="code-block my-3" />
    ) : (
      <div className="doc-content" dangerouslySetInnerHTML={{ __html: html }} />
    );
  }

  const flash = flashSectionId === sectionId;

  if (isCode) {
    return (
      <div
        ref={codeRef}
        data-section-id={sectionId}
        className={`code-block my-3 ${flash ? "outline outline-2 outline-brand-400 rounded-lg" : ""}`}
        onClick={onClick}
      />
    );
  }

  return (
    <div
      ref={innerRef}
      data-section-id={sectionId}
      className={`doc-content ${flash ? "outline outline-2 outline-brand-400 rounded-lg" : ""}`}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={onClick}
    />
  );
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
