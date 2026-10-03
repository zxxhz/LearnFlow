// 运行环境区块：代码沙箱 Python / C++ 工具链检测 + 一键便携安装（装进软件目录，不动系统）
// 安装跑后端守护线程，这里 1s 轮询进度；active 从非空变空（装完/失败）时刷新状态
import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { InstallState, RuntimeComponentName } from "../../lib/types";
import { Button, Spinner } from "../../components/ui";

// 来源徽章：已安装时补充说明装在哪（系统装 / 应用内装 / 打包内置）
const SOURCE_META: Record<"bundled" | "managed" | "system", { label: string; cls: string }> = {
  bundled: { label: "随包内置", cls: "border-emerald-300 bg-emerald-50 text-emerald-700" },
  managed: { label: "应用内", cls: "border-brand-300 dark:border-brand-700 bg-brand-50 dark:bg-brand-900/40 text-brand-700" },
  system: { label: "系统", cls: "border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 text-gray-600 dark:text-gray-400 dark:text-gray-400 dark:text-gray-400" },
};

const ROWS: { key: RuntimeComponentName; title: string; desc: string; installLabel: string }[] = [
  {
    key: "python",
    title: "Python",
    desc: "运行文档里的 ```python 代码块；打包版通常已随包内置，无需下载",
    installLabel: "⬇ 下载安装（约 11MB）",
  },
  {
    key: "cpp",
    title: "C++ 编译器（g++）",
    desc: "运行文档里的 ```cpp 代码块；系统装过 g++ / clang++ 时优先用系统的",
    installLabel: "⬇ 下载安装（约 92MB）",
  },
];

function Row({ name, state }: { name: RuntimeComponentName; state?: InstallState }) {
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: (c: RuntimeComponentName) => api.runtime.install(c),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runtime-install"] }),
  });
  const { data: status } = useQuery({
    queryKey: ["runtime-status"],
    queryFn: api.runtime.status,
    select: (d) => d[name],
  });
  const meta = status?.installed && status.source !== "none" ? SOURCE_META[status.source] : null;
  const busy = state?.state === "downloading" || state?.state === "extracting";

  return (
    <div className="rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-gray-800 dark:text-gray-200">{ROWS.find((r) => r.key === name)!.title}</span>
        {status && (status.installed ? (
          <span className="rounded border border-green-300 bg-green-50 dark:bg-green-900/30 px-1.5 py-0.5 text-[10px] font-bold text-green-700 dark:text-green-400">
            ✅ 已安装
          </span>
        ) : (
          <span className="rounded border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 px-1.5 py-0.5 text-[10px] font-bold text-amber-700 dark:text-amber-400">
            未安装
          </span>
        ))}
        {meta && (
          <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${meta.cls}`}>{meta.label}</span>
        )}
        {status?.version && <span className="text-xs text-gray-500 dark:text-gray-400 dark:text-gray-400 dark:text-gray-400">{status.version}</span>}
        <span className="flex-1" />
        {status && !status.installed && (
          <Button
            variant="secondary"
            disabled={start.isPending || busy}
            onClick={() => start.mutate(name)}
            className="!px-2.5 !py-1 text-xs"
          >
            {start.isPending || busy ? (
              <>
                <Spinner /> 下载中…
              </>
            ) : (
              ROWS.find((r) => r.key === name)!.installLabel
            )}
          </Button>
        )}
      </div>
      <div className="mt-0.5 text-xs text-gray-400 dark:text-gray-500 dark:text-gray-400">{ROWS.find((r) => r.key === name)!.desc}</div>
      {status?.path && <div className="mt-0.5 truncate text-xs text-gray-400 dark:text-gray-500 dark:text-gray-400" title={status.path}>{status.path}</div>}
      {state && busy && (
        <div className="mt-2">
          <div className="h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
            <div
              className="h-full rounded-full bg-brand-500 transition-all"
              style={{ width: `${Math.max(2, Math.min(100, state.percent))}%` }}
            />
          </div>
          <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 dark:text-gray-400 dark:text-gray-400">{state.message}</div>
        </div>
      )}
      {state?.state === "done" && <div className="mt-1.5 text-xs text-green-600 dark:text-green-400">✅ {state.message}</div>}
      {state?.state === "error" && (
        <div className="mt-1.5 text-xs text-red-600 dark:text-red-400">❌ {state.message}（可重试，或换网络环境再试）</div>
      )}
    </div>
  );
}

export default function RuntimeEnvSection() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ["runtime-status"], queryFn: api.runtime.status });
  const { data: inst } = useQuery({
    queryKey: ["runtime-install"],
    queryFn: api.runtime.installStatus,
    refetchInterval: (q) => (q.state.data?.active ? 1000 : false),
  });

  const wasActive = useRef(false);
  useEffect(() => {
    const active = inst?.active ?? null;
    if (wasActive.current && !active) {
      qc.invalidateQueries({ queryKey: ["runtime-status"] });
    }
    wasActive.current = Boolean(active);
  }, [inst?.active, qc]);

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
      <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">代码运行环境</h2>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 dark:text-gray-400 dark:text-gray-400">
        文档里的代码块在本机受限沙箱运行。缺什么装什么：便携包直接解压到软件目录（
        <code className="rounded bg-gray-100 dark:bg-gray-800 px-1">toolchains/</code>），不改系统 PATH、不写注册表，删掉目录即卸载。
      </p>
      {status && !status.installable && (
        <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">当前平台（{status.platform}）不支持一键安装，请用系统包管理器安装。</p>
      )}
      <div className="mt-3 space-y-3">
        <Row name="python" state={inst?.components.python} />
        <Row name="cpp" state={inst?.components.cpp} />
      </div>
    </section>
  );
}
