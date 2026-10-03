// 单题卡片：代码题（补全骨架→运行→stdout 自动判定）/ 概念题（LLM 评分）/ 单选·填空（本地判定）（PRD §5.10）
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Exercise, ExerciseAttempt } from "../../lib/types";
import { Badge, Button, Spinner } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

interface Props {
  exercise: Exercise;
  documentId: string;
}

const STATUS_BADGE: Record<string, { label: string; color: "gray" | "green" | "blue" | "red" | "amber" }> = {
  success: { label: "运行成功", color: "green" },
  runtime_error: { label: "运行出错", color: "red" },
  timeout: { label: "运行超时", color: "amber" },
  compile_error: { label: "编译失败", color: "red" },
  compiler_missing: { label: "缺编译器", color: "amber" },
  error: { label: "执行异常", color: "red" },
  graded: { label: "已评分", color: "blue" },
};

const CHOICE_LETTERS = ["A", "B", "C", "D", "E", "F", "G"];

export function parseOptions(exercise: Exercise): string[] {
  try {
    const arr = JSON.parse(exercise.options);
    return Array.isArray(arr) ? arr.map(String) : [];
  } catch {
    return [];
  }
}

export default function ExerciseCard({ exercise, documentId }: Props) {
  const queryClient = useQueryClient();
  const isCode = exercise.kind === "code";
  const isChoice = exercise.kind === "choice";
  const isFill = exercise.kind === "fill";
  const [draft, setDraft] = useState<string | null>(null); // 代码题：非空 = 用户改过
  const [answer, setAnswer] = useState("");
  const [choicePick, setChoicePick] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const adoptedAttempt = useRef<string | null>(null);

  // 打开时回显最近一次作答（提交后 invalidate 拉到新 attempt，同 BlockView 模式）
  useEffect(() => {
    const a = exercise.latest_attempt;
    if (!a || adoptedAttempt.current === a.id) return;
    adoptedAttempt.current = a.id;
    if (isCode) {
      if (draft === null && a.content !== exercise.skeleton_code) setDraft(a.content);
    } else if (isChoice) {
      if (a.content) setChoicePick(a.content.toUpperCase());
    } else if (!isChoice && answer === "" && a.content) {
      setAnswer(a.content);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exercise.latest_attempt?.id]);

  const attempt: ExerciseAttempt | null = exercise.latest_attempt;

  const submit = useMutation({
    mutationFn: () => {
      const content = isCode ? (draft ?? exercise.skeleton_code) : isChoice ? (choicePick ?? "") : answer;
      return api.exercises.submit(exercise.id, content);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: () => api.exercises.remove(exercise.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const ta = e.currentTarget;
    const { selectionStart: s, selectionEnd: en, value } = ta;
    const next = value.slice(0, s) + "    " + value.slice(en);
    if (isCode) setDraft(next);
    else setAnswer(next);
    requestAnimationFrame(() => ta.setSelectionRange(s + 4, s + 4));
  };

  const pending = submit.isPending;
  const content = isCode ? draft ?? exercise.skeleton_code : isChoice ? "" : answer;
  const options = isChoice ? parseOptions(exercise) : [];

  const answerReveal = () => {
    if (isChoice) {
      const letter = exercise.answer.toUpperCase();
      const idx = CHOICE_LETTERS.indexOf(letter);
      return `${letter}${idx >= 0 && idx < options.length ? `（${options[idx]}）` : ""}`;
    }
    try {
      const arr = JSON.parse(exercise.answer);
      return Array.isArray(arr) ? arr.join(" / ") : exercise.answer;
    } catch {
      return exercise.answer;
    }
  };

  const renderAttemptResult = () =>
    attempt && (
      <div className="mt-2 space-y-2">
        {attempt.passed === true ? (
          <div className="rounded-lg bg-green-50 dark:bg-green-900/30 px-3 py-2 text-sm font-medium text-green-700 dark:text-green-400">
            ✅ 通过{isCode ? "！输出与预期一致。" : ""}
          </div>
        ) : (
          attempt.passed === false && (
            <div className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm font-medium text-red-700 dark:text-red-400">
              ❌ 未通过{attempt.feedback ? `：${attempt.feedback}` : "，再试试。"}
            </div>
          )
        )}
        {isCode && (attempt.stdout || attempt.stderr) && (
          <div className="rounded-lg bg-gray-900/95 p-2.5 font-mono text-xs">
            {attempt.stdout && <pre className="whitespace-pre-wrap text-green-200">{attempt.stdout}</pre>}
            {attempt.stderr && <pre className="whitespace-pre-wrap text-red-300">{attempt.stderr}</pre>}
            <div className="mt-1 text-[10px] text-gray-400 dark:text-gray-500">
              退出码 {attempt.exit_code ?? "-"}
              {attempt.duration_ms != null && ` · ${attempt.duration_ms}ms`}
            </div>
          </div>
        )}
        {!isChoice && (
          <button className="text-xs text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setRevealed((v) => !v)}>
            {revealed ? (isFill ? "收起参考答案" : "收起预期输出") : isFill ? "查看参考答案" : "查看预期输出"}
          </button>
        )}
        {revealed && (
          <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2 font-mono text-xs text-gray-600 dark:text-gray-400">
            {isCode ? exercise.expected_output || "（空）" : isFill ? answerReveal() : exercise.reference_answer}
          </pre>
        )}
      </div>
    );

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge color={isCode ? "blue" : isChoice || isFill ? "amber" : "gray"}>
            {isCode ? "💻 代码题" : isChoice ? "🔤 单选题" : isFill ? "✏️ 填空题" : "💬 概念题"}
          </Badge>
          {attempt?.passed === true && <Badge color="green">✅ 通过</Badge>}
          {attempt?.passed === false && <Badge color="red">❌ 未通过</Badge>}
          {attempt && isCode && STATUS_BADGE[attempt.status] && (
            <Badge color={STATUS_BADGE[attempt.status].color}>{STATUS_BADGE[attempt.status].label}</Badge>
          )}
        </div>
        <button
          className="shrink-0 text-[10px] text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400"
          title="删除此题"
          onClick={() => {
            if (confirm("删除这道练习题及其作答记录？")) remove.mutate();
          }}
        >
          删除
        </button>
      </div>
      <div className="mt-1.5 text-sm font-medium text-gray-800 dark:text-gray-200">{exercise.title}</div>
      <div className="msg-md mt-1 text-sm text-gray-600 dark:text-gray-400 [&_p]:my-1">
        <MarkdownLite text={exercise.task_md} />
      </div>

      {isCode ? (
        <>
          <textarea
            value={content}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={Math.min(14, Math.max(4, content.split("\n").length + 1))}
            spellCheck={false}
            aria-label="练习代码（可编辑）"
            className="mt-2 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-2.5 font-mono text-xs leading-5 text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <div className="mt-2 flex items-center gap-2">
            <Button
              className="bg-green-700/90 text-white hover:bg-green-700"
              disabled={pending || !content.trim()}
              onClick={() => submit.mutate()}
            >
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5 border-gray-300 dark:border-gray-600 border-t-white" /> 运行判定中…
                </>
              ) : (
                "▶ 运行判定"
              )}
            </Button>
            {draft !== null && draft !== exercise.skeleton_code && (
              <Button variant="ghost" className="text-xs" onClick={() => setDraft(null)}>
                ↺ 重置
              </Button>
            )}
          </div>
          {renderAttemptResult()}
        </>
      ) : isChoice ? (
        <>
          <div className="mt-2 space-y-1.5">
            {options.map((opt, i) => {
              const letter = CHOICE_LETTERS[i];
              const picked = choicePick === letter;
              return (
                <button
                  key={letter}
                  disabled={pending}
                  onClick={() => setChoicePick(letter)}
                  className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-sm ${
                    picked
                      ? "border-brand-500 dark:border-brand-400 bg-brand-50 dark:bg-brand-900/40 text-brand-800"
                      : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:border-gray-300"
                  }`}
                >
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                      picked ? "bg-brand-600 text-white" : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
                    }`}
                  >
                    {letter}
                  </span>
                  {opt}
                </button>
              );
            })}
          </div>
          <div className="mt-2">
            <Button disabled={pending || !choicePick} onClick={() => submit.mutate()}>
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> 判定中…
                </>
              ) : (
                "提交答案"
              )}
            </Button>
          </div>
          {renderAttemptResult()}
        </>
      ) : isFill ? (
        <>
          <input
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && answer.trim() && !pending) submit.mutate();
            }}
            placeholder="填入答案…"
            aria-label="填空题作答"
            className="mt-2 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2.5 text-sm text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <div className="mt-2">
            <Button disabled={pending || !answer.trim()} onClick={() => submit.mutate()}>
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> 判定中…
                </>
              ) : (
                "提交答案"
              )}
            </Button>
          </div>
          {renderAttemptResult()}
        </>
      ) : (
        <>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={onKeyDown}
            rows={5}
            placeholder="用自己的话写下你的理解…"
            aria-label="概念题作答"
            className="mt-2 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2.5 text-sm text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <div className="mt-2 flex items-center gap-2">
            <Button disabled={pending || !answer.trim()} onClick={() => submit.mutate()}>
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> AI 评分中…
                </>
              ) : (
                "提交评分"
              )}
            </Button>
            <span className="text-[10px] text-gray-400 dark:text-gray-500">作答后会调用 LLM 按参考答案评分</span>
          </div>
          {attempt && (
            <div className="mt-2 space-y-2">
              {attempt.passed === true && (
                <div className="rounded-lg bg-green-50 dark:bg-green-900/30 px-3 py-2 text-sm font-medium text-green-700 dark:text-green-400">✅ 通过</div>
              )}
              {attempt.passed === false && (
                <div className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm font-medium text-red-700 dark:text-red-400">❌ 未通过</div>
              )}
              {attempt.feedback && (
                <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-2.5 text-sm text-gray-700 dark:text-gray-300 [&_p]:my-1">
                  <MarkdownLite text={attempt.feedback} />
                </div>
              )}
              <button className="text-xs text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setRevealed((v) => !v)}>
                {revealed ? "收起参考答案" : "查看参考答案"}
              </button>
              {revealed && (
                <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2.5 text-sm text-gray-600 dark:text-gray-400 [&_p]:my-1">
                  <MarkdownLite text={exercise.reference_answer} />
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
