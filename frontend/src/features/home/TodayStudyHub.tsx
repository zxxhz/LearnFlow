import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Button, Spinner } from "../../components/ui";

export function TodayStudyHub() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["today-study-hub"],
    queryFn: api.study.today,
    staleTime: 10_000,
  });

  if (isLoading) {
    return (
      <div className="mb-6 rounded-2xl border border-gray-100 dark:border-gray-800 bg-white/70 dark:bg-gray-800/40 p-4 shadow-2xs flex items-center justify-center gap-2 text-xs text-gray-400">
        <Spinner className="h-4 w-4" /> 正在汇总今日学情行动…
      </div>
    );
  }

  if (isError || !data) return null;

  const hasAction =
    !!data.last_read ||
    data.hard_bones.length > 0 ||
    data.bank_wrong_count > 0 ||
    data.active_misconceptions.length > 0;

  return (
    <div className="mb-8 rounded-2xl border border-brand-200/70 dark:border-brand-800/50 bg-gradient-to-br from-brand-50/40 via-white to-indigo-50/30 dark:from-gray-900/60 dark:via-gray-900/40 dark:to-brand-950/30 p-5 shadow-sm transition-all">
      <div className="flex items-center justify-between pb-3.5 border-b border-gray-100 dark:border-gray-800/80 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-base">✨</span>
          <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100">
            「今天」学习行动中枢
          </h2>
          <span className="rounded-full bg-brand-100 dark:bg-brand-950/60 border border-brand-200 dark:border-brand-800 px-2 py-0.2 text-[10px] font-semibold text-brand-700 dark:text-brand-300">
            今日聚焦
          </span>
        </div>
        {data.today_read_seconds > 0 && (
          <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-full px-2.5 py-0.5">
            ⏱ 今日专注投入 {Math.round(data.today_read_seconds / 60)} 分钟
          </span>
        )}
      </div>

      <div className="mt-3.5 space-y-3">
        {/* 1. 继续阅读上次章节 */}
        {data.last_read && (
          <div className="flex items-center justify-between gap-3 bg-white dark:bg-gray-800/90 p-3 rounded-xl border border-gray-100 dark:border-gray-700 shadow-2xs">
            <div className="flex items-center gap-2.5 truncate">
              <span className="text-lg shrink-0">📖</span>
              <div className="truncate">
                <div className="text-[10px] text-gray-400 dark:text-gray-500">继续未完研读</div>
                <div className="text-xs font-bold text-gray-900 dark:text-gray-100 truncate">
                  《{data.last_read.course_title}》第 {data.last_read.chapter_index} 章 《{data.last_read.chapter_title}》
                </div>
              </div>
            </div>
            <Button
              variant="primary"
              className="text-xs !py-1 !px-3 shrink-0 !bg-brand-600 hover:!bg-brand-700 text-white font-medium shadow-2xs"
              onClick={() => navigate(`/read/${data.last_read!.document_id}`)}
            >
              秒回阅读 ➔
            </Button>
          </div>
        )}

        {/* 2. 待攻克硬骨头关卡 */}
        {data.hard_bones.length > 0 && (
          <div className="bg-amber-50/50 dark:bg-amber-950/20 p-3 rounded-xl border border-amber-200/80 dark:border-amber-900/40 text-xs">
            <div className="flex items-center justify-between mb-2 font-semibold text-amber-900 dark:text-amber-200">
              <span className="flex items-center gap-1.5">
                <span>🦴</span>
                <span>暂存待攻克硬骨头 ({data.hard_bones.length} 关)</span>
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {data.hard_bones.map((hb) => (
                <button
                  key={hb.id}
                  onClick={() => navigate(`/read/${hb.document_id}`)}
                  className="rounded-lg bg-white dark:bg-gray-800 border border-amber-300 dark:border-amber-700 px-2.5 py-1 text-[11px] text-gray-800 dark:text-gray-200 hover:border-amber-500 transition flex items-center gap-1.5 shadow-2xs font-medium"
                >
                  <span>🎯</span>
                  <span className="truncate max-w-[180px]">{hb.title}</span>
                  <span className="text-[10px] text-amber-600">➔</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 3. 题库错题待清零 */}
        {data.bank_wrong_count > 0 && (
          <div className="flex items-center justify-between gap-3 bg-rose-50/40 dark:bg-rose-950/20 p-3 rounded-xl border border-rose-200/60 dark:border-rose-900/40 text-xs">
            <div className="flex items-center gap-2 truncate">
              <span className="text-base shrink-0">🎯</span>
              <span className="text-gray-800 dark:text-gray-200 truncate">
                题库错题待清零：当前共有{" "}
                <strong className="text-rose-600 dark:text-rose-400 font-bold">
                  {data.bank_wrong_count}
                </strong>{" "}
                道错题待专项巩固
              </span>
            </div>
            <Button
              variant="secondary"
              className="text-xs !py-1 !px-2.5 border-rose-300 dark:border-rose-800 text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-900/40 shrink-0 font-medium"
              onClick={() => navigate("/banks")}
            >
              前往刷题 ➔
            </Button>
          </div>
        )}

        {/* 4. 活跃认知盲区 */}
        {data.active_misconceptions.length > 0 && (
          <div className="flex items-center justify-between gap-2 bg-indigo-50/40 dark:bg-indigo-950/20 p-2.5 rounded-xl border border-indigo-200/60 dark:border-indigo-900/40 text-xs">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-semibold text-indigo-900 dark:text-indigo-200 flex items-center gap-1">
                <span>🧑‍🎓</span>
                <span>待攻坚认知盲区：</span>
              </span>
              {data.active_misconceptions.map((m) => (
                <span
                  key={m.id}
                  className="rounded-md bg-white dark:bg-gray-800 border border-indigo-200 dark:border-indigo-800 px-2 py-0.5 text-[11px] font-medium text-indigo-800 dark:text-indigo-300"
                >
                  {m.topic}
                </span>
              ))}
            </div>
            <button
              onClick={() => navigate("/settings")}
              className="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline shrink-0 ml-1"
            >
              管理档案
            </button>
          </div>
        )}

        {/* 5. 暂无任务时的鼓励提示 */}
        {!hasAction && (
          <div className="py-2 text-center text-xs text-gray-500 dark:text-gray-400">
            🎉 当前无积压任务与硬骨头，状态极佳！继续学习或探索新课程吧。
          </div>
        )}
      </div>
    </div>
  );
}
