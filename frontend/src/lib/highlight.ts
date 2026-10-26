// 代码高亮：Shiki 按需加载（core + 常用语言 + 双主题）
// 直接 `import("shiki")` 会拉全量 bundle（279 个语言分块约 12MB），
// 这里只注册课程正文实际会出现的语言，未注册语言回落纯文本 <pre>。
import type { HighlighterCore } from "shiki/core";

let highlighterPromise: Promise<HighlighterCore> | null = null;

/** 课程正文常见语言；code 块的语言标识统一小写后匹配 */
const SUPPORTED_LANGS = [
  "python",
  "cpp",
  "c",
  "javascript",
  "typescript",
  "java",
  "go",
  "rust",
  "bash",
  "shell",
  "json",
  "yaml",
  "html",
  "css",
  "sql",
  "markdown",
  "diff",
  "xml",
] as const;

const ALIASES: Record<string, string> = {
  py: "python",
  "c++": "cpp",
  "c++17": "cpp",
  js: "javascript",
  ts: "typescript",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  yml: "yaml",
  md: "markdown",
  golang: "go",
  "rs": "rust",
};

function normalizeLang(lang: string): string {
  const l = (lang || "").trim().toLowerCase();
  return ALIASES[l] ?? l;
}

async function getHighlighter(): Promise<HighlighterCore> {
  if (!highlighterPromise) {
    highlighterPromise = (async () => {
      // JS 引擎（纯正则、无 onig.wasm）：省掉 wasm 分块且体积更小，够用
      const [{ createHighlighterCore }, { createJavaScriptRegexEngine }, { default: langs }, { default: themes }] =
        await Promise.all([
          import("shiki/core"),
          import("shiki/engine/javascript"),
          import("./shikiLangs"),
          import("./shikiThemes"),
        ]);
      return createHighlighterCore({
        themes: [themes.githubLight, themes.githubDark],
        langs,
        engine: createJavaScriptRegexEngine(),
      });
    })();
  }
  return highlighterPromise;
}

/** 高亮一段代码为双主题 HTML；未知语言回落纯文本（与旧版全量 shiki 行为一致） */
export async function highlightCode(code: string, lang: string): Promise<string> {
  const hi = await getHighlighter();
  const l = normalizeLang(lang);
  const loaded = hi.getLoadedLanguages();
  const resolved = loaded.includes(l) ? l : "text";
  // 双主题输出（defaultColor 用浅色令牌，深色由 index.css 的 CSS 变量切换）
  return hi.codeToHtml(code, {
    lang: resolved,
    themes: { light: "github-light", dark: "github-dark" },
    defaultColor: "light",
  });
}
