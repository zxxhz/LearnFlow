// 单题卡片：闯关代码关（看提示→从零手写→运行→stdout 判定）/ 概念题（LLM 评分）/ 单选·填空（本地判定）（PRD §5.10）
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Exercise, ExerciseAttempt } from "../../lib/types";
import { Badge, Button, Spinner } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

interface Props {
  exercise: Exercise;
  documentId: string;
  /** 闯关链内的关卡序号（1 起）；小测题/旧列表不传则不显示关卡徽标 */
  level?: number;
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

export default function ExerciseCard({ exercise, documentId, level }: Props) {
  const queryClient = useQueryClient();
  const isCode = exercise.kind === "code";
  const isChoice = exercise.kind === "choice";
  const isFill = exercise.kind === "fill";
  const isMath = exercise.kind === "math";
  const locked = isCode && !exercise.unlocked;
  const hints = isCode ? (exercise.hints ?? []) : [];
  const [draft, setDraft] = useState<string | null>(null); // 代码题：非空 = 用户改过
  const [answer, setAnswer] = useState("");
  const [choicePick, setChoicePick] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [hintsShown, setHintsShown] = useState(1); // 第 1 条提示默认给出
  const [showRef, setShowRef] = useState(false);
  const adoptedAttempt = useRef<string | null>(null);

  // 助教伴学诊断状态
  const [tutorOpen, setTutorOpen] = useState(false);
  const [tutorLoading, setTutorLoading] = useState(false);
  const [tutorText, setTutorText] = useState("");
  const [tutorQuestion, setTutorQuestion] = useState("");
  const [tutorMode, setTutorMode] = useState<"socratic" | "direct">("socratic");
  const [tutorStatus, setTutorStatus] = useState<string | null>(null);
  const tutorAbortRef = useRef<AbortController | null>(null);



  // 打开时回显最近一次作答（提交后 invalidate 拉到新 attempt，同 BlockView 模式）
  useEffect(() => {
    const a = exercise.latest_attempt;
    if (!a || adoptedAttempt.current === a.id) return;
    adoptedAttempt.current = a.id;
    if (isCode) {
      if (draft === null && a.content) setDraft(a.content);
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
      const content = isCode ? (draft ?? "") : isChoice ? (choicePick ?? "") : answer;
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
  const content = isCode ? draft ?? "" : isChoice ? "" : answer;
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

  const requestTutor = async (questionText = "") => {
    let codeContent = isCode
      ? (draft ?? exercise.latest_attempt?.content ?? "")
      : isChoice
      ? (choicePick ?? "")
      : answer;
    if (!codeContent.trim()) {
      codeContent = "（学员正在思考解题思路，尚未编写作答内容）";
    }
    tutorAbortRef.current?.abort();
    const ctrl = new AbortController();
    tutorAbortRef.current = ctrl;
    setTutorOpen(true);
    setTutorLoading(true);
    setTutorStatus(null);
    if (!questionText) {
      setTutorText("");
    } else {
      setTutorText((prev) => prev + `\n\n**追问：${questionText}**\n\n`);
    }

    try {
      await api.tutor.diagnoseSSE(
        { exercise_id: exercise.id, content: codeContent, question: questionText, mode: tutorMode },
        (ev) => {
          if (ev.type === "tool_call") {
            if (ev.name === "run_sandbox_code") setTutorStatus("⚙️ 助教正在沙箱中实测代码...");
            else if (ev.name === "render_math_plot") setTutorStatus("📐 助教正在绘制函数图像...");
            else setTutorStatus(`🛠️ 助教正在调用工具 ${ev.name}...`);
          } else if (ev.type === "tool_result") {
            setTutorStatus(null);
          } else if (ev.type === "delta" && ev.text) {
            setTutorStatus(null);
            setTutorText((prev) => prev + ev.text);
          } else if (ev.type === "error") {
            setTutorStatus(null);
            setTutorText((prev) => prev + `\n\n> ⚠️ ${ev.detail || "助教诊断失败"}`);
            setTutorLoading(false);
          } else if (ev.type === "done") {
            setTutorStatus(null);
            setTutorLoading(false);
          }
        },
        ctrl.signal
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setTutorStatus(null);
        setTutorText((prev) => prev + `\n\n> ⚠️ ${err.message || "连接失败"}`);
      }
    } finally {
      setTutorLoading(false);
      setTutorStatus(null);
    }
  };

  const renderTutorPanel = () =>
    tutorOpen && (
      <div className="mt-2 rounded-lg border border-amber-200 dark:border-amber-800/80 bg-amber-50/50 dark:bg-amber-950/30 p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-800 dark:text-amber-200">
            <span>💡</span>
            <span>助教观察与启发点拨</span>
            {tutorLoading && <Spinner className="h-3 w-3 border-amber-500 border-t-transparent" />}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-0.5 rounded bg-amber-100/80 dark:bg-amber-900/50 p-0.5 text-[11px]">
              <button
                type="button"
                onClick={() => setTutorMode("socratic")}
                className={`px-1.5 py-0.5 rounded transition ${
                  tutorMode === "socratic"
                    ? "bg-white dark:bg-gray-800 text-amber-900 dark:text-amber-200 font-medium shadow-xs"
                    : "text-amber-700 dark:text-amber-400"
                }`}
              >
                💡 启发
              </button>
              <button
                type="button"
                onClick={() => setTutorMode("direct")}
                className={`px-1.5 py-0.5 rounded transition ${
                  tutorMode === "direct"
                    ? "bg-white dark:bg-gray-800 text-amber-900 dark:text-amber-200 font-medium shadow-xs"
                    : "text-amber-700 dark:text-amber-400"
                }`}
              >
                📖 直答
              </button>
            </div>
            <button
              type="button"
              onClick={() => setTutorOpen(false)}
              className="text-[11px] text-amber-700 dark:text-amber-300 hover:underline"
            >
              收起
            </button>
          </div>
        </div>
        {tutorStatus && (
          <div className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-300 font-mono py-1 animate-pulse">
            <Spinner className="h-3 w-3 border-amber-500 border-t-transparent" />
            <span>{tutorStatus}</span>
          </div>
        )}
        {tutorText && (
          <div className="msg-md text-xs leading-relaxed text-gray-800 dark:text-gray-200 bg-white/80 dark:bg-gray-900/80 rounded-md p-2.5 border border-amber-100 dark:border-amber-900/50">
            <MarkdownLite text={tutorText} />
          </div>
        )}
        <div className="flex items-center gap-1.5 pt-1">
          <input
            type="text"
            value={tutorQuestion}
            onChange={(e) => setTutorQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && tutorQuestion.trim() && !tutorLoading) {
                const q = tutorQuestion.trim();
                setTutorQuestion("");
                requestTutor(q);
              }
            }}
            placeholder="向助教提问（如：思路卡住了 / 这道题怎么破局？）…"
            disabled={tutorLoading}
            className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2.5 py-1 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-amber-500"
          />
          <Button
            variant="ghost"
            disabled={tutorLoading || !tutorQuestion.trim()}
            onClick={() => {
              const q = tutorQuestion.trim();
              setTutorQuestion("");
              requestTutor(q);
            }}
            className="px-2.5 py-1 text-xs text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900/50"
          >
            提问
          </Button>
        </div>
      </div>
    );

  const renderAttemptResult = () =>
    attempt && (
      <div className="mt-2 space-y-2">
        {attempt.passed === true ? (
          <div className="rounded-lg bg-green-50 dark:bg-green-900/30 px-3 py-2 text-sm font-medium text-green-700 dark:text-green-400">
            ✅ 通过{isCode ? "！输出与目标一致，关卡已通关。" : isMath ? "！公式与参考答案代数等价。" : ""}
          </div>
        ) : (
          attempt.passed === false && (
            <div className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm font-medium text-red-700 dark:text-red-400">
              ❌ 未通过{attempt.feedback ? `：${attempt.feedback}` : "，再试试。"}
            </div>
          )
        )}
        {attempt.passed === false && !tutorOpen && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => requestTutor()}
              disabled={tutorLoading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50/80 dark:bg-amber-950/40 px-2.5 py-1.5 text-xs font-medium text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900/60 transition-colors shadow-sm"
            >
              <span>💡</span>
              <span>呼叫助教启发诊断</span>
              {tutorLoading && <Spinner className="h-3 w-3 border-amber-500 border-t-transparent" />}
            </button>
          </div>
        )}
        {renderTutorPanel()}


        {isCode && (attempt.stdout || attempt.stderr) && (
          <div className="rounded-lg bg-gray-900/95 p-2.5 font-mono text-xs">
            <div className="mb-1 text-[10px] text-gray-400 dark:text-gray-500">你的输出</div>
            {attempt.stdout && <pre className="whitespace-pre-wrap text-green-200">{attempt.stdout}</pre>}
            {attempt.stderr && <pre className="whitespace-pre-wrap text-red-300">{attempt.stderr}</pre>}
            <div className="mt-1 text-[10px] text-gray-400 dark:text-gray-500">
              退出码 {attempt.exit_code ?? "-"}
              {attempt.duration_ms != null && ` · ${attempt.duration_ms}ms`}
            </div>
          </div>
        )}
        {!isChoice && !isCode && (
          <button className="text-xs text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setRevealed((v) => !v)}>
            {revealed ? "收起参考答案" : "查看参考答案"}
          </button>
        )}
        {revealed && !isCode && (
          <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2 font-mono text-xs text-gray-600 dark:text-gray-400">
            {isFill ? answerReveal() : isMath ? (exercise.expected_output || exercise.answer || exercise.reference_answer) : exercise.reference_answer}
          </pre>
        )}
        {isCode && attempt.passed === true && (
          <>
            <button className="text-xs text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setShowRef((v) => !v)}>
              {showRef ? "收起参考实现" : "查看参考实现"}
            </button>
            {showRef && (
              <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2 font-mono text-xs text-gray-600 dark:text-gray-400">
                {exercise.reference_code || exercise.skeleton_code || "（无）"}
              </pre>
            )}
          </>
        )}
      </div>
    );

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {level != null && <Badge color="blue">🎮 第 {level} 关</Badge>}
          <Badge color={isCode ? "blue" : isMath ? "purple" : isChoice || isFill ? "amber" : "gray"}>
            {isCode ? "💻 代码关" : isMath ? "📐 数学计算关" : isChoice ? "🔤 单选题" : isFill ? "✏️ 填空题" : "💬 概念题"}
          </Badge>
          {locked && <Badge color="gray">🔒 未解锁</Badge>}
          {attempt?.passed === true && <Badge color="green">✅ 通关</Badge>}
          {attempt?.passed === false && <Badge color="red">❌ 未通过</Badge>}
          {attempt && isCode && STATUS_BADGE[attempt.status] && (
            <Badge color={STATUS_BADGE[attempt.status].color}>{STATUS_BADGE[attempt.status].label}</Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={() => {
              if (!tutorOpen) {
                setTutorOpen(true);
                if (!tutorText) requestTutor();
              } else {
                setTutorOpen(false);
              }
            }}
            className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border transition font-medium ${
              tutorOpen
                ? "border-amber-400 bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200"
                : "border-amber-300 dark:border-amber-700/80 bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900/40 shadow-xs"
            }`}
            title="遇到卡点？呼叫苏格拉底伴学助教"
          >
            <span>💡</span>
            <span>伴学助教</span>
          </button>
          <button
            className="text-[10px] text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400"
            title="删除此题"
            onClick={() => {
              if (confirm("删除这道练习题及其作答记录？")) remove.mutate();
            }}
          >
            删除
          </button>
        </div>
      </div>
      <div className="mt-1.5 text-sm font-medium text-gray-800 dark:text-gray-200">{exercise.title}</div>
      <div className="msg-md mt-1 text-sm text-gray-600 dark:text-gray-400 [&_p]:my-1">
        <MarkdownLite text={exercise.task_md} />
      </div>

      {isCode ? (
        locked ? (
          <div className="mt-2 rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 px-3 py-2.5 text-xs text-gray-500 dark:text-gray-400">
            🔒 通关上一关后解锁挑战
          </div>
        ) : (
          <>
            {hints.length > 0 && (
              <div className="mt-2 space-y-1.5">
                {hints.slice(0, hintsShown).map((h, i) => (
                  <div
                    key={i}
                    className="rounded-lg bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-sm text-amber-800 dark:text-amber-200"
                  >
                    💡 提示 {i + 1}：{h}
                  </div>
                ))}
                {hintsShown < hints.length && (
                  <button
                    className="text-xs text-amber-600 dark:text-amber-300 underline hover:text-amber-700 dark:hover:text-amber-200"
                    onClick={() => setHintsShown((n) => n + 1)}
                  >
                    再给一条提示（{hintsShown + 1}/{hints.length}）
                  </button>
                )}
              </div>
            )}
            <div className="mt-2">
              <div className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
                🎯 目标输出（运行结果必须与之逐字符一致）
              </div>
              <pre className="whitespace-pre-wrap rounded-lg bg-gray-900/95 p-2.5 font-mono text-xs text-green-200">
                {exercise.expected_output || "（空）"}
              </pre>
            </div>
            <textarea
              value={content}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              rows={Math.min(14, Math.max(6, content.split("\n").length + 1))}
              spellCheck={false}
              aria-label="关卡代码（从零手写）"
              placeholder="从零写下你的代码…"
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
              {draft !== null && draft !== "" && (
                <Button variant="ghost" className="text-xs" onClick={() => setDraft(null)}>
                  ↺ 清空
                </Button>
              )}
            </div>
            {renderAttemptResult()}
          </>
        )
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
      ) : isMath ? (
        <>
          <div className="mt-2">
            <div className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
              📐 数学表达式（支持 SymPy 代数等价，如乘法交换律、同底幂相加等）
            </div>
            <input
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && answer.trim() && !pending) submit.mutate();
              }}
              placeholder="输入数学表达式，如 2*x*cos(x**2) 或 1/(1+exp(-x))…"
              aria-label="数学题作答"
              className="w-full rounded-lg border border-purple-200 dark:border-purple-800/60 bg-purple-50/20 dark:bg-purple-950/20 p-2.5 font-mono text-sm text-gray-800 dark:text-gray-200 focus:border-purple-500 dark:focus:border-purple-400 focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
          </div>
          <div className="mt-2 flex items-center gap-2">
            <Button
              className="bg-purple-700/90 text-white hover:bg-purple-700"
              disabled={pending || !answer.trim()}
              onClick={() => submit.mutate()}
            >
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5 border-gray-300 dark:border-gray-600 border-t-white" /> 代数等价验证中…
                </>
              ) : (
                "▶ 验证代数式"
              )}
            </Button>
            {answer.trim() !== "" && (
              <Button variant="ghost" className="text-xs" onClick={() => setAnswer("")}>
                ↺ 清空
              </Button>
            )}
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
