// 更新弹窗：启动自动检查 / 设置页手动检查发现新版本时弹出（PRD 实现备注 19）
import { useState } from "react";
import type { UpdateCheckResult } from "../lib/types";
import { Button, Modal, Spinner } from "./ui";
import { isTauri, tauriSelfUpdate, relaunchApp, openExternalUrl } from "../lib/updater";
import { notify } from "../lib/notify";
import MarkdownLite from "./MarkdownLite";

// 应用内自动更新：桌面壳内下载新安装包（带进度）→ 静默安装 → 自动重启；
// 浏览器/局域网模式不渲染（isTauri 为 false），保留「查看发布页」链接
function AutoUpdateButton() {
  const [phase, setPhase] = useState<"idle" | "downloading" | "installing">("idle");
  const [pct, setPct] = useState<number | null>(null);

  if (!isTauri()) return null;

  const run = async () => {
    setPhase("downloading");
    setPct(null);
    try {
      await tauriSelfUpdate((done, total) => {
        setPct(total ? Math.min(100, Math.round((done / total) * 100)) : null);
      });
      setPhase("installing");
      await relaunchApp();
    } catch {
      setPhase("idle");
      notify("更新失败", "自动更新出错，请到发布页手动下载安装包。");
    }
  };

  return (
    <button
      disabled={phase !== "idle"}
      onClick={run}
      className="rounded-md bg-green-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-800 disabled:opacity-70"
    >
      {phase === "idle" && "⬇ 一键更新"}
      {phase === "downloading" && (pct !== null ? `下载中 ${pct}%` : "下载中…")}
      {phase === "installing" && "安装中，即将重启…"}
    </button>
  );
}

export default function UpdateDialog({
  update,
  onClose,
}: {
  update: UpdateCheckResult | null;
  onClose: () => void;
}) {
  return (
    <Modal open={!!update?.has_update} onClose={onClose} title="🎉 发现新版本" width="max-w-lg">
      {update?.has_update && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-1">
            <p className="text-sm text-gray-700 dark:text-gray-300">
              新版本{" "}
              <strong className="text-brand-600 dark:text-brand-400">{update.latest}</strong>{" "}
              已发布（当前 {update.current}）。
            </p>
            {update.active_mirror && (
              <span className="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 inline-block" />
                加速源: <strong className="font-medium text-gray-700 dark:text-gray-300">{update.active_mirror}</strong>
              </span>
            )}
          </div>

          {update.notes ? (
            <div className="mt-3">
              <div className="mb-1.5 flex items-center justify-between text-xs font-semibold text-gray-500 dark:text-gray-400">
                <span>更新日志</span>
              </div>
              <div className="max-h-72 sm:max-h-80 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700/80 bg-gray-50/80 dark:bg-gray-800/50 p-3.5 text-xs text-gray-800 dark:text-gray-200">
                <MarkdownLite
                  text={update.notes}
                  className="[&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_h1]:text-gray-900 dark:[&_h1]:text-gray-100 [&_h2]:text-gray-900 dark:[&_h2]:text-gray-100 [&_h3]:text-gray-800 dark:[&_h3]:text-gray-200 [&_h1]:mt-2 [&_h2]:mt-2 [&_h3]:mt-2 [&_h1]:mb-1 [&_h2]:mb-1 [&_h3]:mb-1 [&>*:first-child]:mt-0 [&_hr]:my-2.5 [&_hr]:border-gray-200 dark:[&_hr]:border-gray-700"
                />
              </div>
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <AutoUpdateButton />
            {update.accelerated_url && (
              <a
                href={update.accelerated_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  openExternalUrl(update.accelerated_url!);
                }}
                className="rounded-md bg-blue-600 dark:bg-blue-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 dark:hover:bg-blue-800"
                title="使用当前最优镜像通道下载完整安装包"
              >
                ⚡ 极速下载安装包
              </a>
            )}
            {update.url && (
              <a
                href={update.url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  openExternalUrl(update.url!);
                }}
                className="rounded-md border border-gray-300 dark:border-gray-600 px-2.5 py-1 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                查看发布页
              </a>
            )}
            <Button variant="ghost" className="ml-auto text-xs" onClick={onClose}>
              稍后
            </Button>
          </div>
          <p className="mt-3 text-[10px] text-gray-400 dark:text-gray-500">
            一键更新会通过智能测速加速源下载安装包并静默安装重启；亦可直接点击极速下载。
          </p>
        </>
      )}
    </Modal>
  );
}
