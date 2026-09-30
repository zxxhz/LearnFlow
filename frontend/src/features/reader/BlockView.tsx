// 单块渲染：markdown HTML + KaTeX（同步）+ Shiki（代码，动态加载）+ 划线高亮 + 代码运行（PRD §5.8）
// 顺序约定：KaTeX 先于高亮（偏移以最终 textContent 为准，创建标注时同一 DOM）
import { useEffect, useMemo, useRef } from "react";
import renderMathInElement from "katex/contrib/auto-render";
import type { Annotation, CodeExecution, ExecStatus } from "../../lib/types";
import type { ParsedBlock } from "../../lib/markdown";
import { applyHighlights } from "./highlight";

const DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "\\[", right: "\\]", display: true },
  { left: "$", right: "$", display: false },
  { left: "\\(", right: "\\)", display: false },
];

const RUNNABLE_LANGS = new Set(["python", "py", "python3", "cpp", "c++", "cxx", "cc"]);

const EXEC_BADGE: Record<ExecStatus, { label: string; cls: string }> = {
  success: { label: "✅ 运行成功", cls: "text-green-700" },
  runtime_error: { label: "❌ 运行出错", cls: "text-red-700" },
  timeout: { label: "⏱ 运行超时（10s 上限）", cls: "text-amber-700" },
  compile_error: { label: "🔧 编译失败", cls: "text-red-700" },
  compiler_missing: { label: "⚠️ 未安装编译器", cls: "text-amber-700" },
  error: { label: "❌ 沙箱异常", cls: "text-red-700" },
};

interface Props {
  block: ParsedBlock;
  sectionId: string | undefined;
  annotations: Annotation[];
  activeAnnId: string | null;
  onOpenAnnotation: (a: Annotation) => void;
  flashSectionId: string | null;
  execution: CodeExecution | null;
  running: boolean;
  runError: string;
  onRun: (sectionId: string, lang: string, code: string) => void;
}

function stripFence(raw: string): { lang: string; code: string } {
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const first = lines[0] ?? "";
  const lang = first.replace(/^```/, "").trim().split(/\s+/)[0] || "text";
  let end = lines.length;
  if ((lines[end - 1] ?? "").trim() === "```") end -= 1;
  return { lang, code: lines.slice(1, end).join("\n") };
}

function ExecResultPanel({ execution }: { execution: CodeExecution }) {
  const badge = EXEC_BADGE[execution.status] ?? EXEC_BADGE.error;
  return (
    <div className="mt-2 rounded-lg border border-gray-200 bg-gray-900/95 p-3 text-xs">
      <div className="mb-1.5 flex items-center gap-3">
        <span className={`font-medium ${badge.cls} text-gray-100`}>{badge.label}</span>
        <span className="text-gray-400">
          退出码 {execution.exit_code ?? "-"} · {execution.duration_ms ?? 0}ms ·{" "}
          {new Date(execution.created_at).toLocaleTimeString("zh-CN")}
        </span>
      </div>
      {execution.stdout && (
        <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded bg-black/40 p-2 font-mono text-[12px] leading-5 text-green-200">
          {execution.stdout}
        </pre>
      )}
      {execution.stderr && (
        <pre className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-black/40 p-2 font-mono text-[12px] leading-5 text-red-300">
          {execution.stderr}
        </pre>
      )}
    </div>
  );
}

export default function BlockView({
  block,
  sectionId,
  annotations,
  activeAnnId,
  onOpenAnnotation,
  flashSectionId,
  execution,
  running,
  runError,
  onRun,
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
  const runnable = isCode && RUNNABLE_LANGS.has(lang.toLowerCase());

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
    if (activeAnnId) {
      el.querySelector(`mark[data-ann-id="${activeAnnId}"]`)?.classList.add("hl-active");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html, annKey, isCode, activeAnnId, sectionId]);

  // Shiki（代码块：动态 import 拆 chunk，首次渲染代码块时才加载）
  useEffect(() => {
    if (!isCode || !codeRef.current) return;
    let cancelled = false;
    const el = codeRef.current;
    el.classList.toggle("ann-code-flag", annotations.some((a) => a.status === "active"));
    (async () => {
      try {
        const { codeToHtml } = await import("shiki");
        const out = await codeToHtml(code, { lang: lang || "text", theme: "github-light" });
        if (!cancelled) el.innerHTML = out;
      } catch {
        if (!cancelled) el.innerHTML = `<pre><code>${escapeHtml(code)}</code></pre>`;
      }
    })();
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
    return isCode ? (
      <div ref={codeRef} className="code-block my-3" />
    ) : (
      <div className="doc-content" dangerouslySetInnerHTML={{ __html: html }} />
    );
  }

  const flash = flashSectionId === sectionId;

  if (isCode) {
    return (
      <div className="relative my-3">
        {runnable && (
          <button
            onClick={() => onRun(sectionId, lang.toLowerCase(), code)}
            disabled={running}
            className="absolute right-2 top-2 z-10 rounded-md bg-green-700/90 px-2.5 py-1 text-xs font-medium text-white opacity-80 transition hover:opacity-100 disabled:opacity-50"
            title={lang === "" ? "" : `运行 ${lang} 代码（限时 10s）`}
          >
            {running ? "运行中…" : "▶ 运行"}
          </button>
        )}
        <div
          ref={codeRef}
          data-section-id={sectionId}
          className={`code-block ${flash ? "outline outline-2 outline-brand-400 rounded-lg" : ""}`}
          onClick={onClick}
        />
        {runError && <p className="mt-1 text-xs text-red-600">{runError}</p>}
        {execution && <ExecResultPanel execution={execution} />}
      </div>
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
