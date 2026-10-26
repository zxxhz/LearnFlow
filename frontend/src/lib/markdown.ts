// Markdown 块级解析与渲染。
// 契约：后端用 markdown-it-py（js-default 预设）、前端用 markdown-it（默认预设）
// 解析同一份 Markdown，两者的顶层块序列与行号范围一致（PRD §8.3）。
// 后端只产出 7 种 block_type；本文件用相同规则分类，保证 1:1 对齐。
import MarkdownIt from "markdown-it";
import type Token from "markdown-it/lib/token.mjs";
import type { BlockType, SectionBlock } from "./types";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });

export interface ParsedBlock {
  type: BlockType;
  html: string;
  raw: string;
  lineStart: number; // 0-based，含
  lineEnd: number; // 0-based，不含（与 markdown-it token.map 一致）
  headingText?: string;
  headingLevel?: number;
  codeLang?: string;
}

function isMathBlock(inlineContent: string): boolean {
  const t = inlineContent.trim();
  return t.startsWith("$$") && t.endsWith("$$");
}

export function parseBlocks(markdown: string): ParsedBlock[] {
  const normalized = markdown.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const tokens = md.parse(normalized, {});
  const blocks: ParsedBlock[] = [];

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    // 只取顶层块的开启 token（fence/html_block 为自闭合 nesting=0）
    const isOpener = t.level === 0 && (t.nesting === 1 || t.nesting === 0);
    if (!isOpener || t.map == null) continue;

    const [s, e] = t.map;
    const raw = lines.slice(s, e).join("\n");
    let type: BlockType;
    let headingText: string | undefined;
    let headingLevel: number | undefined;
    let codeLang: string | undefined;

    switch (t.type) {
      case "heading_open": {
        type = "heading";
        headingLevel = Number(t.tag.slice(1)); // h1→1
        headingText = tokens[i + 1]?.content?.trim() ?? "";
        break;
      }
      case "fence":
        type = "code";
        codeLang = t.info?.trim().split(/\s+/)[0] || "text";
        break;
      case "table_open":
        type = "table";
        break;
      case "blockquote_open":
        type = "quote";
        break;
      case "bullet_list_open":
      case "ordered_list_open":
        type = "list";
        break;
      case "paragraph_open": {
        const inline = tokens[i + 1]?.content ?? "";
        type = isMathBlock(inline) ? "math" : "paragraph";
        break;
      }
      default:
        continue; // hr / html_block 等两侧一致跳过
    }

    blocks.push({
      type,
      html: md.render(raw),
      raw,
      lineStart: s,
      lineEnd: e,
      headingText,
      headingLevel,
      codeLang,
    });
  }
  return blocks;
}

/**
 * 将前端解析块与后端 SectionBlock 对齐，返回 Map(前端块下标 → section_id)。
 * 优先按类型+顺序对齐；错位时按"标题文本精确匹配 + 保序贪心"兜底
 * （order_index 是块序号不是行号，与 lineStart/lineEnd 比较是单位错配，旧兜底基本随机命中）。
 */
export function alignSections(
  parsed: ParsedBlock[],
  serverBlocks: SectionBlock[]
): Map<number, string> {
  const map = new Map<number, string>();
  if (parsed.length === serverBlocks.length) {
    let allMatch = true;
    for (let i = 0; i < parsed.length; i++) {
      if (parsed[i].type !== serverBlocks[i].block_type) {
        allMatch = false;
        break;
      }
    }
    if (allMatch) {
      serverBlocks.forEach((b, i) => map.set(i, b.id));
      return map;
    }
  }

  // 兜底：同类型块内做保序对齐（LCS 风格），标题块额外要求文本一致
  const norm = (t?: string) => (t ?? "").replace(/\s+/g, "").trim();
  // 求保序最长公共子序列（类型一致 + 标题文本一致的元素）；
  // 标题块用 heading_path 末段比对（其即该标题自身文本）
  const n = parsed.length;
  const m = serverBlocks.length;
  const match = (i: number, j: number) => {
    if (parsed[i].type !== serverBlocks[j].block_type) return false;
    if (parsed[i].type !== "heading") return true;
    const hp = serverBlocks[j].heading_path ?? [];
    return norm(parsed[i].headingText) === norm(hp[hp.length - 1]);
  };
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = match(i, j)
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (match(i, j)) {
      map.set(i, serverBlocks[j].id);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return map;
}
