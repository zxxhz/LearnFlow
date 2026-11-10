// 云端服务端在线更新与版本管理卡片
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getServerSystemVersion, triggerServerUpdate } from "../../lib/api";
import type { ServerSystemVersion, ServerUpdateTriggerResult } from "../../lib/types";
import { Button, Spinner } from "../../components/ui";
import { showToast } from "../../lib/toast";

export default function ServerUpdateCard() {
  const qc = useQueryClient();
  const [updating, setUpdating] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [updateMsg, setUpdateMsg] = useState<string | null>(null);

  const {
    data: versionInfo,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery<ServerSystemVersion>({
    queryKey: ["server-system-version"],
    queryFn: getServerSystemVersion,
    staleTime: 60_000,
    retry: 1,
  });

  const updateMutation = useMutation({
    mutationFn: triggerServerUpdate,
    onSuccess: (data: ServerUpdateTriggerResult) => {
      setUpdateMsg(data.message);
      if (data.status === "triggered") {
        setUpdating(true);
        const waitSec = data.estimated_seconds || 15;
        setCountdown(waitSec);
      } else {
        showToast(data.message);
      }
    },
    onError: (err: any) => {
      showToast(`更新触发失败: ${err.message}`);
    },
  });

  // 倒计时刷新逻辑
  useEffect(() => {
    if (countdown === null) return;
    if (countdown <= 0) {
      window.location.reload();
      return;
    }
    const timer = setTimeout(() => {
      setCountdown((prev) => (prev !== null ? prev - 1 : 0));
    }, 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  // 如果请求失败（例如纯本地单机且非云端中转环境），可安全降级不阻碍主界面
  if (isError) {
    return null;
  }

  const hasUpdate = versionInfo?.has_update ?? false;

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">🚀</span>
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
              云端服务端在线更新
              {versionInfo?.in_container && (
                <span className="inline-flex items-center rounded-full bg-blue-50 dark:bg-blue-950/60 px-2 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                  Docker 容器
                </span>
              )}
            </h2>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              支持在网页端直接检查 GitHub 最新 Release，并一键在线拉取更新前后端镜像。
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            disabled={isFetching || updating}
            onClick={() => refetch()}
            className="text-xs px-3 py-1.5"
          >
            {isFetching ? (
              <>
                <Spinner /> 检查中…
              </>
            ) : (
              "检查新版本"
            )}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-gray-500">
          <Spinner /> 正在获取服务端版本信息…
        </div>
      ) : versionInfo ? (
        <div className="mt-4 space-y-3">
          {/* 版本状态栏 */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 p-3">
            <div>
              <div className="text-xs text-gray-400 dark:text-gray-500">当前运行版本</div>
              <div className="text-sm font-semibold text-gray-800 dark:text-gray-200 mt-0.5">
                v{versionInfo.current_version}
              </div>
            </div>

            <div>
              <div className="text-xs text-gray-400 dark:text-gray-500">云端最新发布</div>
              <div className="text-sm font-semibold text-gray-800 dark:text-gray-200 mt-0.5 flex items-center gap-2">
                {versionInfo.latest_version ? `v${versionInfo.latest_version.replace(/^v/, "")}` : "最新"}
                {hasUpdate ? (
                  <span className="inline-flex items-center rounded-md bg-amber-50 dark:bg-amber-950/60 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                    可升级
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-md bg-green-50 dark:bg-green-950/60 px-1.5 py-0.5 text-xs font-medium text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800">
                    已是最新
                  </span>
                )}
              </div>
            </div>

            <div>
              <div className="text-xs text-gray-400 dark:text-gray-500">更新执行驱动</div>
              <div className="text-sm text-gray-600 dark:text-gray-300 mt-0.5 flex items-center gap-1.5">
                {versionInfo.update_driver === "docker_socket" && "🐳 Docker Socket 直连"}
                {versionInfo.update_driver === "command" && "⚙️ 自定义指令"}
                {versionInfo.update_driver === "manual" && "📋 手动更新"}
              </div>
            </div>
          </div>

          {/* 发现新版本时的升级提示 */}
          {hasUpdate && (
            <div className="rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/60 dark:bg-amber-950/20 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h4 className="text-sm font-semibold text-amber-900 dark:text-amber-200 flex items-center gap-2">
                    <span>🎉 发现新版本</span>
                    <span>{versionInfo.release_title || `v${versionInfo.latest_version}`}</span>
                  </h4>
                  {versionInfo.published_at && (
                    <div className="text-xs text-amber-700/80 dark:text-amber-300/80 mt-0.5">
                      发布时间：{new Date(versionInfo.published_at).toLocaleString("zh-CN")}
                    </div>
                  )}
                  {versionInfo.release_notes && (
                    <p className="mt-2 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-line line-clamp-3 bg-white/60 dark:bg-gray-900/40 p-2 rounded border border-amber-100 dark:border-amber-900/30">
                      {versionInfo.release_notes}
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button
                  disabled={updating || updateMutation.isPending}
                  onClick={() => {
                    if (window.confirm("确定要立即在线更新服务端镜像吗？更新过程中服务将重启约 10~15 秒。")) {
                      updateMutation.mutate();
                    }
                  }}
                  className="bg-brand-600 hover:bg-brand-700 text-white font-medium text-xs px-4 py-2"
                >
                  {updateMutation.isPending ? (
                    <>
                      <Spinner /> 正在触发更新…
                    </>
                  ) : (
                    "🚀 立即在线更新服务端"
                  )}
                </Button>

                {versionInfo.html_url && (
                  <a
                    href={versionInfo.html_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-brand-600 dark:text-brand-400 hover:underline inline-flex items-center gap-1"
                  >
                    查看 Release 详情 ↗
                  </a>
                )}
              </div>
            </div>
          )}

          {/* 更新进行中倒计时界面 */}
          {updating && countdown !== null && (
            <div className="rounded-lg border border-blue-200 dark:border-blue-900/60 bg-blue-50 dark:bg-blue-950/30 p-4 text-center">
              <div className="flex items-center justify-center gap-2 text-blue-700 dark:text-blue-300 font-medium text-sm">
                <Spinner />
                <span>服务端正在拉取最新镜像并重启，请稍候…</span>
              </div>
              <div className="mt-2 text-2xl font-bold text-blue-600 dark:text-blue-400">
                {countdown} 秒后自动刷新网页
              </div>
              {updateMsg && (
                <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">{updateMsg}</div>
              )}
            </div>
          )}

          {/* 如果已是最新版本 */}
          {!hasUpdate && !updating && (
            <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 px-1">
              <span>当前服务端已处于最新版本状态，无需更新。</span>
              {versionInfo.html_url && (
                <a
                  href={versionInfo.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-600 dark:text-brand-400 hover:underline"
                >
                  查看历史版本记录 ↗
                </a>
              )}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
