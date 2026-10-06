// 题库题目作答卡片：单选/多选/判断三种作答形态，提交后即时出判分与解析；回答错误时支持 AI 流式深度解答
import { useEffect, useRef, useState } from "react";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";
import { Badge, Button, ErrorText, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import type { BankAttemptResult, BankQuestion } from "../../lib/types";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
const KATEX_DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "$", right: "$", display: false },
];

const LETTERS = "ABCDEFGH".split("");
const TYPE_LABEL: Record<string, string> = { single: "单选", multi: "多选", judge: "判断" };

/** 可选项列表：判断题固定 A=正确 / B=错误；选择题按列位映射字母并过滤空项。 */
export function visibleOptions(q: BankQuestion): { letter: string; text: string }[] {
  if (q.qtype === "judge") {
    return [
      { letter: "A", text: "正确" },
      { letter: "B", text: "错误" },
    ];
  }
  return q.options
    .map((text, i) => ({ letter: LETTERS[i], text }))
    .filter((o) => o.text);
}

export default function BankQuestionCard({
  question,
  onAnswered,
}: {
  question: BankQuestion;
  onAnswered: (result: BankAttemptResult, picked: string[]) => void;
}) {
  const multi = question.qtype === "multi";
  const [picked, setPicked] = useState<string[]>([]);
  const [result, setResult] = useState<BankAttemptResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const opts = visibleOptions(question);

  // AI 错题解答流式状态
  const [aiOpen, setAiOpen] = useState(false);
  const [aiThinking, setAiThinking] = useState(false);
  const [aiStreaming, setAiStreaming] = useState(false);
  const [aiText, setAiText] = useState("");
  const [aiError, setAiError] = useState("");
  const aiStreamRef = useRef<HTMLDivElement>(null);

  // 数学公式渲染
  useEffect(() => {
    if (aiStreamRef.current) {
      renderMathInElement(aiStreamRef.current, {
        delimiters: KATEX_DELIMITERS,
        throwOnError: false,
      });
    }
  }, [aiText]);

  function toggle(letter: string) {
    if (result) return;
    setPicked((p) =>
      multi
        ? p.includes(letter)
          ? p.filter((x) => x !== letter)
          : [...p, letter]
        : [letter],
    );
  }

  async function submit() {
    setPending(true);
    setError("");
    try {
      const r = await api.banks.attempt(question.id, picked);
      setResult(r);
      onAnswered(r, picked);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function startAiExplain() {
    setAiThinking(true);
    setAiStreaming(true);
    setAiText("");
    setAiError("");

    let acc = "";
    try {
      await api.banks.explainSSE(
        question.id,
        picked,
        (ev) => {
          if (ev.type === "delta" && ev.text) {
            setAiThinking(false);
            acc += ev.text;
            setAiText(acc);
          } else if (ev.type === "done") {
            setAiThinking(false);
            setAiStreaming(false);
          } else if (ev.type === "error") {
            setAiThinking(false);
            setAiStreaming(false);
            setAiError(ev.detail || "AI 解答遇到异常，请稍后重试");
          }
        }
      );
    } catch (e) {
      setAiThinking(false);
      setAiStreaming(false);
      setAiError(`网络或服务异常：${(e as Error).message}`);
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 transition-all">
      <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
        <Badge color={multi ? "amber" : question.qtype === "judge" ? "blue" : "gray"}>
          {TYPE_LABEL[question.qtype] ?? question.qtype}
        </Badge>
        {question.difficulty && <span>难度：{question.difficulty}</span>}
        <span className="ml-auto">第 {question.seq} 题</span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-gray-900 dark:text-gray-100">
        {question.title}
      </p>

      <div className="mt-3 space-y-1.5">
        {opts.map((opt) => {
          const isPicked = picked.includes(opt.letter);
          return (
            <button
              key={opt.letter}
              disabled={!!result || pending}
              onClick={() => toggle(opt.letter)}
              className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-sm transition ${
                result && result.answer.includes(opt.letter)
                  ? "border-green-400 dark:border-green-600 bg-green-50 dark:bg-green-900/30 text-green-800 dark:text-green-300"
                  : isPicked
                    ? "border-brand-500 bg-brand-50 dark:bg-brand-900/30 text-brand-800 dark:text-brand-300"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600"
              }`}
            >
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center text-[11px] font-bold ${
                  multi ? "rounded" : "rounded-full"
                } ${
                  isPicked
                    ? "bg-brand-600 text-white"
                    : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
                }`}
              >
                {opt.letter}
              </span>
              {opt.text}
            </button>
          );
        })}
      </div>

      {result ? (
        <div className="mt-3 rounded-lg bg-gray-50 dark:bg-gray-800/60 p-3 text-sm">
          <div className={result.passed ? "text-green-700 dark:text-green-400 font-medium" : "text-red-700 dark:text-red-400 font-medium"}>
            {result.passed ? "✓ 回答正确" : `✗ 回答错误 · 正确答案：${result.correct_answer}`}
          </div>
          {result.explanation && (
            <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-gray-600 dark:text-gray-400">
              {result.explanation}
            </p>
          )}

          {/* 回答错误时：提供 AI 深度流式解答 */}
          {!result.passed && (
            <div className="mt-3 border-t border-gray-200/60 dark:border-gray-700/60 pt-3">
              {!aiOpen ? (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    💡 想彻底搞懂为什么做错？
                  </span>
                  <Button
                    variant="secondary"
                    className="text-xs !py-1 text-brand-600 dark:text-brand-400 border-brand-200 dark:border-brand-800 hover:bg-brand-50 dark:hover:bg-brand-950/40"
                    onClick={() => {
                      setAiOpen(true);
                      startAiExplain();
                    }}
                  >
                    🤖 获取 AI 深度解析
                  </Button>
                </div>
              ) : (
                <div className="rounded-lg border border-brand-200 dark:border-brand-800 bg-brand-50/50 dark:bg-brand-950/20 p-3 text-xs shadow-sm">
                  <div className="flex items-center justify-between pb-2 border-b border-brand-100 dark:border-brand-900/60">
                    <div className="flex items-center gap-1.5 font-semibold text-brand-800 dark:text-brand-300">
                      <span>🤖 AI 助教错题剖析</span>
                      {aiStreaming && <span className="inline-block h-2 w-2 rounded-full bg-brand-500 animate-ping" />}
                    </div>
                    <div className="flex items-center gap-1">
                      {!aiStreaming && !aiThinking && (
                        <button
                          type="button"
                          className="text-[11px] text-gray-400 hover:text-brand-600 dark:hover:text-brand-400 px-1"
                          onClick={startAiExplain}
                          title="重新生成解答"
                        >
                          ↻ 重新生成
                        </button>
                      )}
                      <button
                        type="button"
                        className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 px-1"
                        onClick={() => setAiOpen(false)}
                        title="收起 AI 解析"
                      >
                        ✕
                      </button>
                    </div>
                  </div>

                  {aiThinking && (
                    <div className="py-4 flex items-center justify-center gap-2 text-gray-500 dark:text-gray-400">
                      <div className="flex space-x-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "0ms" }} />
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "150ms" }} />
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "300ms" }} />
                      </div>
                      <span>AI 正在结合题库规则诊断错因与考点…</span>
                    </div>
                  )}

                  {aiText && (
                    <div className="mt-2 text-gray-800 dark:text-gray-200 leading-relaxed overflow-x-auto">
                      <div
                        ref={aiStreamRef}
                        className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed"
                        dangerouslySetInnerHTML={{ __html: md.render(aiText) }}
                      />
                      {aiStreaming && (
                        <span className="inline-block h-3.5 w-1.5 ml-0.5 align-middle bg-brand-500 animate-pulse rounded-sm" />
                      )}
                    </div>
                  )}

                  {aiError && (
                    <div className="mt-2 text-red-600 dark:text-red-400">
                      {aiError}
                      <button
                        type="button"
                        className="ml-2 underline font-medium"
                        onClick={startAiExplain}
                      >
                        重试
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="mt-3 flex items-center justify-end gap-2">
          {multi && picked.length > 0 && !pending && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              已选 {picked.sort().join("、")}
            </span>
          )}
          <Button disabled={pending || picked.length === 0} onClick={submit}>
            {pending ? (
              <>
                <Spinner className="h-3.5 w-3.5" /> 判定中…
              </>
            ) : multi ? (
              "提交（可多选）"
            ) : (
              "提交"
            )}
          </Button>
        </div>
      )}
      <ErrorText>{error}</ErrorText>
    </div>
  );
}
