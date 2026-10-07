// 题库刷题页：随机练习 / 错题重刷两种模式，一轮抽 N 题，答完出小结；
// 轮中进度（轮 / 位置 / 作答）即时持久化 localStorage，中途退出可从「继续上次」恢复
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";
import { api } from "../../lib/api";
import { Badge, Button, ErrorText, Select, Spinner } from "../../components/ui";
import { FontSizeControl } from "../../components/FontSizeControl";
import { useFontSize } from "../../lib/fontSize";
import BankQuestionCard, { visibleOptions } from "./BankQuestionCard";
import BankPromptModal from "./BankPromptModal";
import type { BankAttemptResult, BankQuestion, BankRound } from "../../lib/types";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
const KATEX_DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "$", right: "$", display: false },
];

const SIZES = [10, 20, 50];
const TYPE_LABEL: Record<string, string> = { single: "单选", multi: "多选", judge: "判断" };

// 未完成轮的存档：按题库分 key，退出刷题后进度保留，重进可继续
interface DrillDraft {
  round: BankRound;
  idx: number;
  results: Record<string, BankAttemptResult>;
  aiExplains?: Record<string, string>;
}

const draftKey = (bankId: string) => `learnflow.bank-drill.${bankId}`;

function loadDraft(bankId: string): DrillDraft | null {
  try {
    const raw = localStorage.getItem(draftKey(bankId));
    if (!raw) return null;
    const d = JSON.parse(raw) as DrillDraft;
    if (d.round?.bank_id !== bankId || d.round.questions.length === 0) return null;
    if (typeof d.idx !== "number" || d.idx < 0) return null;
    return d;
  } catch {
    return null;
  }
}

function saveDraft(bankId: string, d: DrillDraft | null) {
  try {
    if (!d) localStorage.removeItem(draftKey(bankId));
    else localStorage.setItem(draftKey(bankId), JSON.stringify(d));
  } catch {
    // 存储不可用（隐私模式 / 配额满）：进度持久化失败不影响作答
  }
}

export default function BankDrillPage() {
  const { bankId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { fontSize: drillFontSize, setFontSize: setDrillFontSize } = useFontSize("drill");

  const { data: banks, isLoading, error: loadError } = useQuery({
    queryKey: ["banks"],
    queryFn: api.banks.list,
  });
  const bank = banks?.find((b) => b.id === bankId);

  // 存档恢复：答完的轮（小结态）直接回看；未答完的不自动跳，经模式选择页「继续上次」恢复
  const [draft, setDraft] = useState<DrillDraft | null>(() => loadDraft(bankId!));
  const draftFinished = !!draft && draft.idx >= draft.round.questions.length;
  const [round, setRound] = useState<BankRound | null>(() => (draftFinished ? draft!.round : null));
  const [idx, setIdx] = useState(() => (draftFinished ? draft!.idx : 0));
  const [results, setResults] = useState<Record<string, BankAttemptResult>>(() =>
    draftFinished ? { ...draft!.results } : {},
  );
  const [aiExplains, setAiExplains] = useState<Record<string, string>>(() => {
    const fromDraft = draft?.aiExplains || {};
    const fromQuestions: Record<string, string> = {};
    if (draft?.round?.questions) {
      for (const q of draft.round.questions) {
        if (q.ai_explanation) fromQuestions[q.id] = q.ai_explanation;
      }
    }
    return { ...fromQuestions, ...fromDraft };
  });
  const [size, setSize] = useState(20);
  const [startError, setStartError] = useState("");
  const [promptOpen, setPromptOpen] = useState(false);

  // 轮中任何变化即时落盘；round 为空（无轮）时不写，round 归属不符（路由复用残留）也不写
  useEffect(() => {
    if (!round || round.bank_id !== bankId) return;
    saveDraft(bankId!, { round, idx, results, aiExplains });
  }, [bankId, round, idx, results, aiExplains]);

  const handleAiExplained = (qId: string, text: string) => {
    setAiExplains((prev) => ({ ...prev, [qId]: text }));
  };

  const resumeDraft = () => {
    if (!draft) return;
    setRound(draft.round);
    setIdx(draft.idx);
    setResults({ ...draft.results });
    if (draft.aiExplains) setAiExplains({ ...draft.aiExplains });
  };

  const discardRound = () => {
    setDraft(null);
    saveDraft(bankId!, null);
    setRound(null);
    setAiExplains({});
  };

  const start = useMutation({
    mutationFn: (mode: "random" | "wrong") => api.banks.round(bankId!, mode, size),
    onSuccess: (r) => {
      setRound(r);
      setIdx(0);
      setResults({});
      setStartError("");
      const initialAi: Record<string, string> = {};
      for (const q of r.questions) {
        if (q.ai_explanation) initialAi[q.id] = q.ai_explanation;
      }
      setAiExplains(initialAi);
      qc.invalidateQueries({ queryKey: ["banks"] });
    },
    onError: (e) => setStartError((e as Error).message),
  });

  const onAnswered = (qId: string, r: BankAttemptResult) => {
    setResults((prev) => ({ ...prev, [qId]: r }));
    if (r.ai_explanation) {
      setAiExplains((prev) => ({ ...prev, [qId]: prev[qId] || r.ai_explanation! }));
    }
    qc.invalidateQueries({ queryKey: ["banks"] });
  };

  const questions = round?.questions ?? [];
  const current = questions[idx];
  const answeredCount = Object.keys(results).length;
  const roundCorrect = questions.filter((q) => results[q.id]?.passed).length;
  const roundWrong = useMemo(
    () => questions.filter((q) => results[q.id] && !results[q.id].passed),
    [questions, results],
  );

  if (isLoading) {
    return (
      <div className="flex justify-center p-16">
        <Spinner />
      </div>
    );
  }
  if (!bank) {
    return (
      <div className="mx-auto max-w-5xl p-8">
        <ErrorText>{loadError ? (loadError as Error).message : "题库不存在"}</ErrorText>
        <Button variant="secondary" className="mt-3" onClick={() => navigate("/bank")}>
          ← 返回题库列表
        </Button>
      </div>
    );
  }

  // ---------- 轮末小结（答完最后一题后手动进入，避免跳过判分反馈） ----------
  if (round && idx >= questions.length && questions.length > 0) {
    return (
      <div className="mx-auto max-w-5xl p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {round.mode === "wrong" ? "📕 错题重刷 · 小结" : "🎯 随机练习 · 小结"}
          </h1>
          <FontSizeControl
            value={drillFontSize}
            onChange={setDrillFontSize}
            defaultValue={15}
            label="字号"
          />
        </div>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          本轮 {questions.length} 题，答对 <span className="font-bold text-green-600 dark:text-green-400">{roundCorrect}</span> 题，
          答错 <span className="font-bold text-red-600 dark:text-red-400">{roundWrong.length}</span> 题。
          {round.mode === "random" && roundWrong.length > 0 && " 答错的题已进入错题池，可在错题重刷里巩固。"}
        </p>

        {roundWrong.length > 0 && (
          <div
            className="mt-4 space-y-3 drill-content-root"
            style={{ "--drill-font-size": `${drillFontSize}px` } as React.CSSProperties}
          >
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">本轮错题</h2>
            {roundWrong.map((q) => (
              <WrongQuestionItem
                key={q.id}
                question={q}
                result={results[q.id]}
                initialAiExplain={aiExplains[q.id] || q.ai_explanation}
                onAiExplained={(text) => handleAiExplained(q.id, text)}
              />
            ))}
          </div>
        )}

        <div className="mt-6 flex gap-2">
          <Button
            onClick={() =>
              start.mutate(round.mode === "wrong" && round.wrong_pool_size === 0 ? "random" : round.mode)
            }
            disabled={start.isPending}
          >
            {start.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
            {round.mode === "wrong" ? "再刷一轮错题" : "再来一轮"}
          </Button>
          <Button variant="secondary" onClick={discardRound}>
            返回模式选择
          </Button>
          <Link to="/bank" className="inline-flex items-center px-3 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300">
            ← 题库列表
          </Link>
        </div>
      </div>
    );
  }

  // ---------- 轮中作答 ----------
  if (round && current) {
    return (
      <div className="mx-auto max-w-5xl p-8">
        <div className="mb-3 flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => navigate("/bank")}
            title="返回题库列表，本轮进度已保留，下次进入可继续"
          >
            ← 退出本轮
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-base font-bold text-gray-900 dark:text-gray-100">
            {round.mode === "wrong" ? "📕 错题重刷" : "🎯 随机练习"} · {bank.name}
          </h1>
          <FontSizeControl
            value={drillFontSize}
            onChange={setDrillFontSize}
            defaultValue={15}
            label="字号"
          />
          <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">
            {idx + 1} / {questions.length}
          </span>
        </div>
        <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
          <div
            className="h-full rounded-full bg-brand-500 transition-all"
            style={{ width: `${((idx + (results[current.id] ? 1 : 0)) / questions.length) * 100}%` }}
          />
        </div>
        <div
          className="drill-content-root"
          style={{ "--drill-font-size": `${drillFontSize}px` } as React.CSSProperties}
        >
          <BankQuestionCard
            key={current.id}
            question={current}
            initialAiExplain={aiExplains[current.id] || current.ai_explanation}
            onAiExplained={(text) => handleAiExplained(current.id, text)}
            onAnswered={(r) => onAnswered(current.id, r)}
          />
        </div>
        <div className="mt-4 flex justify-end">
          {idx < questions.length - 1 ? (
            <Button disabled={!results[current.id]} onClick={() => setIdx(idx + 1)}>
              下一题 →
            </Button>
          ) : (
            <Button disabled={!results[current.id]} onClick={() => setIdx(idx + 1)}>
              查看小结
            </Button>
          )}
        </div>
      </div>
    );
  }

  // ---------- 模式选择 ----------
  const s = bank.stats;
  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="flex items-center justify-between">
        <Link to="/bank" className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300">
          ← 题库列表
        </Link>
        <div className="flex items-center gap-2">
          <FontSizeControl
            value={drillFontSize}
            onChange={setDrillFontSize}
            defaultValue={15}
            label="刷题字号"
          />
          <button
            type="button"
            onClick={() => setPromptOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2.5 py-1 text-xs text-gray-700 dark:text-gray-300 hover:border-brand-500 hover:text-brand-600 dark:hover:text-brand-400 transition"
            title="自定义此题库的 AI 错题解答提示词与润色"
          >
            <span>⚙️</span>
            <span>AI 提示词设置</span>
            {bank.ai_prompt?.trim() && (
              <span className="h-1.5 w-1.5 rounded-full bg-brand-500" title="已自定义" />
            )}
          </button>
        </div>
      </div>
      <h1 className="mt-1 text-2xl font-bold text-gray-900 dark:text-gray-100">🎯 {bank.name}</h1>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">来源：{bank.source_file}</p>

      {draft && !draftFinished && (
        <div className="mt-4 rounded-xl border border-brand-200 dark:border-brand-800 bg-brand-50/60 dark:bg-brand-900/20 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                ↩ 上次刷到第 {Math.min(draft.idx + 1, draft.round.questions.length)} /{" "}
                {draft.round.questions.length} 题
              </h2>
              <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                已作答 {Object.keys(draft.results).length} 题，进度已保留；开始新一轮会覆盖它。
              </p>
            </div>
            <Button onClick={resumeDraft}>继续刷题 →</Button>
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="题库总题数" value={String(s.question_count)} />
        <StatCard label="已答（题）" value={String(s.answered)} />
        <StatCard label="累计正确率" value={`${s.accuracy}%`} />
        <StatCard
          label="错题池"
          value={String(s.wrong_count)}
          tone={s.wrong_count > 0 ? "red" : undefined}
        />
      </div>

      <div className="mt-6 space-y-3">
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">🎯 随机练习</h2>
              <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                从全部 {s.question_count} 题里随机抽一轮，答错自动进错题池。
              </p>
            </div>
            <Select
              value={size}
              onChange={(e) => setSize(Number(e.target.value))}
              className="!w-28"
            >
              {SIZES.map((n) => (
                <option key={n} value={n}>
                  每轮 {n} 题
                </option>
              ))}
            </Select>
            <Button disabled={start.isPending} onClick={() => start.mutate("random")}>
              {start.isPending ? <Spinner className="h-3.5 w-3.5" /> : null} 开始
            </Button>
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">📕 错题重刷</h2>
              <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                错题池 {s.wrong_count} 题；重刷答对即出池。
              </p>
            </div>
            <Button
              variant="secondary"
              disabled={start.isPending || s.wrong_count === 0}
              onClick={() => start.mutate("wrong")}
            >
              开始
            </Button>
          </div>
        </div>
        <ErrorText>{startError}</ErrorText>
      </div>

      <BankPromptModal
        open={promptOpen}
        bank={bank}
        onClose={() => setPromptOpen(false)}
      />
    </div>
  );
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: "red" }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3">
      <div className={`text-lg font-bold ${tone === "red" ? "text-red-600 dark:text-red-400" : "text-gray-900 dark:text-gray-100"}`}>
        {value}
      </div>
      <div className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{label}</div>
    </div>
  );
}

function WrongQuestionItem({
  question,
  result,
  initialAiExplain,
  onAiExplained,
}: {
  question: BankQuestion;
  result?: BankAttemptResult;
  initialAiExplain?: string;
  onAiExplained?: (text: string) => void;
}) {
  const existingExplain = initialAiExplain || question.ai_explanation || "";
  const [aiOpen, setAiOpen] = useState(!!existingExplain);
  const [aiThinking, setAiThinking] = useState(false);
  const [aiStreaming, setAiStreaming] = useState(false);
  const [aiText, setAiText] = useState(existingExplain);
  const [aiError, setAiError] = useState("");
  const aiStreamRef = useRef<HTMLDivElement>(null);
  const opts = visibleOptions(question);

  const cardRef = useRef<HTMLDivElement>(null);

  // 错题卡片题干与选项公式渲染
  useEffect(() => {
    if (cardRef.current) {
      try {
        renderMathInElement(cardRef.current, {
          delimiters: KATEX_DELIMITERS,
          throwOnError: false,
        });
      } catch (err) {
        console.warn("KaTeX render error on wrong item card:", err);
      }
    }
  }, [question.id, question.title, question.options]);

  useEffect(() => {
    if (aiStreamRef.current && aiText) {
      try {
        renderMathInElement(aiStreamRef.current, {
          delimiters: KATEX_DELIMITERS,
          throwOnError: false,
        });
      } catch (err) {
        console.warn("KaTeX render error:", err);
      }
    }
  }, [aiText]);

  const userPicked = useMemo(() => {
    if (!result?.answer) return [];
    return result.answer.split("").filter(Boolean);
  }, [result]);

  const correctPicked = useMemo(() => {
    if (!result?.correct_answer) return [];
    return result.correct_answer.split("").filter(Boolean);
  }, [result]);

  async function startAiExplain() {
    setAiThinking(true);
    setAiStreaming(true);
    setAiText("");
    setAiError("");

    let acc = "";
    try {
      await api.banks.explainSSE(
        question.id,
        userPicked,
        (ev) => {
          if (ev.type === "delta" && ev.text) {
            setAiThinking(false);
            acc += ev.text;
            setAiText(acc);
            onAiExplained?.(acc);
          } else if (ev.type === "done") {
            setAiThinking(false);
            setAiStreaming(false);
            onAiExplained?.(acc);
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
    <div ref={cardRef} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
        <Badge color={question.qtype === "multi" ? "amber" : question.qtype === "judge" ? "blue" : "gray"}>
          {TYPE_LABEL[question.qtype] ?? question.qtype}
        </Badge>
        {question.difficulty && <span>难度：{question.difficulty}</span>}
        <span className="ml-auto">第 {question.seq} 题</span>
      </div>
      <p className="drill-question-title mt-2 leading-relaxed text-gray-900 dark:text-gray-100 font-medium">
        {question.title}
      </p>

      {/* 选项 */}
      <div className="mt-2.5 space-y-1.5">
        {opts.map((opt) => {
          const isUserPicked = userPicked.includes(opt.letter);
          const isCorrect = correctPicked.includes(opt.letter);
          return (
            <div
              key={opt.letter}
              className={`drill-option-btn flex items-center gap-2.5 rounded-lg border px-3 py-1.5 ${
                isCorrect
                  ? "border-green-400 dark:border-green-600 bg-green-50/70 dark:bg-green-950/30 text-green-800 dark:text-green-300 font-medium"
                  : isUserPicked
                  ? "border-red-400 dark:border-red-600 bg-red-50/70 dark:bg-red-950/30 text-red-800 dark:text-red-300 font-medium"
                  : "border-gray-200 dark:border-gray-700 bg-gray-50/40 dark:bg-gray-800/30 text-gray-600 dark:text-gray-400"
              }`}
            >
              <span
                className={`drill-option-badge flex shrink-0 items-center justify-center font-bold rounded ${
                  isCorrect
                    ? "bg-green-600 text-white"
                    : isUserPicked
                    ? "bg-red-500 text-white"
                    : "bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
                }`}
              >
                {opt.letter}
              </span>
              <span>{opt.text}</span>
            </div>
          );
        })}
      </div>

      {result && (
        <div className="drill-result-banner mt-3 rounded-lg bg-gray-50 dark:bg-gray-800/60 p-2.5">
          <div className="text-red-700 dark:text-red-400 font-semibold">
            ✗ 你的作答：{result.answer || "未选"} · 正确答案：{result.correct_answer}
          </div>
          {result.explanation && (
            <p className="drill-explanation-text mt-1 whitespace-pre-wrap leading-relaxed text-gray-600 dark:text-gray-400">
              {result.explanation}
            </p>
          )}

          {/* AI 深度流式解答 */}
          <div className="mt-2.5 border-t border-gray-200/60 dark:border-gray-700/60 pt-2.5">
            {!aiOpen ? (
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  💡 想看这道题的详细原理解析？
                </span>
                <Button
                  variant="secondary"
                  className="text-xs !py-1 text-brand-600 dark:text-brand-400 border-brand-200 dark:border-brand-800 hover:bg-brand-50 dark:hover:bg-brand-950/40"
                  onClick={() => {
                    setAiOpen(true);
                    if (!aiText) startAiExplain();
                  }}
                >
                  {aiText ? "🤖 查看已生成的 AI 解析" : "🤖 获取 AI 深度解析"}
                </Button>
              </div>
            ) : (
              <div className="drill-ai-box rounded-lg border border-brand-200 dark:border-brand-800 bg-brand-50/50 dark:bg-brand-950/20 p-3 shadow-sm">
                <div className="flex items-center justify-between pb-2 border-b border-brand-100 dark:border-brand-900/60">
                  <div className="flex items-center gap-1.5 font-semibold text-brand-800 dark:text-brand-300">
                    <span>🤖 AI 助教错题剖析</span>
                    {aiStreaming ? (
                      <span className="inline-block h-2 w-2 rounded-full bg-brand-500 animate-ping" />
                    ) : (
                      <span className="rounded bg-brand-100 dark:bg-brand-900/60 px-1 py-0.2 text-[10px] text-brand-700 dark:text-brand-300 font-normal">
                        已保留
                      </span>
                    )}
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
                  <div className="py-3 flex items-center justify-center gap-2 text-gray-500 dark:text-gray-400">
                    <div className="flex space-x-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "300ms" }} />
                    </div>
                    <span>AI 正在剖析错因与考点…</span>
                  </div>
                )}

                {aiText && (
                  <div className="mt-2 text-gray-800 dark:text-gray-200 leading-relaxed overflow-x-auto">
                    <div
                      ref={aiStreamRef}
                      className="drill-ai-content prose prose-sm dark:prose-invert max-w-none leading-relaxed"
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
        </div>
      )}
    </div>
  );
}
