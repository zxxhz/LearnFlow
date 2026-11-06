// 轻量云端中转状态指示器组件 (RelayStatusBadge)
// 动态展示自建服务器连接状态及当前 AI 执行模式（云端 AI vs 本地 AI）
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getRelayConfig, getRelayStatus } from "../lib/api";
import type { RelayConfig, RelayStatus } from "../lib/types";

interface RelayStatusBadgeProps {
  className?: string;
  showWhenDisabled?: boolean;
}

export default function RelayStatusBadge({
  className = "",
  showWhenDisabled = false,
}: RelayStatusBadgeProps) {
  const navigate = useNavigate();

  // 获取配置
  const { data: config } = useQuery<RelayConfig>({
    queryKey: ["relay-config"],
    queryFn: getRelayConfig,
    staleTime: 15_000,
    retry: 1,
  });

  // 获取实时状态（当配置开启时定期轮询）
  const { data: status } = useQuery<RelayStatus>({
    queryKey: ["relay-status"],
    queryFn: getRelayStatus,
    enabled: config?.enabled ?? false,
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return state === "connecting" ? 3_000 : 10_000;
    },
    staleTime: 5_000,
    retry: 1,
  });

  const isEnabled = config?.enabled ?? false;

  // 未启用且未指定强制显示时静默隐藏
  if (!isEnabled && !showWhenDisabled) {
    return null;
  }

  const connState = !isEnabled ? "disabled" : (status?.status || config?.status || "connecting");
  const latency = status?.latency_ms ?? config?.latency_ms;
  const serverUrl = status?.server_url || config?.server_url || "";
  const errorMessage = status?.last_error || config?.last_error;

  // 计算当前实际生效的 AI 模式（云端 AI vs 本地 AI）
  const configuredAiMode = status?.ai_mode || config?.ai_mode || "auto";
  const effectiveAiMode =
    status?.effective_ai_mode ||
    (status as any)?.actual_ai_mode ||
    config?.effective_ai_mode ||
    (configuredAiMode === "auto"
      ? (connState === "connected" ? "local" : "cloud")
      : configuredAiMode);

  const isCloudAi = effectiveAiMode === "cloud";

  const handleClick = () => {
    navigate("/settings");
  };

  if (!isEnabled) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/80 px-2.5 py-0.5 text-xs text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-750 transition ${className}`}
        title="云端中转未启用，点击前往设置开启"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
        <span className="hidden sm:inline">中转未启用</span>
      </button>
    );
  }

  if (connState === "connected") {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`inline-flex items-center gap-1.5 rounded-full border border-green-200 dark:border-green-800/60 bg-green-50/90 dark:bg-green-950/40 px-2.5 py-0.5 text-xs font-medium text-green-700 dark:text-green-300 hover:bg-green-100 dark:hover:bg-green-900/50 transition cursor-pointer shadow-xs ${className}`}
        title={`已连接云端中转${serverUrl ? ` (${serverUrl})` : ""}${latency != null ? `，延迟 ${latency}ms` : ""}。当前 AI 执行模式：${isCloudAi ? "云端服务端 AI (Cloud)" : "本地节点 AI (Local)"}。点击管理设置`}
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
        </span>
        <span className="flex items-center gap-1">
          <span>{isCloudAi ? "☁️ 云端 AI" : "💻 本地 AI"}</span>
          <span className="text-[11px] opacity-75">就绪</span>
        </span>
        {latency != null && (
          <span className="hidden md:inline font-mono text-[10px] text-green-600 dark:text-green-400 font-normal">
            {latency}ms
          </span>
        )}
      </button>
    );
  }

  if (connState === "connecting") {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`inline-flex items-center gap-1.5 rounded-full border border-amber-200 dark:border-amber-800/60 bg-amber-50/90 dark:bg-amber-950/40 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/50 transition cursor-pointer ${className}`}
        title={`正在连接云端自建中转${serverUrl ? ` (${serverUrl})` : ""}，目标 AI 模式: ${isCloudAi ? "云端 AI" : "本地 AI"}，点击查看详情`}
      >
        <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
        <span className="flex items-center gap-1">
          <span>{isCloudAi ? "☁️" : "💻"}</span>
          <span>连接中…</span>
        </span>
      </button>
    );
  }

  // 错误或断开连接
  return (
    <button
      type="button"
      onClick={handleClick}
      className={`inline-flex items-center gap-1.5 rounded-full border border-red-200 dark:border-red-800/60 bg-red-50/90 dark:bg-red-950/40 px-2.5 py-0.5 text-xs font-medium text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/50 transition cursor-pointer ${className}`}
      title={`云端中转连接失败${errorMessage ? `: ${errorMessage}` : ""}。点击前往设置排查`}
    >
      <span className="h-2 w-2 rounded-full bg-red-500" />
      <span>中转断开 ({isCloudAi ? "云端 AI" : "本地 AI"})</span>
    </button>
  );
}
