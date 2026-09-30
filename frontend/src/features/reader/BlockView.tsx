// 单块渲染：markdown HTML + KaTeX（同步）+ Shiki（代码，动态加载）+ 划线高亮 + 代码运行（PRD §5.8）
// 顺序约定：KaTeX 先于高亮（偏移以最终 textContent 为准，创建标注时同一 DOM）
// 代码块带头部栏：语言徽章区分（Python 绿 / C++ 靛 / Plot 紫）；可运行块支持力扣式编辑——
// 改代码 → 运行 → 后端按块持久化最后一次执行的代码，重开文档回显，可一键重置回原文
import { useEffect, useMemo, useRef, useState } from "react";
import renderMathInElement from "katex/contrib/auto-render";
import { api } from "../../lib/api";
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
const PLOT_LANGS = new Set(["plot", "math-plot", "绘图"]);

const EXEC_BADGE: Record<ExecStatus, { label: string; cls: string }> = {
  success: { label: "✅ 运行成功", cls: "text-green-700" },
  runtime_error: { label: "❌ 运行出错", cls: "text-red-700" },
  timeout: { label: "⏱ 运行超时（10s 上限）", cls: "text-amber-700" },
  compile_error: { label: "🔧 编译失败", cls: "text-red-700" },
  compiler_missing: { label: "⚠️ 未安装编译器", cls: "text-amber-700" },
  error: { label: "❌ 沙箱异常", cls: "text-red-700" },
};

// 语言徽章：视觉上区分代码块语言（也覆盖不可运行的普通代码块）
const LANG_BADGE: Record<string, { label: string; cls: string }> = {
  python: { label: "PYTHON", cls: "border-emerald-300 bg-emerald-50 text-emerald-700" },
  py: { label: "PYTHON", cls: "border-emerald-300 bg-emerald-50 text-emerald-700" },
  python3: { label: "PYTHON", cls: "border-emerald-300 bg-emerald-50 text-emerald-700" },
  cpp: { label: "C++", cls: "border-indigo-300 bg-indigo-50 text-indigo-700" },
  "c++": { label: "C++", cls: "border-indigo-300 bg-indigo-50 text-indigo-700" },
  cxx: { label: "C++", cls: "border-indigo-300 bg-indigo-50 text-indigo-700" },
  cc: { label: "C++", cls: "border-indigo-300 bg-indigo-50 text-indigo-700" },
  plot: { label: "PLOT", cls: "border-violet-300 bg-violet-50 text-violet-700" },
  "math-plot": { label: "PLOT", cls: "border-violet-300 bg-violet-50 text-violet-700" },
  绘图: { label: "PLOT", cls: "border-violet-300 bg-violet-50 text-violet-700" },
};
const LANG_FALLBACK = { label: "", cls: "border-gray-200 bg-gray-50 text-gray-500" };

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
  const [plotSvg, setPlotSvg] = useState<string>("");
  const [plotBusy, setPlotBusy] = useState(false);
  const [plotErr, setPlotErr] = useState("");
  // 力扣式编辑：draft 非空表示用户改过代码（运行即持久化，重开文档由 execution 回显）
  const [draft, setDraft] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editBuf, setEditBuf] = useState("");
  const adoptedExecId = useRef<string | null>(null);
  const html = block.html;
  const annKey = useMemo(
    () => annotations.map((a) => `${a.id}:${a.status}:${a.color}:${a.exact.length}`).join("|"),
    [annotations]
  );
  const isCode = block.type === "code";
  const { lang, code } = useMemo(() => (isCode ? stripFence(block.raw) : { lang: "", code: "" }), [block.raw, isCode]);
  const langKey = lang.toLowerCase();
  const runnable = isCode && RUNNABLE_LANGS.has(langKey);
  const plottable = isCode && PLOT_LANGS.has(langKey);
  const displayCode = draft ?? code;
  const badge = LANG_BADGE[langKey] ?? LANG_FALLBACK;

  // 回显上次执行的代码（力扣式：重开文档显示你上次提交的版本）
  useEffect(() => {
    if (!execution || adoptedExecId.current === execution.id) return;
    adoptedExecId.current = execution.id;
    if (!editing && draft === null && execution.code && execution.code !== code) {
      setDraft(execution.code);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execution]);

  const startEdit = () => {
    setEditBuf(displayCode);
    setEditing(true);
  };
  const finishEdit = () => {
    setEditing(false);
    setDraft(editBuf === code ? null : editBuf);
  };

  // 高数图形化（PRD 实现备注 14）：plot 块 → SymPy/Matplotlib 渲染 SVG
  const doPlot = async () => {
    if (plotBusy || !plottable) return;
    setPlotBusy(true);
    setPlotErr("");
    try {
      const res = await api.math.render({ expressions: code });
      setPlotSvg(res.svg);
    } catch (e) {
      setPlotErr((e as Error).message);
    } finally {
      setPlotBusy(false);
    }
  };

  // KaTeX（非代码块，同步渲染）
  useEffect(() => {
    if (isCode || !innerRef.current) return;
    renderMathInElement(innerRef.current, { delimiters: DELIMITERS, throwOnError: false });
  }, [html, isCode]);

  // 划线高亮（KaTeX 之后按 textContent 偏移定位；编辑态切换后重挂载需重算）
  useEffect(() => {
    const el = isCode ? codeRef.current : innerRef.current;
    if (!el || !sectionId) return;
    applyHighlights(el, annotations);
    if (activeAnnId) {
      el.querySelector(`mark[data-ann-id="${activeAnnId}"]`)?.classList.add("hl-active");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html, annKey, isCode, activeAnnId, sectionId, editing, displayCode]);

  // Shiki（代码块：动态 import 拆 chunk，首次渲染代码块时才加载）
  useEffect(() => {
    if (!isCode || editing || !codeRef.current) return;
    let cancelled = false;
    const el = codeRef.current;
    el.classList.toggle("ann-code-flag", annotations.some((a) => a.status === "active"));
    (async () => {
      try {
        const { codeToHtml } = await import("shiki");
        const out = await codeToHtml(displayCode, { lang: lang || "text", theme: "github-light" });
        if (!cancelled) el.innerHTML = out;
      } catch {
        if (!cancelled) el.innerHTML = `<pre><code>${escapeHtml(displayCode)}</code></pre>`;
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayCode, lang, isCode, annKey, editing]);

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
    const headerCls = "flex items-center justify-between gap-2 rounded-t-lg border border-b-0 border-gray-200 bg-gray-50 px-3 py-1.5";
    return (
      <div className="relative my-3">
        <div className={headerCls}>
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-widest ${badge.cls}`}
          >
            {badge.label || lang.toUpperCase() || "CODE"}
          </span>
          <div className="flex items-center gap-1.5">
            {draft !== null && !editing && (
              <>
                <span className="text-[10px] text-amber-600">已修改</span>
                <button
                  onClick={() => setDraft(null)}
                  className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-xs text-gray-600 transition hover:bg-gray-100"
                  title="放弃修改，恢复文档中的原始代码"
                >
                  ↺ 重置
                </button>
              </>
            )}
            {editing && (
              <>
                <button
                  onClick={finishEdit}
                  className="rounded-md bg-brand-600 px-2 py-0.5 text-xs font-medium text-white transition hover:bg-brand-700"
                  title="保存编辑（不运行）"
                >
                  ✓ 完成
                </button>
                <button
                  onClick={() => setEditing(false)}
                  className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-xs text-gray-600 transition hover:bg-gray-100"
                  title="放弃本次编辑"
                >
                  ✕ 取消
                </button>
              </>
            )}
            {!editing && runnable && (
              <button
                onClick={() => onRun(sectionId, langKey, displayCode)}
                disabled={running}
                className="rounded-md bg-green-700/90 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-green-700 disabled:opacity-50"
                title={`运行${draft !== null ? "修改后的" : ""} ${lang} 代码（限时 10s）`}
              >
                {running ? "运行中…" : "▶ 运行"}
              </button>
            )}
            {!editing && plottable && (
              <button
                onClick={doPlot}
                disabled={plotBusy}
                className="rounded-md bg-violet-700/90 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-violet-700 disabled:opacity-50"
                title="用 SymPy + Matplotlib 绘制函数图像（默认区间 [-10, 10]）"
              >
                {plotBusy ? "绘制中…" : "📐 绘图"}
              </button>
            )}
            {!editing && runnable && (
              <button
                onClick={startEdit}
                className="rounded-md border border-gray-200 bg-white px-2 py-0.5 text-xs text-gray-600 transition hover:bg-gray-100"
                title="编辑代码后运行（力扣式刷题）"
              >
                ✎ 编辑
              </button>
            )}
          </div>
        </div>
        {editing ? (
          <textarea
            value={editBuf}
            onChange={(e) => setEditBuf(e.target.value)}
            spellCheck={false}
            rows={Math.min(Math.max(editBuf.split("\n").length + 1, 6), 28)}
            className="w-full resize-y rounded-b-lg border border-t-0 border-gray-200 bg-white p-4 font-mono text-[13px] leading-6 text-gray-900 outline-none focus:ring-2 focus:ring-brand-400"
          />
        ) : (
          <div
            ref={codeRef}
            data-section-id={sectionId}
            className={`code-block with-header ${flash ? "outline outline-2 outline-brand-400" : ""}`}
            onClick={onClick}
          />
        )}
        {runError && <p className="mt-1 text-xs text-red-600">{runError}</p>}
        {plotErr && <p className="mt-1 text-xs text-red-600">{plotErr}</p>}
        {plotSvg && (
          <div className="mt-2 rounded-lg border border-gray-200 bg-white p-3">
            <div className="mb-1.5 text-xs text-gray-400">📐 函数图像（SymPy + Matplotlib）</div>
            <div className="plot-svg [&_svg]:h-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: plotSvg }} />
          </div>
        )}
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
