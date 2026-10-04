// 数据与安全：一键备份/恢复 + 局域网访问令牌（0.0.0.0 平板场景）
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Button, EmptyState, Spinner } from "../../components/ui";

function fmtSize(n: number): string {
  if (n > 1048576) return `${(n / 1048576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

export default function DataSafetySection() {
  const qc = useQueryClient();
  const [msg, setMsg] = useState("");
  const { data: backups, isLoading: loadingBackups } = useQuery({
    queryKey: ["system-backups"],
    queryFn: api.system.backups,
  });
  const { data: access } = useQuery({
    queryKey: ["system-access"],
    queryFn: api.system.accessInfo,
    staleTime: 30_000,
  });

  const flash = (m: string) => {
    setMsg(m);
    setTimeout(() => setMsg(""), 2500);
  };

  const doBackup = useMutation({
    mutationFn: api.system.backup,
    onSuccess: (b) => {
      flash(`已备份：${b.name}（${fmtSize(b.size)}）`);
      qc.invalidateQueries({ queryKey: ["system-backups"] });
    },
    onError: (e) => alert(e.message),
  });
  const doRestore = useMutation({
    mutationFn: (name: string) => api.system.restore(name),
    onSuccess: (r) => flash(r.message),
    onError: (e) => alert(e.message),
  });
  const doDelete = useMutation({
    mutationFn: (name: string) => api.system.deleteBackup(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["system-backups"] }),
    onError: (e) => alert(e.message),
  });
  const doRotate = useMutation({
    mutationFn: api.system.rotateToken,
    onSuccess: (a) => {
      qc.setQueryData(["system-access"], a);
      qc.invalidateQueries({ queryKey: ["system-access"] });
      flash("已重新生成令牌，旧地址立即失效");
    },
    onError: (e) => alert((e as Error).message),
  });
  const doToggleLan = useMutation({
    mutationFn: (enabled: boolean) => api.system.setLanAccess(enabled),
    onSuccess: (a) => {
      qc.setQueryData(["system-access"], a);
      qc.invalidateQueries({ queryKey: ["system-access"] });
      flash(a.lan_mode ? "已开启局域网访问" : "已关闭局域网访问");
    },
    onError: (e) => alert((e as Error).message),
  });

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
      <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">数据与安全</h2>
      {msg && <p className="mt-2 rounded bg-green-50 dark:bg-green-900/30 px-2.5 py-1.5 text-xs text-green-700 dark:text-green-400">{msg}</p>}

      <div className="mt-3 flex items-center gap-3">
        <Button variant="secondary" disabled={doBackup.isPending} onClick={() => doBackup.mutate()}>
          {doBackup.isPending ? (
            <>
              <Spinner className="h-3.5 w-3.5" /> 打包中…
            </>
          ) : (
            "⬒ 立即备份"
          )}
        </Button>
        <span className="text-xs text-gray-400 dark:text-gray-500">打包 app.db + courses/ 到 data/backups/</span>
      </div>
      <div className="mt-3">
        {loadingBackups ? (
          <Spinner className="h-4 w-4" />
        ) : !backups || backups.length === 0 ? (
          <p className="text-xs text-gray-400 dark:text-gray-500">还没有备份文件。</p>
        ) : (
          <div className="space-y-1.5">
            {backups.map((b) => (
              <div key={b.name} className="flex items-center justify-between rounded-lg border border-gray-100 dark:border-gray-800 px-3 py-1.5 text-xs">
                <span className="truncate text-gray-700 dark:text-gray-300">
                  {b.name} <span className="text-gray-400 dark:text-gray-500">({fmtSize(b.size)})</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <button
                    className="text-brand-600 underline"
                    onClick={() => {
                      if (confirm(`用 ${b.name} 恢复数据？当前未备份的修改会丢失。恢复在重启应用后生效。`))
                        doRestore.mutate(b.name);
                    }}
                  >
                    恢复
                  </button>
                  <button
                    className="text-gray-400 dark:text-gray-500 underline hover:text-red-500 dark:hover:text-red-400"
                    onClick={() => {
                      if (confirm(`删除备份 ${b.name}？`)) doDelete.mutate(b.name);
                    }}
                  >
                    删除
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-5 border-t border-gray-100 dark:border-gray-800 pt-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">局域网访问</h3>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              允许同一 Wi-Fi 或局域网下的手机、平板及其他设备通过浏览器访问本应用
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={access?.lan_mode ?? false}
              disabled={doToggleLan.isPending}
              onChange={(e) => doToggleLan.mutate(e.target.checked)}
            />
            <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-600 peer-checked:bg-brand-600"></div>
          </label>
        </div>

        {!access?.lan_mode ? (
          <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
            局域网访问已关闭，当前仅允许本机访问（127.0.0.1）。
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            <div className="text-xs text-gray-600 dark:text-gray-400">
              在局域网设备浏览器中打开以下完整地址（含专属安全令牌）：
            </div>
            {access.lan_urls_with_token.map((u) => (
              <div
                key={u}
                onClick={() => {
                  navigator.clipboard.writeText(u);
                  flash("地址与令牌已复制到剪贴板");
                }}
                className="group flex items-center justify-between rounded-lg bg-gray-50 dark:bg-gray-800/50 px-3 py-2 font-mono text-xs text-gray-700 dark:text-gray-300 border border-gray-100 dark:border-gray-800 hover:border-brand-300 dark:hover:border-brand-700 cursor-pointer transition"
                title="点击复制访问地址"
              >
                <span className="truncate">{u}</span>
                <span className="shrink-0 text-[11px] text-brand-600 dark:text-brand-400 opacity-80 group-hover:opacity-100 ml-2">复制</span>
              </div>
            ))}
            <div className="flex items-center gap-2 pt-1">
              <Button variant="secondary" className="text-xs" disabled={doRotate.isPending} onClick={() => doRotate.mutate()}>
                重新生成令牌
              </Button>
              <span className="text-[10px] text-gray-400 dark:text-gray-500">非本机来源必须携带 token；重新生成后旧地址立即失效。</span>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
