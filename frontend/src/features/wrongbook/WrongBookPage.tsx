// 错题本：最近一次作答未通过的练习（跨课程），重刷通过后自动出池
// v0.5.0：接入统一 AI 助教——错题卡「问 AI 助教」打开 document 会话，与对应章节阅读页上下文延续
import { useCallback, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { EmptyState, Spinner } from "../../components/ui";
import ExerciseCard from "../reader/ExerciseCard";
import AssistantPanel from "../../components/AssistantPanel";
import { ReaderAssistantContext } from "../reader/assistantContext";
import FontSizeControl from "../../components/FontSizeControl";
import { useFontSize } from "../../lib/fontSize";
import type { AssistantSceneContext } from "../../lib/types";

export default function WrongBookPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["exercises-wrongbook"],
    queryFn: api.exercises.wrongbook,
  });
  // 设置页口径：错题练习字号走 drill 档（与题库练习一致），course 档是阅读正文
  const { fontSize, setFontSize } = useFontSize("drill");

  // 统一助教：document 会话（与该题所属章节的阅读页共用连续上下文）
  const [assistant, setAssistant] = useState<{
    scene: AssistantSceneContext;
    label: string;
  } | null>(null);
  const [closing, setClosing] = useState(false);
  // 关闭动画定时器须可取消：关后 300ms 内再开时陈旧回调会把面板再次关掉（v0.5.1 体检 P2）
  const assistantCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeAssistant = useCallback(() => {
    setClosing(true);
    if (assistantCloseTimerRef.current) clearTimeout(assistantCloseTimerRef.current);
    assistantCloseTimerRef.current = setTimeout(() => {
      assistantCloseTimerRef.current = null;
      setAssistant(null);
      setClosing(false);
    }, 300);
  }, []);
  // Provider value 必须是稳定引用（useMemo 直接给对象）：工厂函数会让 context value
  // 每次渲染恒变，触发全部 ExerciseCard 消费者（含 KaTeX/Shiki 重组件）无谓重渲染
  const assistantApi = useMemo(
    () => ({
      openAssistant: (scene: AssistantSceneContext, label: string) => {
        if (assistantCloseTimerRef.current) {
          clearTimeout(assistantCloseTimerRef.current);
          assistantCloseTimerRef.current = null;
        }
        setClosing(false);
        setAssistant({ scene, label });
      },
    }),
    []
  );

  return (
    <ReaderAssistantContext.Provider value={assistantApi}>
      <div className="mx-auto max-w-5xl p-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">📕 错题本</h1>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              最近一次作答未通过的题都在这里；重刷通过后自动出池。
            </p>
          </div>
          <FontSizeControl value={fontSize} onChange={setFontSize} defaultValue={15} label="字号" />
        </div>
        {isLoading ? (
          <div className="mt-10 flex justify-center">
            <Spinner />
          </div>
        ) : isError ? (
          <EmptyState
            icon="⚠️"
            title="错题本加载失败"
            hint={(error as Error)?.message ?? "服务暂时不可用，请稍后重试"}
            action={
              <button
                type="button"
                onClick={() => refetch()}
                className="mt-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                重试
              </button>
            }
          />
        ) : !data || data.length === 0 ? (
          <EmptyState icon="🎉" title="没有错题" hint="练习里做错的题会自动收集到这里。" />
        ) : (
          <div
            className="mt-4 space-y-4 exercise-drawer-root"
            style={{ "--course-font-size": `${fontSize}px` } as React.CSSProperties}
          >
            {data.map((e) => (
              <div key={e.id}>
                <div className="mb-1 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
                  <span>
                    {e.kp_title ?? "（知识点已删除）"} ·{" "}
                    {e.kind === "code"
                      ? "代码题"
                      : e.kind === "choice"
                      ? "单选"
                      : e.kind === "fill"
                      ? "填空"
                      : e.kind === "math"
                      ? "数学题"
                      : "概念题"}
                  </span>
                  <Link to={`/read/${e.document_id}`} className="text-brand-600 underline">
                    前往章节 ↗
                  </Link>
                </div>
                <ExerciseCard exercise={e} documentId={e.document_id} />
              </div>
            ))}
          </div>
        )}

        {/* 统一 AI 助教面板（错题本入口，仍归属对应章节 document 会话） */}
        {assistant && (
          <AssistantPanel
            open
            closing={closing}
            contextType="document"
            contextId={assistant.scene.document_id ?? ""}
            contextLabel={assistant.label}
            scene={assistant.scene}
            fontSize={fontSize}
            onClose={closeAssistant}
          />
        )}
      </div>
    </ReaderAssistantContext.Provider>
  );
}
