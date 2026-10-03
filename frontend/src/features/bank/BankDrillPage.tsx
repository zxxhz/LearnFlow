// 题库刷题页：随机练习 / 错题重刷两种模式，一轮抽 N 题，答完出小结；
// 轮中进度（轮 / 位置 / 作答）即时持久化 localStorage，中途退出可从「继续上次」恢复
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, Button, ErrorText, Select, Spinner } from "../../components/ui";
import BankQuestionCard from "./BankQuestionCard";
import type { BankAttemptResult, BankRound } from "../../lib/types";

const SIZES = [10, 20, 50];
const TYPE_LABEL: Record<string, string> = { single: "单选", multi: "多选", judge: "判断" };

// 未完成轮的存档：按题库分 key，退出刷题后进度保留，重进可继续
interface DrillDraft {
  round: BankRound;
  idx: number;
  results: Record<string, BankAttemptResult>;
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
  const [size, setSize] = useState(20);
  const [startError, setStartError] = useState("");

  // 轮中任何变化即时落盘；round 为空（无轮）时不写，round 归属不符（路由复用残留）也不写
  useEffect(() => {
    if (!round || round.bank_id !== bankId) return;
    saveDraft(bankId!, { round, idx, results });
  }, [bankId, round, idx, results]);

  const resumeDraft = () => {
    if (!draft) return;
    setRound(draft.round);
    setIdx(draft.idx);
    setResults({ ...draft.results });
  };

  const discardRound = () => {
    setDraft(null);
    saveDraft(bankId!, null);
    setRound(null);
  };

  const start = useMutation({
    mutationFn: (mode: "random" | "wrong") => api.banks.round(bankId!, mode, size),
    onSuccess: (r) => {
      setRound(r);
      setIdx(0);
      setResults({});
      setStartError("");
      qc.invalidateQueries({ queryKey: ["banks"] });
    },
    onError: (e) => setStartError((e as Error).message),
  });

  const onAnswered = (qId: string, r: BankAttemptResult) => {
    setResults((prev) => ({ ...prev, [qId]: r }));
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
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
          {round.mode === "wrong" ? "📕 错题重刷 · 小结" : "🎯 随机练习 · 小结"}
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          本轮 {questions.length} 题，答对 <span className="font-bold text-green-600 dark:text-green-400">{roundCorrect}</span> 题，
          答错 <span className="font-bold text-red-600 dark:text-red-400">{roundWrong.length}</span> 题。
          {round.mode === "random" && roundWrong.length > 0 && " 答错的题已进入错题池，可在错题重刷里巩固。"}
        </p>

        {roundWrong.length > 0 && (
          <div className="mt-4 space-y-3">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">本轮错题</h2>
            {roundWrong.map((q) => {
              const r = results[q.id];
              return (
                <div key={q.id} className="rounded-lg border border-red-100 dark:border-red-900/40 bg-red-50/50 dark:bg-red-900/10 p-3 text-sm">
                  <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
                    <Badge color="red">{TYPE_LABEL[q.qtype]}</Badge>
                    <span>第 {q.seq} 题</span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-gray-800 dark:text-gray-200">{q.title}</p>
                  <p className="mt-1 text-xs text-green-700 dark:text-green-400">正确答案：{r.correct_answer}</p>
                  {r.explanation && (
                    <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-gray-500 dark:text-gray-400">{r.explanation}</p>
                  )}
                </div>
              );
            })}
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
        <BankQuestionCard key={current.id} question={current} onAnswered={(r) => onAnswered(current.id, r)} />
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
      <Link to="/bank" className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300">
        ← 题库列表
      </Link>
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
