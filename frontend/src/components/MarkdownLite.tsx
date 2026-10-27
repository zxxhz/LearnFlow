// 轻量 markdown 渲染（消息/卡片背面共用）：markdown-it + KaTeX auto-render
import { useEffect, useRef } from "react";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

// linkify/链接默认在当前 WebView 导航，点一下就把整个应用窗口带走：
// 统一新窗口（Tauri 壳交系统浏览器/PWA 交新标签页）打开并断开 opener
const defaultRender =
  md.renderer.rules.link_open ||
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet("target", "_blank");
  tokens[idx].attrSet("rel", "noopener noreferrer");
  return defaultRender(tokens, idx, options, env, self);
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
    if (ref.current) {
      renderMathInElement(ref.current, { delimiters: DELIMITERS, throwOnError: false });
    }
  }, [html]);

  return <div ref={ref} className={`msg-md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />;
}
