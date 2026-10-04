// 更新弹窗：启动自动检查 / 设置页手动检查发现新版本时弹出（PRD 实现备注 19）
import { useState } from "react";
import type { UpdateCheckResult } from "../lib/types";
import { Button, Modal, Spinner } from "./ui";
import { isTauri, tauriSelfUpdate, relaunchApp, openExternalUrl } from "../lib/updater";
import { notify } from "../lib/notify";

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
    <Modal open={!!update?.has_update} onClose={onClose} title="🎉 发现新版本" width="max-w-sm">
      {update?.has_update && (
        <>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            新版本{" "}
            <strong className="text-brand-600 dark:text-brand-400">{update.latest}</strong>{" "}
            已发布（当前 {update.current}）。
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <AutoUpdateButton />
            {update.url && (
              <a
                href={update.url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => {
                  e.preventDefault();
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
            一键更新会下载安装包并静默安装后自动重启；浏览器/局域网模式请到发布页手动下载。
          </p>
        </>
      )}
    </Modal>
  );
}
