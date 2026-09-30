// 轻量 markdown 渲染（消息/卡片背面共用）：markdown-it + KaTeX auto-render
import { useEffect, useRef } from "react";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

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
