// Shiki 按需语言注册表（配合 lib/highlight.ts，见文件头说明）
import type { LanguageInput } from "shiki/core";

import cpp from "shiki/langs/cpp.mjs";
import c from "shiki/langs/c.mjs";
import python from "shiki/langs/python.mjs";
import javascript from "shiki/langs/javascript.mjs";
import typescript from "shiki/langs/typescript.mjs";
import java from "shiki/langs/java.mjs";
import go from "shiki/langs/go.mjs";
import rust from "shiki/langs/rust.mjs";
import bash from "shiki/langs/bash.mjs";
import json from "shiki/langs/json.mjs";
import yaml from "shiki/langs/yaml.mjs";
import html from "shiki/langs/html.mjs";
import css from "shiki/langs/css.mjs";
import sql from "shiki/langs/sql.mjs";
import markdown from "shiki/langs/markdown.mjs";
import diff from "shiki/langs/diff.mjs";
import xml from "shiki/langs/xml.mjs";

const langs: LanguageInput[] = [
  python,
  cpp,
  c,
  javascript,
  typescript,
  java,
  go,
  rust,
  bash,
  json,
  yaml,
  html,
  css,
  sql,
  markdown,
  diff,
  xml,
];

export default langs;
