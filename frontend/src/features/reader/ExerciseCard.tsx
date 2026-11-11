// 单题卡片：闯关代码关（看提示→从零手写→运行→stdout 判定）/ 概念题（LLM 评分）/ 单选·填空（本地判定）（PRD §5.10）
// v0.5.0：卡内旧辅导框下线，统一「问 AI 助教」唤起右侧 AssistantPanel（同一章节内上下文延续）
import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Exercise, ExerciseAttempt } from "../../lib/types";
import { Badge, Button, Spinner } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";
import { useReaderAssistant } from "./assistantContext";

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

const CHOICE_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"];

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
  const assistant = useReaderAssistant();
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
  const [isDoubtful, setIsDoubtful] = useState(false);
  const adoptedAttempt = useRef<string | null>(null);

  const attempt: ExerciseAttempt | null = exercise.latest_attempt;

  /** 唤起右侧统一 AI 助教：随附题目、当前作答与最新判题状态（场景护栏按未通过/已通过自动切换） */
  const askAssistant = () => {
    if (!assistant) return;
    const userCode = isCode ? (draft ?? exercise.latest_attempt?.content ?? "") : "";
    const userAnswer = isChoice ? (choicePick ?? "") : isCode ? "" : answer;
    const judgeStatus =
      attempt?.passed === true ? "passed" : attempt?.passed === false ? "failed" : "pending";
    assistant.openAssistant(
      {
        kind: "exercise",
        document_id: documentId,
        exercise_id: exercise.id,
        user_code: userCode || undefined,
        user_answer: userAnswer || undefined,
        judge_status: judgeStatus,
      },
      `💻 练习：${exercise.title}`
    );
  };



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

  const submit = useMutation({
    mutationFn: () => {
      const content = isCode ? (draft ?? "") : isChoice ? (choicePick ?? "") : answer;
      return api.exercises.submit(exercise.id, content, isDoubtful);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
      // 小测题同源提交，需刷新 quizzes 缓存才能拿到作答后的参考答案回显
      queryClient.invalidateQueries({ queryKey: ["quizzes", documentId] });
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

  const toggleHardBone = useMutation({
    mutationFn: () => api.exercises.toggleHardBone(exercise.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const generateBridge = useMutation({
    mutationFn: () => api.exercises.generateBridge(exercise.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
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

  const renderAttemptResult = () =>
    attempt && (
      <div className="mt-2 space-y-2">
        {attempt.passed === true ? (
          <div className="rounded-lg bg-green-50 dark:bg-green-900/30 px-3 py-2 exercise-result-banner font-medium text-green-700 dark:text-green-400">
            ✅ 通过{isCode ? "！输出与目标一致，关卡已通关。" : isMath ? "！公式与参考答案代数等价。" : ""}
          </div>
        ) : (
          attempt.passed === false && (
            <div className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 exercise-result-banner font-medium text-red-700 dark:text-red-400">
              ❌ 未通过{attempt.feedback ? `：${attempt.feedback}` : "，再试试。"}
            </div>
          )
        )}
        {attempt.passed === false && (
          <div className="mt-2">
            <button
              type="button"
              onClick={askAssistant}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50/80 dark:bg-amber-950/40 px-2.5 py-1.5 text-[0.85em] font-medium text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900/60 transition-colors shadow-sm"
            >
              <span>🤖</span>
              <span>问 AI 助教：卡在哪一步了？</span>
            </button>
          </div>
        )}

        {isCode && (attempt.stdout || attempt.stderr) && (
          <div className="rounded-lg bg-gray-900/95 p-2.5 font-mono text-[0.85em]">
            <div className="mb-1 text-[0.8em] text-gray-400 dark:text-gray-500">你的输出</div>
            {attempt.stdout && <pre className="whitespace-pre-wrap text-green-200">{attempt.stdout}</pre>}
            {attempt.stderr && <pre className="whitespace-pre-wrap text-red-300">{attempt.stderr}</pre>}
            <div className="mt-1 text-[0.8em] text-gray-400 dark:text-gray-500">
              退出码 {attempt.exit_code ?? "-"}
              {attempt.duration_ms != null && ` · ${attempt.duration_ms}ms`}
            </div>
          </div>
        )}
        {!isChoice && !isCode && (
          <button className="text-[0.85em] text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setRevealed((v) => !v)}>
            {revealed ? "收起参考答案" : "查看参考答案"}
          </button>
        )}
        {revealed && !isCode && (
          <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2 font-mono text-[0.85em] text-gray-600 dark:text-gray-400">
            {isFill ? answerReveal() : isMath ? (exercise.expected_output || exercise.answer || exercise.reference_answer) : exercise.reference_answer}
          </pre>
        )}
        {/* 与后端脱敏口径一致：reference_code 只要 ever_passed（任一次通过）就下发，
            通关后改代码重跑失败不应把按钮藏回去 */}
        {isCode && exercise.ever_passed && (
          <>
            <button className="text-[0.85em] text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setShowRef((v) => !v)}>
              {showRef ? "收起参考实现" : "查看参考实现"}
            </button>
            {showRef && (
              <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2 font-mono text-[0.85em] text-gray-600 dark:text-gray-400">
                {exercise.reference_code || exercise.skeleton_code || "（无）"}
              </pre>
            )}
          </>
        )}
        {attempt && attempt.passed === false && isCode && !exercise.parent_exercise_id && (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => generateBridge.mutate()}
              disabled={generateBridge.isPending}
              className="inline-flex items-center gap-1.5 text-[0.85em] font-medium text-brand-700 dark:text-brand-300 bg-brand-50/80 dark:bg-brand-950/40 border border-brand-200 dark:border-brand-800 rounded-lg px-2.5 py-1 hover:bg-brand-100 dark:hover:bg-brand-900/40 transition"
              title="将当前综合难题拆解为 1~2 道微步骤阶梯小题辅助破局"
            >
              <span>🧱</span>
              <span>{generateBridge.isPending ? "AI 正在拆解支线小题…" : "太难卡壳了？拆解做两道支线小题"}</span>
            </button>
          </div>
        )}
      </div>
    );

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3.5 exercise-card-root">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {level != null && <Badge color="blue">🎮 第 {level} 关</Badge>}
          <Badge color={isCode ? "blue" : isMath ? "purple" : isChoice || isFill ? "amber" : "gray"}>
            {isCode ? "💻 代码关" : isMath ? "📐 数学计算关" : isChoice ? "🔤 单选题" : isFill ? "✏️ 填空题" : "💬 概念题"}
          </Badge>
          {locked && <Badge color="gray">🔒 未解锁</Badge>}
          {attempt?.passed === true && <Badge color="green">✅ 通关</Badge>}
          {attempt?.passed === false && <Badge color="red">❌ 未通过</Badge>}
          {attempt?.is_doubtful && <Badge color="amber">🤔 存疑作答</Badge>}
          {exercise.is_hard_bone && <Badge color="amber">🦴 硬骨头暂存</Badge>}
          {exercise.parent_exercise_id && <Badge color="purple">🧱 支线阶梯</Badge>}
          {exercise.self_verified === 1 && (
            <Badge color="green" title="出题时已通过沙箱实测：参考实现与目标输出严格一致">
              🧪 已实测
            </Badge>
          )}
          {exercise.self_verified === 2 && (
            <Badge color="amber" title="出题时模型给出的目标输出与实际运行结果不符，已按实际运行输出自动校准">
              🧪 输出已校准
            </Badge>
          )}
          {attempt && isCode && STATUS_BADGE[attempt.status] && (
            <Badge color={STATUS_BADGE[attempt.status].color}>{STATUS_BADGE[attempt.status].label}</Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0 flex-wrap">
          {isCode && !exercise.parent_exercise_id && (
            <button
              type="button"
              onClick={() => toggleHardBone.mutate()}
              disabled={toggleHardBone.isPending}
              className={`inline-flex items-center gap-1 text-[0.8em] px-2 py-0.5 rounded border transition font-medium ${
                exercise.is_hard_bone
                  ? "border-amber-400 bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"
                  : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:border-amber-300 hover:text-amber-700"
              }`}
              title={exercise.is_hard_bone ? "取消硬骨头标记" : "卡壳了？标记为硬骨头先跳过，解锁下一关并在首页留存待攻克"}
            >
              <span>🦴</span>
              <span>{exercise.is_hard_bone ? "已标硬骨头" : "硬骨头跳过"}</span>
            </button>
          )}
          {assistant && (
            <button
              type="button"
              onClick={askAssistant}
              className="inline-flex items-center gap-1 text-[0.8em] px-2 py-0.5 rounded border transition font-medium border-amber-300 dark:border-amber-700/80 bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900/40 shadow-xs"
              title="在右侧 AI 助教中连续追问本题（自动带上当前作答与判题状态）"
            >
              <span>🤖</span>
              <span>问 AI 助教</span>
            </button>
          )}
          <button
            className="text-[0.75em] text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400"
            title="删除此题"
            onClick={() => {
              if (confirm("删除这道练习题及其作答记录？")) remove.mutate();
            }}
          >
            删除
          </button>
        </div>
      </div>
      <div className="mt-1.5 exercise-card-title font-medium text-gray-800 dark:text-gray-200">{exercise.title}</div>
      <div className="msg-md exercise-task-md mt-1 text-gray-600 dark:text-gray-400 [&_p]:my-1">
        <MarkdownLite text={exercise.task_md} />
      </div>

      {isCode ? (
        locked ? (
          <div className="mt-2 rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 px-3 py-2.5 text-[0.88em] text-gray-500 dark:text-gray-400">
            🔒 通关上一关后解锁挑战
          </div>
        ) : (
          <>
            {hints.length > 0 && (
              <div className="mt-2 space-y-1.5">
                {hints.slice(0, hintsShown).map((h, i) => (
                  <div
                    key={i}
                    className="rounded-lg bg-amber-50 dark:bg-amber-900/20 px-3 py-2 exercise-hint-box text-amber-800 dark:text-amber-200"
                  >
                    💡 提示 {i + 1}：{h}
                  </div>
                ))}
                {hintsShown < hints.length && (
                  <button
                    className="text-[0.85em] text-amber-600 dark:text-amber-300 underline hover:text-amber-700 dark:hover:text-amber-200"
                    onClick={() => setHintsShown((n) => n + 1)}
                  >
                    再给一条提示（{hintsShown + 1}/{hints.length}）
                  </button>
                )}
              </div>
            )}
            <div className="mt-2">
              <div className="mb-1 text-[0.85em] font-medium text-gray-500 dark:text-gray-400">
                🎯 目标输出（运行结果必须与之逐字符一致）
              </div>
              <pre className="whitespace-pre-wrap rounded-lg bg-gray-900/95 p-2.5 font-mono exercise-terminal-box text-green-200">
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
              className="mt-2 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-2.5 font-mono exercise-code-editor text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <div className="mt-2 flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
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
              <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 select-none cursor-pointer">
                <input
                  type="checkbox"
                  checked={isDoubtful}
                  onChange={(e) => setIsDoubtful(e.target.checked)}
                  className="rounded text-brand-600 focus:ring-brand-500"
                />
                <span>🤔 存疑/不确定</span>
              </label>
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
                  className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left exercise-option-btn ${
                    picked
                      ? "border-brand-500 dark:border-brand-400 bg-brand-50 dark:bg-brand-900/40 text-brand-800"
                      : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:border-gray-300"
                  }`}
                >
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[0.8em] font-bold ${
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
          <div className="mt-2 flex items-center justify-between flex-wrap gap-2">
            <Button disabled={pending || !choicePick} onClick={() => submit.mutate()}>
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> 判定中…
                </>
              ) : (
                "提交答案"
              )}
            </Button>
            <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 select-none cursor-pointer">
              <input
                type="checkbox"
                checked={isDoubtful}
                onChange={(e) => setIsDoubtful(e.target.checked)}
                className="rounded text-brand-600 focus:ring-brand-500"
              />
              <span>🤔 存疑/不确定</span>
            </label>
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
            className="mt-2 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2.5 exercise-input-box text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <div className="mt-2 flex items-center justify-between flex-wrap gap-2">
            <Button disabled={pending || !answer.trim()} onClick={() => submit.mutate()}>
              {pending ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> 判定中…
                </>
              ) : (
                "提交答案"
              )}
            </Button>
            <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 select-none cursor-pointer">
              <input
                type="checkbox"
                checked={isDoubtful}
                onChange={(e) => setIsDoubtful(e.target.checked)}
                className="rounded text-brand-600 focus:ring-brand-500"
              />
              <span>🤔 存疑/不确定</span>
            </label>
          </div>
          {renderAttemptResult()}
        </>
      ) : isMath ? (
        <>
          <div className="mt-2">
            <div className="mb-1 text-[0.85em] font-medium text-gray-500 dark:text-gray-400">
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
              className="w-full rounded-lg border border-purple-200 dark:border-purple-800/60 bg-purple-50/20 dark:bg-purple-950/20 p-2.5 font-mono exercise-input-box text-gray-800 dark:text-gray-200 focus:border-purple-500 dark:focus:border-purple-400 focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
          </div>
          <div className="mt-2 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
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
            <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 select-none cursor-pointer">
              <input
                type="checkbox"
                checked={isDoubtful}
                onChange={(e) => setIsDoubtful(e.target.checked)}
                className="rounded text-brand-600 focus:ring-brand-500"
              />
              <span>🤔 存疑/不确定</span>
            </label>
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
            className="mt-2 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-2.5 exercise-code-editor text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <div className="mt-2 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <Button disabled={pending || !answer.trim()} onClick={() => submit.mutate()}>
                {pending ? (
                  <>
                    <Spinner className="h-3.5 w-3.5" /> AI 评分中…
                  </>
                ) : (
                  "提交评分"
                )}
              </Button>
              <span className="text-[0.75em] text-gray-400 dark:text-gray-500">按参考答案客观评分</span>
            </div>
            <label className="inline-flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 select-none cursor-pointer">
              <input
                type="checkbox"
                checked={isDoubtful}
                onChange={(e) => setIsDoubtful(e.target.checked)}
                className="rounded text-brand-600 focus:ring-brand-500"
              />
              <span>🤔 存疑/不确定</span>
            </label>
          </div>
          {attempt && (
            <div className="mt-2 space-y-2">
              {attempt.passed === true && (
                <div className="rounded-lg bg-green-50 dark:bg-green-900/30 px-3 py-2 exercise-result-banner font-medium text-green-700 dark:text-green-400">✅ 通过</div>
              )}
              {attempt.passed === false && (
                <div className="rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 exercise-result-banner font-medium text-red-700 dark:text-red-400">❌ 未通过</div>
              )}
              {attempt.feedback && (
                <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-2.5 exercise-task-md text-gray-700 dark:text-gray-300 [&_p]:my-1">
                  <MarkdownLite text={attempt.feedback} />
                </div>
              )}
              <button className="text-[0.85em] text-gray-400 dark:text-gray-500 underline hover:text-gray-600 dark:hover:text-gray-300" onClick={() => setRevealed((v) => !v)}>
                {revealed ? "收起参考答案" : "查看参考答案"}
              </button>
              {revealed && (
                <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-2.5 exercise-task-md text-gray-600 dark:text-gray-400 [&_p]:my-1">
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
