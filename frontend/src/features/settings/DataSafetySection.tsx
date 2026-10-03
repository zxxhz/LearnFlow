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
    onError: (e) => alert(e.message),
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
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">局域网访问（平板）</h3>
        {!access?.lan_mode ? (
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            当前仅本机访问（127.0.0.1）。用 <code className="rounded bg-gray-100 dark:bg-gray-800 px-1">APP_HOST=0.0.0.0</code> 启动可开启平板访问，开启后自动启用访问令牌。
          </p>
        ) : (
          <div className="mt-2 space-y-2">
            {access.lan_urls_with_token.map((u) => (
              <div key={u} className="truncate rounded bg-gray-50 dark:bg-gray-800/50 px-2.5 py-1.5 font-mono text-[11px] text-gray-600 dark:text-gray-400">
                {u}
              </div>
            ))}
            <div className="flex items-center gap-2">
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
