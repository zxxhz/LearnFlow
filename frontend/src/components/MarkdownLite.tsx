// 轻量 markdown 渲染（消息/卡片背面共用）：markdown-it + KaTeX auto-render + 函数图像自动渲染
// v0.5.0：新增 mindmap（交互导图）与 quiz（随堂微测卡）富块，由 assistantBlocks 装配
import { useEffect, useRef, useState } from "react";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";
import { api } from "../lib/api";
import { sanitizeSvg } from "../lib/sanitize";
import { attachAssistantBlocks, MINDMAP_ZOOM_EVENT } from "./assistantBlocks";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

// 全局图像缓存，避免流式输出或重新渲染时重复向后端发起网络请求
// LRU 上限 50：长会话下无上限增长会挤占内存，超限按 Map 插入序删最早
const plotSvgCache = new Map<string, string>();
const PLOT_SVG_CACHE_MAX = 50;
const PLOT_LANGS = new Set(["plot", "math-plot", "绘图"]);
const MINDMAP_LANGS = new Set(["mindmap", "导图"]);

function cachePlotSvg(key: string, svg: string): string {
  const clean = sanitizeSvg(svg);
  if (plotSvgCache.has(key)) plotSvgCache.delete(key);
  plotSvgCache.set(key, clean);
  if (plotSvgCache.size > PLOT_SVG_CACHE_MAX) {
    const oldest = plotSvgCache.keys().next().value;
    if (oldest !== undefined) plotSvgCache.delete(oldest);
  }
  return clean;
}

// linkify/链接默认在当前 WebView 导航，点一下就把整个应用窗口带走：
// 统一新窗口（Tauri 壳交系统浏览器/PWA 交新标签页）打开并断开 opener
const defaultLinkRender =
  md.renderer.rules.link_open ||
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet("target", "_blank");
  tokens[idx].attrSet("rel", "noopener noreferrer");
  return defaultLinkRender(tokens, idx, options, env, self);
};

// 识别 ```plot / ```math-plot 代码块并渲染为包含绘图容器的卡片
const defaultFenceRender =
  md.renderer.rules.fence ||
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.fence = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  const lang = (token.info || "").trim().split(/\s+/)[0].toLowerCase();
  if (PLOT_LANGS.has(lang)) {
    const code = token.content;
    const encoded = encodeURIComponent(code);
    return `<div class="math-plot-container my-3 rounded-lg border border-violet-200 dark:border-violet-800/80 bg-white dark:bg-gray-900 overflow-hidden shadow-sm" data-plot="${encoded}">
  <div class="flex items-center justify-between px-3 py-1.5 bg-violet-50 dark:bg-violet-950/40 border-b border-violet-100 dark:border-violet-900/60 text-xs text-violet-700 dark:text-violet-300 font-medium">
    <span class="flex items-center gap-1.5">📐 函数图像</span>
    <span class="text-[11px] text-gray-400">SymPy + Matplotlib</span>
  </div>
  <pre class="m-0 p-2.5 text-xs font-mono bg-gray-50/60 dark:bg-gray-950/40 text-gray-700 dark:text-gray-300 border-b border-gray-100 dark:border-gray-800 overflow-x-auto">${md.utils.escapeHtml(code)}</pre>
  <div class="plot-canvas p-2.5 flex items-center justify-center min-h-[90px] text-xs text-gray-400">
    <span class="animate-pulse">📐 正在绘制函数图像…</span>
  </div>
</div>`;
  }
  if (MINDMAP_LANGS.has(lang)) {
    const code = token.content;
    const encoded = encodeURIComponent(code);
    return `<div class="mindmap-container my-3 rounded-lg border border-sky-200 dark:border-sky-800/80 bg-sky-50/40 dark:bg-sky-950/30 overflow-hidden shadow-sm" data-mindmap="${encoded}">
  <div class="flex items-center justify-between px-3 py-1.5 bg-sky-50 dark:bg-sky-950/40 border-b border-sky-100 dark:border-sky-900/60 text-xs text-sky-700 dark:text-sky-300 font-medium">
    <span class="flex items-center gap-1.5">🗺️ 思维导图</span>
    <button type="button" class="mindmap-zoom-btn shrink-0 rounded border border-sky-200 dark:border-sky-700 px-1.5 py-0.5 text-[11px] text-sky-600 dark:text-sky-300 hover:bg-sky-100 dark:hover:bg-sky-900/50">⛶ 放大查看</button>
  </div>
  <div class="mindmap-body px-3 py-2 text-gray-800 dark:text-gray-200"></div>
</div>`;
  }
  if (lang === "quiz") {
    const code = token.content.trim();
    const encoded = encodeURIComponent(code);
    return `<div class="quiz-container my-3 rounded-lg border border-emerald-200 dark:border-emerald-800/80 bg-emerald-50/40 dark:bg-emerald-950/30 overflow-hidden shadow-sm" data-quiz="${encoded}">
  <div class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 dark:bg-emerald-950/40 border-b border-emerald-100 dark:border-emerald-900/60 text-xs text-emerald-700 dark:text-emerald-300 font-medium">🧪 随堂微测（点选即验）</div>
  <div class="quiz-body px-3 py-2 text-gray-800 dark:text-gray-200"></div>
</div>`;
  }
  return defaultFenceRender(tokens, idx, options, env, self);
};

const DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "\\[", right: "\\]", display: true },
  { left: "$", right: "$", display: false },
  { left: "\\(", right: "\\)", display: false },
];

export default function MarkdownLite({
  text,
  className = "",
  deferMath = false,
}: {
  text: string;
  className?: string;
  /** 流式输出期间置 true：跳过 KaTeX 渲染（每个 token 排版公式开销过大），翻转回 false 时对最终全文补渲染一次 */
  deferMath?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const html = md.render(text ?? "");
  // 导图全屏放大覆盖层（经 window 事件从任意 MarkdownLite 实例的 DOM 按钮唤起）
  const [zoom, setZoom] = useState<{ html: string; title: string } | null>(null);

  useEffect(() => {
    const onZoom = (e: Event) => {
      const detail = (e as CustomEvent<{ html: string; title: string }>).detail;
      if (detail?.html) setZoom({ html: detail.html, title: detail.title || "思维导图" });
    };
    window.addEventListener(MINDMAP_ZOOM_EVENT, onZoom);
    return () => window.removeEventListener(MINDMAP_ZOOM_EVENT, onZoom);
  }, []);

  useEffect(() => {
    if (!ref.current) return;

    // 1. 同步 KaTeX 渲染（deferMath=true 时跳过，仅 markdown 渲染）
    if (!deferMath) {
      try {
        renderMathInElement(ref.current, { delimiters: DELIMITERS, throwOnError: false });
      } catch (e) {
        console.warn("KaTeX render error in MarkdownLite:", e);
      }
    }

    // 1.5 助教富块（思维导图 / 随堂微测卡）装配
    attachAssistantBlocks(ref.current);

    // 2. 异步自动绘制并装配所有函数图像
    const plotContainers = ref.current.querySelectorAll<HTMLDivElement>(".math-plot-container[data-plot]");
    plotContainers.forEach((container) => {
      const rawEncoded = container.getAttribute("data-plot");
      if (!rawEncoded) return;
      const expressions = decodeURIComponent(rawEncoded).trim();
      if (!expressions) return;
      const canvas = container.querySelector<HTMLDivElement>(".plot-canvas");
      if (!canvas) return;

      // 命中缓存则立刻填入
      if (plotSvgCache.has(expressions)) {
        const cachedSvg = plotSvgCache.get(expressions)!;
        canvas.innerHTML = `<div class="plot-svg w-full [&_svg]:h-auto [&_svg]:max-w-full">${cachedSvg}</div>`;
        return;
      }

      // 未命中缓存则异步请求后端绘制
      api.math
        .render({ expressions })
        .then((res: { svg: string }) => {
          const clean = cachePlotSvg(expressions, res.svg);
          if (canvas.isConnected) {
            canvas.innerHTML = `<div class="plot-svg w-full [&_svg]:h-auto [&_svg]:max-w-full">${clean}</div>`;
          }
        })
        .catch((err: unknown) => {
          if (!canvas.isConnected) return;
          // 错误消息可能携带后端回显的 LLM 可控表达式文本，插入 innerHTML 前必须转义
          const msg = md.utils.escapeHtml((err as Error).message || "表达式解析异常");
          canvas.innerHTML = `<div class="text-xs text-red-500 py-2 flex flex-wrap items-center gap-2"><span>⚠️ 函数图像生成失败：${msg}</span></div>`;
          // 一键 AI 自修：把原表达式与报错交给后端修正，成功即换缓存重绘（DOM 按钮避免 innerHTML 注入）
          const fixBtn = document.createElement("button");
          fixBtn.type = "button";
          fixBtn.textContent = "🤖 AI 修正";
          fixBtn.className =
            "shrink-0 rounded-md border border-violet-300 dark:border-violet-700 bg-violet-50 dark:bg-violet-950/40 px-2 py-0.5 text-[11px] font-medium text-violet-700 dark:text-violet-300 transition hover:bg-violet-100 dark:hover:bg-violet-900/40 disabled:opacity-50";
          fixBtn.title = "让 AI 根据报错自动修正函数表达式并重绘";
          fixBtn.onclick = async () => {
            fixBtn.disabled = true;
            fixBtn.textContent = "🤖 AI 修正中…";
            try {
              const fixed = await api.math.fix({ expressions, error: (err as Error).message || "" });
              const clean = cachePlotSvg(fixed.expressions, fixed.svg);
              if (canvas.isConnected) {
                canvas.innerHTML = `<div class="plot-svg w-full [&_svg]:h-auto [&_svg]:max-w-full">${clean}</div>`;
              }
            } catch (fixErr: unknown) {
              if (canvas.isConnected) {
                const fixMsg = md.utils.escapeHtml((fixErr as Error).message || "AI 修正失败");
                canvas.innerHTML = `<div class="text-xs text-red-500 py-2">⚠️ AI 修正失败：${fixMsg}</div>`;
              }
            }
          };
          canvas.appendChild(fixBtn);
        });
    });
  }, [html, deferMath]);

  return (
    <>
      <div ref={ref} className={`msg-md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />
      {zoom && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-6"
          onClick={() => setZoom(null)}
        >
          <div
            className="max-h-full w-full max-w-2xl overflow-auto rounded-xl border border-gray-200 bg-white p-5 shadow-2xl dark:border-gray-700 dark:bg-gray-900"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">🗺️ {zoom.title}</span>
              <button
                type="button"
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                onClick={() => setZoom(null)}
              >
                ✕
              </button>
            </div>
            {/* 覆盖层内容来自已构建的 DOM 安全树（textContent 转义链路），无注入面 */}
            <div className="mindmap-zoom-body text-gray-800 dark:text-gray-200" dangerouslySetInnerHTML={{ __html: zoom.html }} />
          </div>
        </div>
      )}
    </>
  );
}
