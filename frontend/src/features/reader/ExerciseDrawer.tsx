// 练习抽屉：按知识点分组的做题面板，手动生成练习（PRD §5.10）
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Exercise, KnowledgePoint } from "../../lib/types";
import { Button, Select, Spinner } from "../../components/ui";
import ExerciseCard from "./ExerciseCard";

interface Props {
  documentId: string;
  kps: KnowledgePoint[];
  exercises: Exercise[];
  focusKpId: string | null;
  onClose: () => void;
}

const LANG_LABEL: Record<string, string> = { python: "Python", cpp: "C++" };

export default function ExerciseDrawer({ documentId, kps, exercises, focusKpId, onClose }: Props) {
  const queryClient = useQueryClient();
  const [langByKp, setLangByKp] = useState<Record<string, "python" | "cpp">>({});
  const listRef = useRef<HTMLDivElement>(null);

  const byKp = useMemo(() => {
    const m = new Map<string, Exercise[]>();
    for (const e of exercises) {
      const list = m.get(e.knowledge_point_id) ?? [];
      list.push(e);
      m.set(e.knowledge_point_id, list);
    }
    return m;
  }, [exercises]);

  // 从知识点浮层进入时滚到对应分组
  useEffect(() => {
    if (!focusKpId) return;
    const t = setTimeout(() => {
      listRef.current?.querySelector(`[data-kp="${focusKpId}"]`)?.scrollIntoView({ block: "start" });
    }, 100);
    return () => clearTimeout(t);
  }, [focusKpId]);

  const generate = useMutation({
    mutationFn: (body: { kpId: string; language: "python" | "cpp" }) => {
      const has = (byKp.get(body.kpId) ?? []).length > 0;
      if (has && !confirm("重新生成将替换该知识点现有的练习题和作答记录，继续？")) {
        return Promise.reject(new Error("cancelled"));
      }
      return api.exercises.generate({ knowledge_point_id: body.kpId, language: body.language });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
    },
    onError: (e) => {
      if ((e as Error).message !== "cancelled") alert((e as Error).message);
    },
  });

  const total = exercises.length;

  return (
    <div className="fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 bg-white shadow-lg sm:w-[420px]">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <span className="text-sm font-semibold text-gray-900">📝 练习{total > 0 && `（${total}）`}</span>
        <button className="text-gray-400 hover:text-gray-600" onClick={onClose}>
          ✕
        </button>
      </div>
      <div ref={listRef} className="flex-1 space-y-4 overflow-auto p-3">
        {kps.length === 0 && (
          <p className="mt-8 text-center text-xs text-gray-400">本章还没有知识点，生成文档后即可出练习</p>
        )}
        {kps.map((kp) => {
          const list = byKp.get(kp.id) ?? [];
          const lang = langByKp[kp.id] ?? "python";
          const busy = generate.isPending && generate.variables?.kpId === kp.id;
          return (
            <div key={kp.id} data-kp={kp.id} className="scroll-mt-2 space-y-2 rounded-xl border border-gray-100 p-2.5">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-gray-800">{kp.title}</div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-gray-400">{kp.summary}</p>
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
                    "＋ 生成练习"
                  )}
                </Button>
              </div>
              {list.length > 0 && (
                <div className="space-y-2">
                  {list.map((e) => (
                    <ExerciseCard key={e.id} exercise={e} documentId={documentId} />
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
