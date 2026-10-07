// 下载源测速与智能路由配置卡片：为应用更新与环境下载测速择优
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, Button, Spinner } from "../../components/ui";
import type { DownloadMirrorItem } from "../../lib/types";

export default function DownloadMirrorsSection() {
  const queryClient = useQueryClient();
  const [testingMsg, setTestingMsg] = useState("");

  const { data: status, isLoading } = useQuery({
    queryKey: ["settings-mirrors"],
    queryFn: api.settings.mirrors.getStatus,
  });

  const testMutation = useMutation({
    mutationFn: api.settings.mirrors.speedTest,
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
      setTestingMsg(`测速完成！最优源为「${data.active_mirror.name}」`);
      setTimeout(() => setTestingMsg(""), 3500);
    },
    onError: (err) => {
      setTestingMsg(`测速失败: ${(err as Error).message}`);
      setTimeout(() => setTestingMsg(""), 3500);
    },
  });

  const selectMutation = useMutation({
    mutationFn: (args: { mode: "auto" | "manual"; selected_id: string }) =>
      api.settings.mirrors.select(args),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
    },
  });

  const handleModeChange = (mode: "auto" | "manual") => {
    selectMutation.mutate({
      mode,
      selected_id: mode === "manual" ? status?.selected_id || status?.fastest_id || "official" : "auto",
    });
  };

  const handleSelectMirror = (item: DownloadMirrorItem) => {
    selectMutation.mutate({
      mode: "manual",
      selected_id: item.id,
    });
  };

  if (isLoading) {
    return (
      <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Spinner className="h-4 w-4" /> 正在加载下载源配置…
        </div>
      </section>
    );
  }

  const isAuto = status?.mode === "auto" || status?.selected_id === "auto";
  const activeId = status?.active_mirror?.id;

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              下载源测速与智能路由
            </h2>
            <Badge color="blue" className="text-[11px]">
              {isAuto ? "自动择优中" : "手动锁定"}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            用于应用更新安装包、MinGW 编译器及 Python 便携运行时的极速下载。支持并发测速并自动切换至最优源。
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            variant="secondary"
            disabled={testMutation.isPending}
            onClick={() => testMutation.mutate()}
            className="text-xs"
          >
            {testMutation.isPending ? (
              <>
                <Spinner className="h-3.5 w-3.5" /> 测速中…
              </>
            ) : (
              "⚡ 立即测速"
            )}
          </Button>
        </div>
      </div>

      {testingMsg && (
        <div className="mt-3 rounded-lg bg-brand-50 dark:bg-brand-950/40 border border-brand-200 dark:border-brand-800/50 px-3 py-1.5 text-xs text-brand-700 dark:text-brand-300">
          {testingMsg}
        </div>
      )}

      {/* 模式选择 */}
      <div className="mt-4 flex items-center gap-4 text-xs text-gray-700 dark:text-gray-300">
        <span className="font-medium text-gray-500 dark:text-gray-400">选择策略：</span>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="mirror-mode"
            checked={isAuto}
            onChange={() => handleModeChange("auto")}
            className="text-brand-600 focus:ring-brand-500"
          />
          <span>🤖 自动选用最快源（推荐）</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="mirror-mode"
            checked={!isAuto}
            onChange={() => handleModeChange("manual")}
            className="text-brand-600 focus:ring-brand-500"
          />
          <span>✋ 手动指定源</span>
        </label>
      </div>

      {/* 镜像列表卡片 */}
      <div className="mt-3.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {status?.results?.map((item) => {
          const isActive = item.id === activeId;
          const isFastest = item.id === status?.fastest_id && item.ok;

          return (
            <div
              key={item.id}
              onClick={() => {
                if (!isAuto) handleSelectMirror(item);
              }}
              className={`relative flex flex-col justify-between rounded-lg border p-3 transition-all ${
                isActive
                  ? "border-brand-500 bg-brand-50/40 dark:bg-brand-950/20 shadow-xs"
                  : "border-gray-200 dark:border-gray-700/80 bg-gray-50/60 dark:bg-gray-800/40 hover:border-gray-300 dark:hover:border-gray-600"
              } ${!isAuto ? "cursor-pointer" : ""}`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                    {item.name}
                    {isActive && (
                      <span className="h-2 w-2 rounded-full bg-brand-600 dark:bg-brand-400 animate-pulse" />
                    )}
                  </span>
                  <div className="flex items-center gap-1">
                    {isFastest && (
                      <span className="rounded bg-amber-100 dark:bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300">
                        ⚡ 最快
                      </span>
                    )}
                    {isActive && (
                      <span className="rounded bg-brand-100 dark:bg-brand-900/50 px-1.5 py-0.5 text-[10px] font-medium text-brand-700 dark:text-brand-300">
                        使用中
                      </span>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400 line-clamp-1">
                  {item.desc}
                </p>
              </div>

              <div className="mt-3 flex items-center justify-between text-[11px] border-t border-gray-100 dark:border-gray-700/50 pt-2">
                <span className="text-gray-400 dark:text-gray-500">
                  {item.latency_ms !== null ? (
                    item.ok ? (
                      <span
                        className={
                          item.latency_ms < 600
                            ? "text-green-600 dark:text-green-400 font-medium"
                            : item.latency_ms < 1500
                            ? "text-amber-600 dark:text-amber-400 font-medium"
                            : "text-red-500 dark:text-red-400"
                        }
                      >
                        ● {item.latency_ms} ms
                      </span>
                    ) : (
                      <span className="text-red-500 dark:text-red-400" title={item.error || ""}>
                        ✕ {item.error || "不可达"}
                      </span>
                    )
                  ) : (
                    "未测速"
                  )}
                </span>

                {!isAuto && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSelectMirror(item);
                    }}
                    className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                      isActive
                        ? "bg-brand-600 text-white"
                        : "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-300 dark:hover:bg-gray-600"
                    }`}
                  >
                    {isActive ? "已选用" : "设为当前"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
