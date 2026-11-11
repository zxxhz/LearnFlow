// 统一 AI 助教富块渲染：mindmap（交互式思维导图）与 quiz（随堂微测卡）
// 通过 data-* 占位容器 + DOM 附加装配，文本一律走 textContent，杜绝 LLM 输出注入面。
// 全屏放大经 window 事件委托给 MarkdownLite 的 React 覆盖层。

export const MINDMAP_ZOOM_EVENT = "learnflow:mindmap-zoom";

interface MindNode {
  text: string;
  children: MindNode[];
}

/** 解析 Markdown 缩进列表（每层 2 空格；Tab 记 2 空格）为树。 */
export function parseMindmap(src: string): MindNode | null {
  const lines = src
    .split("\n")
    .map((l) => l.replace(/\t/g, "  ").replace(/\r$/, ""))
    .map((l) => ({ indent: l.length - l.trimStart().length, text: l.trim() }))
    .filter((l) => l.text.length > 0 && !l.text.startsWith("```"));
  if (lines.length === 0) return null;

  const root: MindNode = { text: lines[0].text, children: [] };
  const stack: Array<{ node: MindNode; indent: number }> = [{ node: root, indent: lines[0].indent }];
  for (let i = 1; i < lines.length; i++) {
    const { indent, text } = lines[i];
    // 去掉列表标记（- / * / 1.）
    const clean = text.replace(/^[-*]\s+/, "").replace(/^\d+[.、)]\s+/, "").trim();
    if (!clean) continue;
    const node: MindNode = { text: clean, children: [] };
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop();
    if (indent > stack[stack.length - 1].indent) {
      stack[stack.length - 1].node.children.push(node);
      stack.push({ node, indent });
    } else {
      // 与根同级：追加为根子节点（宽容处理不规范的扁平列表）
      root.children.push(node);
      stack.push({ node, indent });
    }
  }
  return root;
}

const EDGE = "rgba(128,128,128,0.35)";

function mindmapNodeHtml(node: MindNode, depth: number): string {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const dot = depth === 0 ? "#4f7cff" : depth === 1 ? "#7c5cff" : "rgba(128,128,128,0.7)";
  if (node.children.length === 0) {
    return `<div style="display:flex;align-items:center;gap:6px;padding:2px 0 2px 14px;font-size:0.92em;">
      <span style="width:5px;height:5px;border-radius:99px;background:${dot};flex-shrink:0;"></span>
      <span>${esc(node.text)}</span></div>`;
  }
  return `<details open style="padding:2px 0 2px ${depth === 0 ? "0" : "14px"};">
    <summary style="display:flex;align-items:center;gap:6px;cursor:pointer;list-style:none;font-weight:${
      depth === 0 ? "600" : "400"
    };font-size:0.92em;">
      <span style="width:7px;height:7px;border-radius:99px;background:${dot};flex-shrink:0;"></span>
      <span>${esc(node.text)}</span></summary>
    <div style="margin-left:3px;padding-left:10px;border-left:1.5px solid ${EDGE};">
      ${node.children.map((c) => mindmapNodeHtml(c, depth + 1)).join("")}
    </div></details>`;
}

export function buildMindmapHtml(root: MindNode): string {
  return mindmapNodeHtml(root, 0);
}

function attachMindmaps(rootEl: HTMLElement): void {
  const containers = rootEl.querySelectorAll<HTMLDivElement>(".mindmap-container[data-mindmap]");
  containers.forEach((container) => {
    if (container.dataset.attached === "1") return;
    container.dataset.attached = "1";
    const raw = container.getAttribute("data-mindmap");
    if (!raw) return;
    let src = "";
    try {
      src = decodeURIComponent(raw);
    } catch {
      src = raw;
    }
    const parsed = parseMindmap(src);
    const body = container.querySelector<HTMLDivElement>(".mindmap-body");
    if (!body) return;
    if (!parsed) {
      body.innerHTML = '<div style="padding:8px 0;color:rgba(128,128,128,0.8);font-size:0.85em;">（导图内容为空）</div>';
      return;
    }
    body.innerHTML = buildMindmapHtml(parsed);
    const zoomBtn = container.querySelector<HTMLButtonElement>(".mindmap-zoom-btn");
    zoomBtn?.addEventListener("click", () => {
      window.dispatchEvent(
        new CustomEvent(MINDMAP_ZOOM_EVENT, {
          detail: { html: buildMindmapHtml(parsed), title: parsed.text },
        })
      );
    });
  });
}

// ===== 随堂微测卡 =====

interface QuizPayload {
  question?: string;
  options?: string[];
  answer?: number;
  explanation?: string;
}

function attachQuizzes(rootEl: HTMLElement): void {
  const containers = rootEl.querySelectorAll<HTMLDivElement>(".quiz-container[data-quiz]");
  containers.forEach((container) => {
    if (container.dataset.attached === "1") return;
    container.dataset.attached = "1";
    const raw = container.getAttribute("data-quiz");
    if (!raw) return;
    let payload: QuizPayload | null = null;
    try {
      payload = JSON.parse(decodeURIComponent(raw)) as QuizPayload;
    } catch {
      payload = null;
    }
    const body = container.querySelector<HTMLDivElement>(".quiz-body");
    if (!body || !payload || !Array.isArray(payload.options) || payload.options.length < 2) {
      if (body) body.innerHTML = '<div style="padding:6px 0;color:rgba(128,128,128,0.8);font-size:0.85em;">（微测卡格式异常，已按原文展示）</div>';
      return;
    }
    const correct = typeof payload.answer === "number" ? payload.answer : -1;
    const optionButtons: HTMLButtonElement[] = [];
    payload.options.forEach((opt, i) => {
      const row = document.createElement("button");
      row.type = "button";
      row.style.cssText =
        "display:flex;align-items:center;gap:8px;width:100%;text-align:left;padding:6px 10px;margin-top:6px;" +
        "border:1px solid " + EDGE + ";border-radius:8px;background:transparent;cursor:pointer;font-size:0.9em;transition:background .15s;";
      const letter = document.createElement("span");
      letter.textContent = String.fromCharCode(65 + i);
      letter.style.cssText =
        "display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:99px;" +
        "background:rgba(128,128,128,0.18);font-size:0.8em;font-weight:600;flex-shrink:0;";
      const text = document.createElement("span");
      text.textContent = String(opt);
      row.appendChild(letter);
      row.appendChild(text);
      row.addEventListener("mouseenter", () => {
        if (!body.dataset.answered) row.style.background = "rgba(128,128,128,0.08)";
      });
      row.addEventListener("mouseleave", () => {
        if (!body.dataset.answered) row.style.background = "transparent";
      });
      row.addEventListener("click", () => {
        if (body.dataset.answered === "1") return;
        body.dataset.answered = "1";
        const isCorrect = i === correct;
        optionButtons.forEach((btn, bi) => {
          btn.style.cursor = "default";
          if (bi === correct) {
            btn.style.borderColor = "rgba(34,160,90,0.65)";
            btn.style.background = "rgba(34,160,90,0.12)";
          } else if (bi === i) {
            btn.style.borderColor = "rgba(214,69,69,0.65)";
            btn.style.background = "rgba(214,69,69,0.12)";
          }
        });
        const verdict = document.createElement("div");
        verdict.style.cssText = "margin-top:8px;font-size:0.88em;font-weight:600;";
        verdict.textContent = isCorrect ? "✅ 答对了" : correct >= 0 ? `❌ 不对，正确答案是 ${String.fromCharCode(65 + correct)}` : "❌ 不对";
        verdict.style.color = isCorrect ? "#22a05a" : "#d64545";
        body.appendChild(verdict);
        if (payload?.explanation) {
          const exp = document.createElement("div");
          exp.style.cssText = "margin-top:4px;font-size:0.88em;opacity:0.85;line-height:1.5;";
          exp.textContent = payload.explanation;
          body.appendChild(exp);
        }
      });
      optionButtons.push(row);
      body.appendChild(row);
    });
  });
}

/** 在 MarkdownLite 渲染完成后装配全部助教富块（幂等）。 */
export function attachAssistantBlocks(rootEl: HTMLElement | null): void {
  if (!rootEl) return;
  attachMindmaps(rootEl);
  attachQuizzes(rootEl);
}
