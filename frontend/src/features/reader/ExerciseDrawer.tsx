// 闯关练习抽屉：按知识点分组的关卡链 + 随堂小测（跨知识点组卷）（PRD §5.10）
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Exercise, KnowledgePoint } from "../../lib/types";
import { Button, Select, Spinner } from "../../components/ui";
import ExerciseCard from "./ExerciseCard";

interface Props {
  documentId: string;
  kps: KnowledgePoint[];
  exercises: Exercise[];
  focusKpId: string | null;
  closing?: boolean;
  onClose: () => void;
}

export default function ExerciseDrawer({
  documentId,
  kps,
  exercises,
  focusKpId,
  closing = false,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setMounted(true);
    }, 20);
    return () => clearTimeout(timer);
  }, []);

  const [langByKp, setLangByKp] = useState<Record<string, "python" | "cpp">>({});
  const [quizMode, setQuizMode] = useState(false);
  const [quizLang, setQuizLang] = useState<"python" | "cpp">("python");
  const [quizKpIds, setQuizKpIds] = useState<string[] | null>(null); // null = 全选
  const listRef = useRef<HTMLDivElement>(null);

  const { data: quizzes } = useQuery({
    queryKey: ["quizzes", documentId],
    queryFn: () => api.quizzes.list(documentId),
  });
  const activeQuiz = quizzes?.[0] ?? null;
  const selectedKpIds = quizKpIds ?? kps.map((k) => k.id);

  const byKp = useMemo(() => {
    const m = new Map<string, Exercise[]>();
    for (const e of exercises) {
      const list = m.get(e.knowledge_point_id) ?? [];
      list.push(e);
      m.set(e.knowledge_point_id, list);
    }
    // 每个知识点内：代码关按闯关顺序在前，其余题型按时间在后
    for (const list of m.values()) {
      list.sort((a, b) => {
        const aLadder = a.kind === "code" && !a.quiz_id ? 0 : 1;
        const bLadder = b.kind === "code" && !b.quiz_id ? 0 : 1;
        if (aLadder !== bLadder) return aLadder - bLadder;
        return (
          a.order_index - b.order_index ||
          a.created_at.localeCompare(b.created_at) ||
          a.id.localeCompare(b.id)
        );
      });
    }
    return m;
  }, [exercises]);

  // 代码关在各自知识点链内的关卡序号（1 起）
  const levelById = useMemo(() => {
    const m = new Map<string, number>();
    for (const list of byKp.values()) {
      let n = 0;
      for (const e of list) {
        if (e.kind === "code" && !e.quiz_id) m.set(e.id, ++n);
      }
    }
    return m;
  }, [byKp]);

  // 从知识点浮层进入时滚到对应分组
  useEffect(() => {
    if (!focusKpId) return;
    const t = setTimeout(() => {
      listRef.current?.querySelector(`[data-kp="${focusKpId}"]`)?.scrollIntoView({ block: "start" });
    }, 100);
    return () => clearTimeout(t);
  }, [focusKpId]);

  // 正在出题的知识点（跨 mutation 存活：不同知识点允许并发出题，同一知识点按钮禁用防重复触发）
  const [pendingKpIds, setPendingKpIds] = useState<string[]>([]);
  const generate = useMutation({
    mutationFn: async (body: { kpId: string; language: "python" | "cpp" }) => {
      const has = (byKp.get(body.kpId) ?? []).length > 0;
      if (has && !confirm("重新生成将替换该知识点现有的练习题和作答记录，继续？")) {
        throw new Error("cancelled");
      }
      setPendingKpIds((p) => (p.includes(body.kpId) ? p : [...p, body.kpId]));
      try {
        return await api.exercises.generate({ knowledge_point_id: body.kpId, language: body.language });
      } finally {
        setPendingKpIds((p) => p.filter((x) => x !== body.kpId));
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
    },
    onError: (e) => {
      if ((e as Error).message !== "cancelled") alert((e as Error).message);
    },
  });

  const generateQuiz = useMutation({
    mutationFn: (body: { kpIds: string[]; language: "python" | "cpp" }) =>
      api.quizzes.generate({ document_id: documentId, kp_ids: body.kpIds, language: body.language }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quizzes", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const removeQuiz = useMutation({
    mutationFn: (id: string) => api.quizzes.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quizzes", documentId] });
      queryClient.invalidateQueries({ queryKey: ["exercises-wrongbook"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const ladder = exercises.filter((e) => e.kind === "code" && !e.quiz_id);
  const cleared = ladder.filter((e) => e.ever_passed).length;
  const total = exercises.length;

  const isVisible = mounted && !closing;

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl sm:w-[420px] transition-transform duration-300 ease-out transform ${
        isVisible ? "translate-x-0" : "translate-x-full"
      }`}
    >
      <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">🎮 闯关练习{total > 0 && `（${total}）`}</span>
          <span className="text-[11px] rounded bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/60 px-1.5 py-0.5 text-amber-700 dark:text-amber-300 font-medium">
            💡 助教伴学
          </span>
          {ladder.length > 0 && (
            <span className={`text-xs font-medium ${cleared === ladder.length ? "text-green-600 dark:text-green-400" : "text-gray-400 dark:text-gray-500"}`}>
              已通关 {cleared}/{ladder.length} 关
            </span>
          )}
          {kps.length > 0 && (
            <Button
              variant="ghost"
              className="!px-2 !py-0.5 text-xs"
              onClick={() => setQuizMode((v) => !v)}
            >
              📋 随堂小测
            </Button>
          )}
        </div>
        <button className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300" onClick={onClose}>
          ✕
        </button>
      </div>
      <div ref={listRef} className="flex-1 space-y-4 overflow-auto p-3">
        {quizMode && kps.length > 0 && (
          <div className="space-y-3 rounded-xl border border-brand-200 dark:border-brand-700 bg-brand-50 dark:bg-brand-900/40 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-brand-800">📋 随堂小测</span>
              {activeQuiz && (
                <Button variant="ghost" className="!px-2 !py-0.5 text-xs text-red-500 dark:text-red-400" onClick={() => removeQuiz.mutate(activeQuiz.id)}>
                  删除当前小测
                </Button>
              )}
            </div>
            {generateQuiz.isPending ? (
              <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                <Spinner className="h-3.5 w-3.5" /> 正在出卷（单选/填空/代码各一部分）…
              </div>
            ) : activeQuiz ? (
              <>
                <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                  <span>
                    {activeQuiz.title} · 共 {activeQuiz.total} 题
                  </span>
                  <span className={activeQuiz.correct === activeQuiz.total && activeQuiz.total > 0 ? "font-bold text-green-600 dark:text-green-400" : ""}>
                    已通过 {activeQuiz.correct} / {activeQuiz.total}
                  </span>
                </div>
                <div className="space-y-2">
                  {activeQuiz.items.map((e) => (
                    <ExerciseCard key={e.id} exercise={e} documentId={documentId} />
                  ))}
                </div>
                <p className="text-[10px] text-gray-400 dark:text-gray-500">全部通过后可删除本卷重新生成；错题自动进错题本。</p>
              </>
            ) : (
              <>
                <div className="space-y-1">
                  {kps.map((kp) => (
                    <label key={kp.id} className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                      <input
                        type="checkbox"
                        checked={selectedKpIds.includes(kp.id)}
                        onChange={(e) =>
                          setQuizKpIds((p) => {
                            const cur = p ?? kps.map((k) => k.id);
                            return e.target.checked ? [...cur, kp.id] : cur.filter((x) => x !== kp.id);
                          })
                        }
                      />
                      {kp.title}
                    </label>
                  ))}
                </div>
                <div className="flex items-center gap-1.5">
                  <Select className="w-28 py-1 text-xs" value={quizLang} onChange={(e) => setQuizLang(e.target.value as "python" | "cpp")}>
                    <option value="python">Python</option>
                    <option value="cpp">C++</option>
                  </Select>
                  <Button
                    variant="secondary"
                    className="text-xs"
                    disabled={selectedKpIds.length === 0}
                    onClick={() => generateQuiz.mutate({ kpIds: selectedKpIds, language: quizLang })}
                  >
                    出卷（每知识点 1 题）
                  </Button>
                </div>
                <p className="text-[10px] text-gray-400 dark:text-gray-500">单选 + 填空 + 代码混合，全部自动判定；重新出卷会替换当前小测。</p>
              </>
            )}
          </div>
        )}
        {kps.length === 0 && (
          <p className="mt-8 text-center text-xs text-gray-400 dark:text-gray-500">本章还没有知识点，生成文档后即可闯关</p>
        )}
        {kps.map((kp) => {
          const list = byKp.get(kp.id) ?? [];
          const lang = langByKp[kp.id] ?? "python";
          const busy = pendingKpIds.includes(kp.id);
          return (
            <div key={kp.id} data-kp={kp.id} className="scroll-mt-2 space-y-2 rounded-xl border border-gray-100 dark:border-gray-800 p-2.5">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-gray-800 dark:text-gray-200">{kp.title}</div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-gray-400 dark:text-gray-500">{kp.summary}</p>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <Select
                  className="w-28 py-1 text-xs"
                  value={lang}
                  onChange={(e) => setLangByKp((p) => ({ ...p, [kp.id]: e.target.value as "python" | "cpp" }))}
                  aria-label="练习语言"
                >
                  <option value="python">Python</option>
                  <option value="cpp">C++</option>
                </Select>
                <Button
                  variant="secondary"
                  className="text-xs"
                  disabled={busy}
                  onClick={() => generate.mutate({ kpId: kp.id, language: lang })}
                >
                  {busy ? (
                    <>
                      <Spinner className="h-3.5 w-3.5" /> 出题中…
                    </>
                  ) : list.length > 0 ? (
                    "↻ 重新生成"
                  ) : (
                    "＋ 生成关卡"
                  )}
                </Button>
              </div>
              {list.length > 0 && (
                <div className="space-y-2">
                  {list.map((e) => (
                    <ExerciseCard key={e.id} exercise={e} documentId={documentId} level={levelById.get(e.id)} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
