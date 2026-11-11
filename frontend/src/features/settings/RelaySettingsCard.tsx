// 自建云端中转服务器 (Cloud Relay) 设置卡片（支持云端/本地 AI 模式选择与双向数据同步）
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRelayConfig,
  getRelayStatus,
  pullRelayData,
  pushRelayData,
  syncBothRelayData,
  testRelayConnection,
  updateRelayConfig,
  getServerLLMConfig,
  updateServerLLMConfig,
  testServerLLMConnection,
} from "../../lib/api";
import type {
  RelayAiMode,
  RelayConfig,
  RelayConnectionState,
  RelayStatus,
  RelaySyncResult,
  ServerLLMConfig,
  ServerLLMTestResult,
} from "../../lib/types";
import { Button, Input, Spinner } from "../../components/ui";
import { showToast } from "../../lib/toast";

const SERVER_PROVIDER_PRESETS = [
  { label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { label: "智谱 GLM", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
  { label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { label: "Moonshot", base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  { label: "Ollama 本地", base_url: "http://localhost:11434/v1", model: "qwen2.5:7b" },
];

export default function RelaySettingsCard() {
  const qc = useQueryClient();

  // 获取初始配置
  const { data: config, isLoading } = useQuery<RelayConfig>({
    queryKey: ["relay-config"],
    queryFn: getRelayConfig,
    staleTime: 10_000,
  });

  // 获取实时连接状态（当启用时定期轮询）
  const { data: statusData } = useQuery<RelayStatus>({
    queryKey: ["relay-status"],
    queryFn: getRelayStatus,
    enabled: config?.enabled ?? false,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.status === "connecting" ? 3_000 : 8_000;
    },
    staleTime: 3_000,
  });

  const [enabled, setEnabled] = useState(false);
  const [serverUrl, setServerUrl] = useState("");
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [autoSync, setAutoSync] = useState(true);
  const [aiMode, setAiMode] = useState<RelayAiMode>("auto");

  // 操作交互状态
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; latency_ms?: number } | null>(null);
  const [syncingAction, setSyncingAction] = useState<"pull" | "push" | "both" | null>(null);
  const [syncFeedback, setSyncFeedback] = useState<{
    type: "success" | "error";
    message: string;
    details?: string;
  } | null>(null);

  const [saveMsg, setSaveMsg] = useState("");
  const [saveErr, setSaveErr] = useState("");
  const [lastSyncAt, setLastSyncAt] = useState<string | null>(null);

  // 云端服务端内置大模型配置状态 (VPS 端 API)
  const [serverLlmBaseUrl, setServerLlmBaseUrl] = useState("");
  const [serverLlmApiKey, setServerLlmApiKey] = useState("");
  const [serverLlmModel, setServerLlmModel] = useState("");
  const [showServerKey, setShowServerKey] = useState(false);
  const [serverLlmMaskedKey, setServerLlmMaskedKey] = useState("");
  const [serverLlmTesting, setServerLlmTesting] = useState(false);
  const [serverLlmTestResult, setServerLlmTestResult] = useState<ServerLLMTestResult | null>(null);
  const [serverLlmSaving, setServerLlmSaving] = useState(false);
  const [serverLlmSaveMsg, setServerLlmSaveMsg] = useState("");
  const [serverLlmOpen, setServerLlmOpen] = useState(false);

  // 查询云端大模型配置
  const { data: serverLlmConfig, refetch: refetchServerLlm } = useQuery<ServerLLMConfig>({
    queryKey: ["server-llm-config"],
    queryFn: getServerLLMConfig,
    enabled: enabled || (typeof window !== "undefined" && !(window as any).__TAURI_INTERNALS__),
    staleTime: 30_000,
  });

  // 检测是否直接在自建云端中转服务端 (Relay Server) 网页上运行
  const isRelayServer = Boolean(
    config?.is_relay_server ||
    statusData?.is_relay_server ||
    config?.service === "LearnFlow-Relay-Server" ||
    statusData?.service === "LearnFlow-Relay-Server"
  );

  const workerOnline = Boolean(
    statusData?.worker_online ??
    config?.worker_online ??
    statusData?.tunnel?.worker_online
  );

  const serverLlmConfigured = Boolean(
    statusData?.server_llm_configured ??
    config?.server_llm_configured ??
    statusData?.ai?.server_llm_configured
  );

  // 在云端服务端环境下，中转功能始终常驻生效，且默认展开云端大模型配置
  useEffect(() => {
    if (isRelayServer) {
      setEnabled(true);
      setServerLlmOpen(true);
    }
  }, [isRelayServer]);

  useEffect(() => {
    if (serverLlmConfig) {
      if (serverLlmConfig.server_llm_base_url) setServerLlmBaseUrl(serverLlmConfig.server_llm_base_url);
      if (serverLlmConfig.server_llm_model) setServerLlmModel(serverLlmConfig.server_llm_model);
      if (serverLlmConfig.server_llm_api_key_masked) setServerLlmMaskedKey(serverLlmConfig.server_llm_api_key_masked);
    }
  }, [serverLlmConfig]);

  const handleTestServerLlm = async () => {
    setServerLlmTesting(true);
    setServerLlmTestResult(null);
    try {
      const res = await testServerLLMConnection({
        server_llm_base_url: serverLlmBaseUrl.trim(),
        server_llm_api_key: serverLlmApiKey.trim() || undefined,
        server_llm_model: serverLlmModel.trim(),
      });
      setServerLlmTestResult(res);
      if (res.ok) {
        showToast(`✅ 云端 API 测试成功 (${res.latency_ms}ms)`);
      } else {
        showToast(`❌ 云端 API 测试失败: ${res.message}`);
      }
    } catch (e: any) {
      setServerLlmTestResult({ ok: false, message: e.message || "测试请求失败" });
      showToast(`❌ 云端 API 测试失败: ${e.message}`);
    } finally {
      setServerLlmTesting(false);
    }
  };

  const handleSaveServerLlm = async () => {
    setServerLlmSaving(true);
    setServerLlmSaveMsg("");
    try {
      await updateServerLLMConfig({
        server_llm_base_url: serverLlmBaseUrl.trim(),
        server_llm_api_key: serverLlmApiKey.trim() || undefined,
        server_llm_model: serverLlmModel.trim(),
      });
      setServerLlmSaveMsg("✅ 云端大模型配置已保存并持久化！");
      showToast("✅ 云端大模型配置已更新");
      refetchServerLlm();
      setTimeout(() => setServerLlmSaveMsg(""), 3000);
    } catch (e: any) {
      showToast(`❌ 保存失败: ${e.message}`);
    } finally {
      setServerLlmSaving(false);
    }
  };

  // 初始化填充
  useEffect(() => {
    if (config) {
      setEnabled(config.enabled ?? false);
      setServerUrl(config.server_url || "");
      setToken(config.token || (config as any).server_token || "");
      setAutoSync(config.auto_sync ?? true);
      if (config.ai_mode) {
        setAiMode(config.ai_mode);
      }
      if (config.last_sync_at) {
        setLastSyncAt(config.last_sync_at);
      }
    }
  }, [config]);

  // 同步状态更新上次同步时间
  useEffect(() => {
    if (statusData?.last_sync_at) {
      setLastSyncAt(statusData.last_sync_at);
    }
    if (statusData?.ai_mode) {
      setAiMode(statusData.ai_mode);
    }
  }, [statusData]);

  // 保存配置 Mutation
  const saveMutation = useMutation({
    mutationFn: (data: Partial<RelayConfig>) => updateRelayConfig(data),
    onSuccess: (saved) => {
      setSaveErr("");
      setSaveMsg(isRelayServer ? "✅ AI 执行模式已更新" : "✅ 中转配置已保存");
      if (saved.last_sync_at) setLastSyncAt(saved.last_sync_at);
      if (saved.ai_mode) setAiMode(saved.ai_mode);
      qc.invalidateQueries({ queryKey: ["relay-config"] });
      qc.invalidateQueries({ queryKey: ["relay-status"] });
      setTimeout(() => setSaveMsg(""), 3000);
      showToast(isRelayServer ? "✅ AI 调度模式已更新并持久化" : "✅ 自建中转服务器与 AI 模式配置已保存");
    },
    onError: (e: Error) => {
      setSaveMsg("");
      setSaveErr(`保存失败：${e.message}`);
    },
  });

  // 切换 AI 执行模式（在云端服务端模式下点击即自动保存持久化）
  const handleSelectAiMode = (mode: RelayAiMode) => {
    if (!enabled && !isRelayServer) return;
    setAiMode(mode);
    if (isRelayServer) {
      saveMutation.mutate({ ai_mode: mode });
    }
  };

  // 测试连接
  const handleTestConnection = async () => {
    const trimmedUrl = serverUrl.trim();
    if (!trimmedUrl) {
      setTestResult({ ok: false, message: "请先输入服务器地址" });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await testRelayConnection(trimmedUrl, token.trim());
      setTestResult(res);
      if (res.ok) {
        showToast(`✅ 测试连接成功${res.latency_ms ? `（延迟 ${res.latency_ms}ms）` : ""}`);
      } else {
        showToast(`❌ 测试连接失败：${res.message}`);
      }
    } catch (err: any) {
      const msg = err.message || "请求服务器失败，请检查网络或地址";
      setTestResult({ ok: false, message: msg });
      showToast(`❌ 测试连接失败：${msg}`);
    } finally {
      setTesting(false);
    }
  };

  // 触发指定方向的数据同步（Pull / Push / Both）
  const handleSync = async (action: "pull" | "push" | "both") => {
    setSyncingAction(action);
    setSyncFeedback(null);
    try {
      let res: RelaySyncResult;
      if (action === "pull") {
        res = await pullRelayData();
      } else if (action === "push") {
        res = await pushRelayData();
      } else {
        res = await syncBothRelayData();
      }

      if (res.ok) {
        const timeStr = res.synced_at || new Date().toLocaleString();
        setLastSyncAt(timeStr);

        let actionDesc = "双向同步";
        if (action === "pull") actionDesc = "从云端拉取数据";
        if (action === "push") actionDesc = "推送到云端";

        let detailMsg = res.message || `${actionDesc}成功`;
        if (res.pulled_count != null || res.pushed_count != null) {
          detailMsg += ` (拉取: ${res.pulled_count ?? 0} 项，推送: ${res.pushed_count ?? 0} 项)`;
        }

        setSyncFeedback({
          type: "success",
          message: `✅ ${actionDesc}完成`,
          details: detailMsg,
        });
        showToast(`✅ ${actionDesc}成功：${res.message || "数据已合并"}`);

        qc.invalidateQueries({ queryKey: ["relay-config"] });
        qc.invalidateQueries({ queryKey: ["relay-status"] });
        // 亦可刷新课程列表与题库查询
        qc.invalidateQueries({ queryKey: ["courses"] });
        qc.invalidateQueries({ queryKey: ["banks"] });
      } else {
        setSyncFeedback({
          type: "error",
          message: "同步失败",
          details: res.message,
        });
        showToast(`❌ 同步失败：${res.message}`);
      }
    } catch (err: any) {
      const msg = err.message || "网络请求异常";
      setSyncFeedback({
        type: "error",
        message: "同步异常",
        details: msg,
      });
      showToast(`❌ 同步发生错误：${msg}`);
    } finally {
      setSyncingAction(null);
    }
  };

  // 计算当前展示的连接状态
  const activeStatus: RelayConnectionState = !enabled
    ? "disconnected"
    : (statusData?.status || config?.status || "connecting");

  const activeLatency = statusData?.latency_ms ?? config?.latency_ms;
  const activeError = statusData?.last_error || config?.last_error;

  // 当前实际生效的 AI 执行模式
  const effectiveAiMode =
    statusData?.effective_ai_mode ||
    (statusData as any)?.actual_ai_mode ||
    config?.effective_ai_mode ||
    (aiMode === "auto" ? (activeStatus === "connected" ? "local" : "cloud") : aiMode);

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-sm transition-all">
      {/* 头部标题与简介 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
              <span className="text-xl">☁️</span> {isRelayServer ? "云端中转服务端 (Cloud Relay Server)" : "自建云端中转服务器 (Cloud Relay)"}
            </h2>
            {/* 顶栏微缩连接徽章 */}
            {isRelayServer ? (
              <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
                服务端运行中
              </span>
            ) : !enabled ? (
              <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
                未启用
              </span>
            ) : activeStatus === "connected" ? (
              <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                已连接
                {activeLatency != null && <span className="opacity-75 font-normal">{activeLatency}ms</span>}
              </span>
            ) : activeStatus === "connecting" ? (
              <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                连接中
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                连接失败
              </span>
            )}
          </div>
          <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400 leading-relaxed max-w-3xl">
            {isRelayServer
              ? "当前正直接访问自建云端中转服务端。支持配置云端原生大模型 API、切换 AI 调度模式并查看家中本地电脑算力节点的接入状态。"
              : "支持将 LearnFlow 挂载到公网自建服务器上，在外网随时随地学习。可自由切换云端 AI 与本地 AI 模式，并支持双向数据合并同步。"}
          </p>
        </div>

        {/* 右侧开关 / 状态标识 */}
        {isRelayServer ? (
          <div className="flex items-center gap-2 shrink-0 self-start sm:self-auto bg-green-50/80 dark:bg-green-950/30 px-3 py-2 rounded-xl border border-green-200/80 dark:border-green-800/60 text-xs font-medium text-green-700 dark:text-green-300">
            <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
            <span>云端 Web 模式</span>
          </div>
        ) : (
          <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto bg-gray-50 dark:bg-gray-800/60 p-2.5 rounded-xl border border-gray-100 dark:border-gray-800">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">启用云端中转</span>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-brand-500 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-brand-600"></div>
            </label>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="py-8 flex items-center justify-center gap-2 text-sm text-gray-400">
          <Spinner className="h-4 w-4" /> 正在加载中转配置…
        </div>
      ) : (
        <div className="mt-5 space-y-5">
          {/* 工作原理提示 */}
          <div className="rounded-lg bg-blue-50/60 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/40 p-3 text-xs text-blue-800 dark:text-blue-300 flex items-start gap-2.5">
            <span className="text-base select-none">💡</span>
            <div className="space-y-0.5">
              <span className="font-medium">{isRelayServer ? "云端独立运行与算力说明：" : "工作原理："}</span>
              <span>
                {isRelayServer
                  ? "您当前直接访问 VPS 服务端。即使家中的电脑关机，网页端亦可由云端独立大模型（如下方配置的 DeepSeek / 智谱等）顺畅生成大纲、精读讲义与划线答疑；当家中的电脑开机且启动客户端时，系统将自动建立反向隧道，支持调用本地沙箱与算力。"
                  : "自建服务器部署在公网或局域网 VPS，可直接调用云端 AI，亦可通过 WebSocket 反向隧道安全穿透调用本地 LLM 与代码沙箱。本地与云端课程、笔记、题库支持双向同步合并，两端数据时刻保持一致。"}
              </span>
            </div>
          </div>

          {/* 表单输入区（客户端模式下输入中转地址与 Token；云端服务端模式下展示节点与数据存储状态） */}
          {isRelayServer ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* 本地客户端反向隧道状态 */}
              <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/70 dark:bg-gray-850/80 p-3.5 flex items-start gap-3">
                <span className="text-xl mt-0.5 select-none">{workerOnline ? "💻" : "⚪"}</span>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">本地电脑节点 (Home Worker)</span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        workerOnline
                          ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                          : "bg-gray-200/80 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                      }`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${workerOnline ? "bg-green-500 animate-pulse" : "bg-gray-400"}`} />
                      {workerOnline ? "已连接" : "未连接"}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    {workerOnline
                      ? "家中电脑已通过 WebSocket 反向隧道连入，可穿透调度本地 Python/C++ 沙箱与本地模型。"
                      : "家中电脑未连接（电脑关机或客户端未开启）。当前所有生成与学习由云端大模型承接，不影响正常使用。"}
                  </p>
                </div>
              </div>

              {/* 云端数据持久化中心 */}
              <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/70 dark:bg-gray-850/80 p-3.5 flex items-start gap-3">
                <span className="text-xl mt-0.5 select-none">🗄️</span>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">云端 SQLite 数据中心</span>
                    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">
                      <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                      正常持久化
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    课程大纲、讲义 Markdown、题库与错题记录已在 VPS 云端安全持久化，手机与电脑随时互通。
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* 服务器地址 */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  服务器地址 <span className="text-red-500">*</span>
                </label>
                <Input
                  type="text"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  placeholder="http://1.2.3.4:8421 或 https://hub.example.com"
                  disabled={!enabled}
                  className={!enabled ? "opacity-60 bg-gray-50 dark:bg-gray-800" : ""}
                />
                <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                  你的公网自建服务端访问地址，需带协议头（http:// 或 https://），默认端口为 8421。
                </p>
              </div>

              {/* 中转鉴权 Token */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  中转鉴权 Token
                </label>
                <div className="relative">
                  <Input
                    type={showToken ? "text" : "password"}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="留空则表示自建服务器免鉴权"
                    disabled={!enabled}
                    className={`pr-10 ${!enabled ? "opacity-60 bg-gray-50 dark:bg-gray-800" : ""}`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken(!showToken)}
                    disabled={!enabled}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition p-1"
                    title={showToken ? "隐藏 Token" : "显示 Token"}
                    aria-label={showToken ? "隐藏 Token" : "显示 Token"}
                  >
                    {showToken ? (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18"
                        />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                        />
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                        />
                      </svg>
                    )}
                  </button>
                </div>
                <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                  若自建服务器未强制开启 Token 鉴权（RELAY_AUTH_REQUIRED=false），可留空；密码输入框支持明暗切换。
                </p>
              </div>
            </div>
          )}

          {/* AI 执行模式选择器 */}
          <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/70 dark:bg-gray-850/80 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <label className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                  <span>🤖</span> AI 执行模式 (AI Execution Mode)
                </label>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  决定在生成大纲、阅读答疑、助教诊断与拍照解题时，优先由何处的 AI 模型处理。
                </p>
              </div>
              {/* 当前生效提示 */}
              {enabled && (
                <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-800">
                  <span>当前生效：</span>
                  <span className="font-semibold">
                    {effectiveAiMode === "cloud" ? "☁️ 云端服务端 AI" : "💻 本地节点 AI"}
                  </span>
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
              {/* 1. 云端服务端模式 */}
              <div
                onClick={() => handleSelectAiMode("cloud")}
                className={`relative flex flex-col justify-between rounded-xl border p-3.5 transition cursor-pointer select-none ${
                  !enabled && !isRelayServer
                    ? "opacity-60 cursor-not-allowed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                    : aiMode === "cloud"
                    ? "border-brand-500 dark:border-brand-500 bg-brand-50/40 dark:bg-brand-950/30 ring-2 ring-brand-500/20"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-medium text-sm text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                      <span>☁️</span> 云端模式 (Cloud AI)
                    </span>
                    <input
                      type="radio"
                      name="ai_mode"
                      value="cloud"
                      checked={aiMode === "cloud"}
                      onChange={() => handleSelectAiMode("cloud")}
                      disabled={!enabled && !isRelayServer}
                      className="text-brand-600 focus:ring-brand-500"
                    />
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    所有 AI 请求直接调用服务端的模型。适合外出或本地电脑关机场景，手机/平板在外随时学习。
                  </p>
                </div>
                <div className="mt-3 pt-2 border-t border-gray-100 dark:border-gray-800 text-[11px] text-gray-400 dark:text-gray-500 flex items-center justify-between">
                  <span>⚡ 免开本地电脑 · 云端算力</span>
                  {isRelayServer && <span className="text-[11px] text-blue-600 dark:text-blue-400 font-medium">独立可用</span>}
                </div>
              </div>

              {/* 2. 本地节点模式 */}
              <div
                onClick={() => handleSelectAiMode("local")}
                className={`relative flex flex-col justify-between rounded-xl border p-3.5 transition cursor-pointer select-none ${
                  !enabled && !isRelayServer
                    ? "opacity-60 cursor-not-allowed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                    : aiMode === "local"
                    ? "border-brand-500 dark:border-brand-500 bg-brand-50/40 dark:bg-brand-950/30 ring-2 ring-brand-500/20"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-medium text-sm text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                      <span>💻</span> 本地节点 (Local AI)
                    </span>
                    <input
                      type="radio"
                      name="ai_mode"
                      value="local"
                      checked={aiMode === "local"}
                      onChange={() => handleSelectAiMode("local")}
                      disabled={!enabled && !isRelayServer}
                      className="text-brand-600 focus:ring-brand-500"
                    />
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    通过反向隧道穿透回本地客户端，调用本地显卡 Ollama 或本地 API Key 与代码沙箱，隐私绝对安全。
                  </p>
                </div>
                <div className="mt-3 pt-2 border-t border-gray-100 dark:border-gray-800 text-[11px] text-gray-400 dark:text-gray-500 flex items-center justify-between">
                  <span>🔒 本地显卡算力 · 隐私无泄漏</span>
                  {isRelayServer && (
                    workerOnline ? (
                      <span className="text-[11px] text-green-600 dark:text-green-400 font-medium">✅ 本地电脑在线</span>
                    ) : (
                      <span className="text-[11px] text-amber-600 dark:text-amber-400 font-medium">⚠️ 本地电脑离线</span>
                    )
                  )}
                </div>
              </div>

              {/* 3. 智能自动模式 */}
              <div
                onClick={() => handleSelectAiMode("auto")}
                className={`relative flex flex-col justify-between rounded-xl border p-3.5 transition cursor-pointer select-none ${
                  !enabled && !isRelayServer
                    ? "opacity-60 cursor-not-allowed border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
                    : aiMode === "auto"
                    ? "border-brand-500 dark:border-brand-500 bg-brand-50/40 dark:bg-brand-950/30 ring-2 ring-brand-500/20"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-medium text-sm text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                      <span>🔄</span> 智能自动 (Auto Fallback)
                    </span>
                    <input
                      type="radio"
                      name="ai_mode"
                      value="auto"
                      checked={aiMode === "auto"}
                      onChange={() => handleSelectAiMode("auto")}
                      disabled={!enabled && !isRelayServer}
                      className="text-brand-600 focus:ring-brand-500"
                    />
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    推荐模式。本地电脑在线优先走本地节点；若本地断开或关机，自动无缝切换到云端服务端处理。
                  </p>
                </div>
                <div className="mt-3 pt-2 border-t border-gray-100 dark:border-gray-800 text-[11px] text-gray-400 dark:text-gray-500 flex items-center justify-between">
                  <span>⭐ 优先本地 · 离线自动平滑降级</span>
                  {isRelayServer && (
                    <span className="text-[11px] text-brand-600 dark:text-brand-400 font-medium">
                      {workerOnline ? "当前调度本地" : "当前调度云端"}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* 云端服务端内置大模型 API 配置 (VPS 端 API) */}
          <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/70 dark:bg-gray-850/80 p-4 space-y-3">
            <button
              type="button"
              className="flex w-full items-center justify-between text-left"
              onClick={() => setServerLlmOpen(!serverLlmOpen)}
            >
              <div className="flex items-center gap-2">
                <span className="text-base">⚡</span>
                <div>
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    云端服务端大模型 API 配置 (VPS 端)
                  </span>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                    在云端模式或本地离线自动回退时由 VPS 直连该大模型；支持在线修改并永久保存。
                  </p>
                </div>
              </div>
              <span className="text-xs text-brand-600 dark:text-brand-400 font-medium">
                {serverLlmOpen ? "收起 ▾" : "修改 API ▸"}
              </span>
            </button>

            {serverLlmOpen && (
              <div className="mt-3 space-y-3 pt-3 border-t border-gray-200/60 dark:border-gray-800">
                {/* 快捷预设 */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-gray-500 dark:text-gray-400">快捷预设:</span>
                  {SERVER_PROVIDER_PRESETS.map((p) => (
                    <button
                      key={p.label}
                      type="button"
                      onClick={() => {
                        setServerLlmBaseUrl(p.base_url);
                        setServerLlmModel(p.model);
                      }}
                      className="rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 hover:border-brand-500 hover:text-brand-600 transition"
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Base URL
                    </label>
                    <Input
                      type="text"
                      value={serverLlmBaseUrl}
                      onChange={(e) => setServerLlmBaseUrl(e.target.value)}
                      placeholder="https://api.deepseek.com/v1"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                      API Key
                    </label>
                    <div className="relative">
                      <Input
                        type={showServerKey ? "text" : "password"}
                        value={serverLlmApiKey}
                        onChange={(e) => setServerLlmApiKey(e.target.value)}
                        placeholder={
                          serverLlmMaskedKey ? `已配置: ${serverLlmMaskedKey}` : "sk-..."
                        }
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowServerKey(!showServerKey)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition text-xs"
                      >
                        {showServerKey ? "隐藏" : "显示"}
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Model 名称
                    </label>
                    <Input
                      type="text"
                      value={serverLlmModel}
                      onChange={(e) => setServerLlmModel(e.target.value)}
                      placeholder="deepseek-chat 或 gpt-4o-mini"
                    />
                  </div>
                </div>

                {/* 连通性测试结果面板 */}
                {serverLlmTestResult && (
                  <div
                    className={`rounded-lg p-2.5 text-xs border flex items-start gap-2 ${
                      serverLlmTestResult.ok
                        ? "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900/50 text-green-700 dark:text-green-300"
                        : "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300"
                    }`}
                  >
                    <span>{serverLlmTestResult.ok ? "✅" : "❌"}</span>
                    <div>
                      <div className="font-medium">{serverLlmTestResult.message}</div>
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between pt-1">
                  <Button
                    variant="secondary"
                    disabled={serverLlmTesting || !serverLlmBaseUrl.trim() || !serverLlmModel.trim()}
                    onClick={handleTestServerLlm}
                    className="text-xs px-3 py-1.5"
                  >
                    {serverLlmTesting ? (
                      <>
                        <Spinner className="h-3 w-3" /> 测试连接中…
                      </>
                    ) : (
                      "⚡ 测试云端 API"
                    )}
                  </Button>

                  <div className="flex items-center gap-2">
                    {serverLlmSaveMsg && (
                      <span className="text-xs text-green-600 dark:text-green-400">{serverLlmSaveMsg}</span>
                    )}
                    <Button
                      disabled={serverLlmSaving}
                      onClick={handleSaveServerLlm}
                      className="text-xs px-3.5 py-1.5"
                    >
                      {serverLlmSaving ? (
                        <>
                          <Spinner className="h-3 w-3" /> 保存中…
                        </>
                      ) : (
                        "保存云端 API 配置"
                      )}
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 自动同步选项（仅客户端模式展示） */}
          {!isRelayServer && (
            <div className="flex items-center justify-between rounded-lg border border-gray-100 dark:border-gray-800 p-3 bg-gray-50/60 dark:bg-gray-850">
              <div>
                <span className="text-sm font-medium text-gray-800 dark:text-gray-200">自动同步数据</span>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                  本地数据更新时（创建/编辑课程、添加笔记、错题刷题记录），自动向云端服务器增量同步。
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer shrink-0">
                <input
                  type="checkbox"
                  checked={autoSync}
                  onChange={(e) => setAutoSync(e.target.checked)}
                  disabled={!enabled}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-600 peer-checked:bg-brand-600 peer-disabled:opacity-50"></div>
              </label>
            </div>
          )}

          {/* 状态展示与多向数据同步区（仅客户端模式下需要向云端 push/pull） */}
          {!isRelayServer && (
            <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/70 dark:bg-gray-850/80 p-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    连接状态
                  </span>
                  {!enabled ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-gray-200/80 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                      <span className="h-2 w-2 rounded-full bg-gray-400" />
                      未启用
                    </span>
                  ) : activeStatus === "connected" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">
                      <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                      已连接
                      {activeLatency != null && (
                        <span className="font-mono text-[11px] opacity-80">({activeLatency} ms)</span>
                      )}
                    </span>
                  ) : activeStatus === "connecting" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                      <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                      连接中 / 重试中
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
                      <span className="h-2 w-2 rounded-full bg-red-500" />
                      连接失败
                    </span>
                  )}
                </div>

                {/* 上次同步时间 */}
                <div className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
                  <span>🕒 上次同步时间：</span>
                  <span className="font-mono text-gray-700 dark:text-gray-300 font-medium">
                    {lastSyncAt ? lastSyncAt : "尚未同步"}
                  </span>
                </div>
              </div>

              {/* 错误提示详情 */}
              {enabled && activeStatus === "error" && activeError && (
                <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/60 p-2.5 text-xs text-red-700 dark:text-red-300 flex items-start gap-2">
                  <span className="shrink-0 mt-0.5">⚠️</span>
                  <div>
                    <span className="font-medium">错误详情：</span>
                    <span>{activeError}</span>
                  </div>
                </div>
              )}

              {/* 连通性测试结果面板 */}
              {testResult && (
                <div
                  className={`rounded-lg p-2.5 text-xs border flex items-start gap-2 ${
                    testResult.ok
                      ? "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900/50 text-green-700 dark:text-green-300"
                      : "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300"
                  }`}
                >
                  <span className="shrink-0 mt-0.5">{testResult.ok ? "✅" : "❌"}</span>
                  <div>
                    <div className="font-medium">
                      {testResult.ok ? "测试连接成功" : "测试连接失败"}
                      {testResult.latency_ms != null && (
                        <span className="ml-1.5 font-mono text-[11px] opacity-80 font-normal">
                          (延迟: {testResult.latency_ms} ms)
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-[11px] opacity-90">{testResult.message}</div>
                  </div>
                </div>
              )}

              {/* 数据同步操作反馈面板 */}
              {syncFeedback && (
                <div
                  className={`rounded-lg p-2.5 text-xs border flex items-start gap-2 ${
                    syncFeedback.type === "success"
                      ? "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900/50 text-green-700 dark:text-green-300"
                      : "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300"
                  }`}
                >
                  <span className="shrink-0 mt-0.5">{syncFeedback.type === "success" ? "✅" : "❌"}</span>
                  <div>
                    <div className="font-medium">{syncFeedback.message}</div>
                    {syncFeedback.details && (
                      <div className="mt-0.5 text-[11px] opacity-90">{syncFeedback.details}</div>
                    )}
                  </div>
                </div>
              )}

              {/* 双向同步操作按钮区 */}
              <div className="pt-2 border-t border-gray-200/60 dark:border-gray-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-600 dark:text-gray-400">
                    数据同步控制 (Data Synchronization)
                  </span>
                  <span className="text-[11px] text-gray-400 dark:text-gray-500">
                    支持按需拉取云端、推送本地或双向完整同步
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  {/* 1. Pull */}
                  <button
                    type="button"
                    disabled={syncingAction !== null || !enabled || activeStatus !== "connected"}
                    onClick={() => handleSync("pull")}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-750 disabled:opacity-50 transition"
                    title="从自建云端服务器拉取最新的课程、笔记和题库，安全合并到本地"
                  >
                    {syncingAction === "pull" ? (
                      <>
                        <Spinner className="h-3.5 w-3.5" /> 正在拉取…
                      </>
                    ) : (
                      <>
                        <span>⬇️</span> 从云端拉取更新 (Pull)
                      </>
                    )}
                  </button>

                  {/* 2. Push */}
                  <button
                    type="button"
                    disabled={syncingAction !== null || !enabled || activeStatus !== "connected"}
                    onClick={() => handleSync("push")}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-750 disabled:opacity-50 transition"
                    title="将本地最新的所有数据（课程大纲、学习进度、错题本）推送到云端自建服务器保存"
                  >
                    {syncingAction === "push" ? (
                      <>
                        <Spinner className="h-3.5 w-3.5" /> 正在推送…
                      </>
                    ) : (
                      <>
                        <span>⬆️</span> 推送本地到云端 (Push)
                      </>
                    )}
                  </button>

                  {/* 3. Both */}
                  <button
                    type="button"
                    disabled={syncingAction !== null || !enabled || activeStatus !== "connected"}
                    onClick={() => handleSync("both")}
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-brand-300 dark:border-brand-700 bg-brand-50/60 dark:bg-brand-950/40 px-3 py-2 text-xs font-medium text-brand-700 dark:text-brand-300 hover:bg-brand-100 dark:hover:bg-brand-900/60 disabled:opacity-50 transition"
                    title="先拉取云端更新进行本地合并，再将本地变更推回云端，保证两端完整一致"
                  >
                    {syncingAction === "both" ? (
                      <>
                        <Spinner className="h-3.5 w-3.5" /> 双向同步中…
                      </>
                    ) : (
                      <>
                        <span>🔄</span> 双向完整同步 (Both)
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* 底部操作与配置保存 */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <div>
              {/* 仅在客户端模式下展示测试中转连接按钮 */}
              {!isRelayServer && (
                <Button
                  variant="secondary"
                  disabled={testing || !serverUrl.trim()}
                  onClick={handleTestConnection}
                  className="text-xs"
                  title="实时向中转服务器发送探测请求以测试网络连通性与往返延迟"
                >
                  {testing ? (
                    <>
                      <Spinner className="h-3 w-3" /> 测试中…
                    </>
                  ) : (
                    "⚡ 测试连接"
                  )}
                </Button>
              )}
            </div>

            {/* 保存配置按钮及反馈 */}
            <div className="flex items-center gap-3">
              {saveMsg && <span className="text-xs text-green-600 dark:text-green-400">{saveMsg}</span>}
              {saveErr && <span className="text-xs text-red-600 dark:text-red-400">{saveErr}</span>}
              <Button
                disabled={saveMutation.isPending}
                onClick={() =>
                  saveMutation.mutate(
                    isRelayServer
                      ? { ai_mode: aiMode }
                      : {
                          enabled,
                          server_url: serverUrl.trim(),
                          token: token.trim(),
                          auto_sync: autoSync,
                          ai_mode: aiMode,
                        }
                  )
                }
              >
                {saveMutation.isPending ? (
                  <>
                    <Spinner className="h-3 w-3" /> 保存中…
                  </>
                ) : (
                  isRelayServer ? "保存 AI 模式" : "保存配置"
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
