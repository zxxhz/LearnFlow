// 轻量 markdown 渲染（消息/卡片背面共用）：markdown-it + KaTeX auto-render + 函数图像自动渲染
import { useEffect, useRef } from "react";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";
import { api } from "../lib/api";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

// 全局图像缓存，避免流式输出或重新渲染时重复向后端发起网络请求
const plotSvgCache = new Map<string, string>();
const PLOT_LANGS = new Set(["plot", "math-plot", "绘图"]);

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
  return defaultFenceRender(tokens, idx, options, env, self);
};

const DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "\\[", right: "\\]", display: true },
  { left: "$", right: "$", display: false },
  { left: "\\(", right: "\\)", display: false },
];

export default function MarkdownLite({ text, className = "" }: { text: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const html = md.render(text ?? "");

  useEffect(() => {
    if (!ref.current) return;

    // 1. 同步 KaTeX 渲染
    try {
      renderMathInElement(ref.current, { delimiters: DELIMITERS, throwOnError: false });
    } catch (e) {
      console.warn("KaTeX render error in MarkdownLite:", e);
    }

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
          plotSvgCache.set(expressions, res.svg);
          if (canvas.isConnected) {
            canvas.innerHTML = `<div class="plot-svg w-full [&_svg]:h-auto [&_svg]:max-w-full">${res.svg}</div>`;
          }
        })
        .catch((err: unknown) => {
          if (canvas.isConnected) {
            canvas.innerHTML = `<div class="text-xs text-red-500 py-2">⚠️ 函数图像生成失败：${(err as Error).message || "表达式解析异常"}</div>`;
          }
        });
    });
  }, [html]);

  return <div ref={ref} className={`msg-md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />;
}
