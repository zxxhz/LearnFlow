// SVG 字符串净化（defense-in-depth）：这些 SVG 来自后端 Matplotlib/SymPy 输出，本身可信；
// 但插入路径可能被 LLM 生成的异常内容或上游服务污染，直插 innerHTML 前统一剥除
// 脚本标签与内联事件属性做最后一道兜底。注意：这是针对性正则而非完整 XSS 过滤器，
// 不用于渲染任意来源的 HTML。
const SVG_SCRIPT_RE = /<script[\s\S]*?<\/script\s*>/gi;
// 匹配 onclick= / onerror= 等内联事件属性（含未加引号的值）
const SVG_EVENT_ATTR_RE = /\son\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;

export function sanitizeSvg(svg: string): string {
  return svg.replace(SVG_SCRIPT_RE, "").replace(SVG_EVENT_ATTR_RE, "");
}
