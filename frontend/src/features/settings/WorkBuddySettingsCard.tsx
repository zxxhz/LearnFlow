// WorkBuddy（codebuddy CLI）集成设置卡片：状态探测、命令路径与默认模型、真实小任务验证
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getWorkBuddyStatus, testWorkBuddy, updateWorkBuddyConfig } from "../../lib/api";
import type { WorkBuddyStatus, WorkBuddyTestResult } from "../../lib/types";
import { Button, Input, Select, Spinner } from "../../components/ui";
import { showToast } from "../../lib/toast";

export default function WorkBuddySettingsCard() {
  const qc = useQueryClient();
  const { data: status, isLoading } = useQuery<WorkBuddyStatus>({
    queryKey: ["workbuddy-status"],
    queryFn: getWorkBuddyStatus,
    staleTime: 30_000,
  });

  const [cmd, setCmd] = useState("");
  const [model, setModel] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<WorkBuddyTestResult | null>(null);

  // 首次加载/刷新后同步服务端配置；用户开始编辑后不再覆盖
  useEffect(() => {
    if (status && !dirty) {
      setCmd(status.cmd);
      setModel(status.model);
    }
  }, [status, dirty]);

  const save = async () => {
    setSaving(true);
    try {
      await updateWorkBuddyConfig({ cmd: cmd.trim(), model });
      await qc.invalidateQueries({ queryKey: ["workbuddy-status"] });
      setDirty(false);
      showToast("WorkBuddy 配置已保存（仅本机生效）");
    } catch (e) {
      showToast(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await testWorkBuddy();
      setTestResult(r);
      await qc.invalidateQueries({ queryKey: ["workbuddy-status"] });
    } catch (e) {
      setTestResult({ status: "error", error: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-sm transition-all">
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
        WorkBuddy 集成（外部 Agent 委派）
      </h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        全局助教（Ctrl+J）可把独立任务委派给本机 WorkBuddy CLI（codebuddy）无头执行；
        此配置仅本机生效，不入云端同步。
      </p>

      {/* 状态行：CLI 安装/版本探测（不触发模型调用）；登录态用测试任务权威验证 */}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        {isLoading ? (
          <Spinner className="h-4 w-4" />
        ) : status?.installed ? (
          <span className="inline-flex items-center gap-1.5 font-medium text-green-600 dark:text-green-400">
            <span className="h-2 w-2 rounded-full bg-green-500" />
            已安装{status.version ? ` · CLI ${status.version}` : ""}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 font-medium text-red-600 dark:text-red-400">
            <span className="h-2 w-2 rounded-full bg-red-500" />
            未找到 CLI
          </span>
        )}
        {status && !status.installed && (
          <span className="text-xs text-gray-500 dark:text-gray-400">{status.install_hint}</span>
        )}
        {status?.installed && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            登录状态用「发送测试任务」验证
          </span>
        )}
      </div>

      {/* 命令路径与默认模型 */}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300">
            CLI 命令或绝对路径（默认 codebuddy）
          </label>
          <Input
            value={cmd}
            placeholder="codebuddy"
            onChange={(e) => {
              setCmd(e.target.value);
              setDirty(true);
            }}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300">
            默认模型（助教未显式指定时使用）
          </label>
          <Select
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
              setDirty(true);
            }}
          >
            <option value="">跟随 WorkBuddy 默认</option>
            {(status?.model_presets ?? []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Button variant="secondary" disabled={saving || !dirty} onClick={save}>
          {saving ? "保存中…" : "保存配置"}
        </Button>
        <Button
          disabled={testing || !status?.installed}
          onClick={runTest}
          title={!status?.installed ? "未安装 CLI" : "发送一个真实小任务，验证登录与全链路"}
        >
          {testing ? (
            <>
              <Spinner className="h-4 w-4" /> 测试中（约 5~30 秒）…
            </>
          ) : (
            "发送测试任务"
          )}
        </Button>
      </div>

      {/* 测试结果 */}
      {testResult && (
        <div
          className={`mt-3 rounded-lg border p-3 text-sm ${
            testResult.status === "success"
              ? "border-green-300 bg-green-50 text-green-800 dark:border-green-700 dark:bg-green-900/20 dark:text-green-300"
              : "border-red-300 bg-red-50 text-red-800 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300"
          }`}
        >
          {testResult.status === "success" ? (
            <>
              ✅ 测试任务成功：WorkBuddy 返回「{testResult.result}」
              {testResult.duration_ms != null &&
                `（${(testResult.duration_ms / 1000).toFixed(1)}s）`}
              {testResult.session_id && (
                <span className="ml-1 text-xs opacity-70">
                  会话 {testResult.session_id.slice(0, 8)}…
                </span>
              )}
            </>
          ) : (
            <>
              ❌ {testResult.error || testResult.message || "测试任务失败"}
              {testResult.stderr_tail && (
                <pre className="mt-1 whitespace-pre-wrap break-all text-xs opacity-80">
                  {testResult.stderr_tail}
                </pre>
              )}
              <div className="mt-1 text-xs opacity-80">
                提示：未登录时在终端运行 codebuddy 进入交互界面输入 /login；额度或网络问题看上方报错定位。
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
