// Shiki 双主题（浅色令牌直出，深色由 index.css 的 CSS 变量切换）
import type { ThemeInput } from "shiki/core";

import githubLight from "shiki/themes/github-light.mjs";
import githubDark from "shiki/themes/github-dark.mjs";

const themes: Record<"githubLight" | "githubDark", ThemeInput> = {
  githubLight,
  githubDark,
};

export default themes;
