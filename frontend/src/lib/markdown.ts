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
 * 优先按类型+顺序对齐；错位时按行号范围重叠兜底。
 */
export function alignSections(
  parsed: ParsedBlock[],
  serverBlocks: SectionBlock[]
): Map<number, string> {
  const map = new Map<number, string>();
  const byLine = new Map<string, SectionBlock>();
  for (const b of serverBlocks) byLine.set(`${b.order_index}`, b);

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

  // 兜底：行号重叠匹配
  const used = new Set<string>();
  parsed.forEach((p, i) => {
    const hit = serverBlocks.find(
      (b) =>
        !used.has(b.id) &&
        b.block_type === p.type &&
        b.order_index < p.lineEnd + 1 &&
        b.order_index > p.lineStart - 1
    );
    if (hit) {
      used.add(hit.id);
      map.set(i, hit.id);
    }
  });
  return map;
}
