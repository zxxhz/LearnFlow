// 更新弹窗：启动自动检查 / 设置页手动检查发现新版本时弹出（PRD 实现备注 19）
import { useState } from "react";
import type { UpdateCheckResult } from "../lib/types";
import { Button, Modal } from "./ui";
import { isTauri, inAppMirrorUpdate, tauriSelfUpdate, relaunchApp, openExternalUrl } from "../lib/updater";
import { notify } from "../lib/notify";
import MarkdownLite from "./MarkdownLite";

// 应用内自动更新：优先通过国内/自定义镜像源极速下载安装包并静默安装重启；
// 浏览器/局域网模式不渲染（isTauri 为 false），保留「查看发布页」与「浏览器极速下载」
function AutoUpdateButton({ update }: { update: UpdateCheckResult }) {
  const [phase, setPhase] = useState<"idle" | "downloading" | "installing">("idle");
  const [pct, setPct] = useState<number | null>(null);
  const [speed, setSpeed] = useState<number | null>(null);

  if (!isTauri()) return null;

  const run = async () => {
    setPhase("downloading");
    setPct(null);
    setSpeed(null);

    try {
      // 1. 优先使用国内/自定义最优加速镜像源进行极速下载与静默安装
      await inAppMirrorUpdate(
        update.latest || "",
        update.accelerated_url,
        (p) => {
          if (p.phase === "downloading") {
            setPct(p.percent);
            setSpeed(p.speed_mb ?? null);
          } else if (p.phase === "ready" || p.phase === "installing") {
            setPhase("installing");
          }
        }
      );
      setPhase("installing");
    } catch (mirrorErr) {
      console.warn("镜像一键更新失败，尝试回退到官方 updater 直连通道:", mirrorErr);
      // 2. 备用回退机制：若镜像源出现网络异常，尝试回退到 Tauri 原生直连通道
      try {
        await tauriSelfUpdate((done, total) => {
          setPct(total ? Math.min(100, Math.round((done / total) * 100)) : null);
        });
        setPhase("installing");
        await relaunchApp();
      } catch (officialErr) {
        setPhase("idle");
        notify("自动更新未完成", "请尝试点击右侧「⚡ 浏览器极速下载」或到发布页手动下载。");
      }
    }
  };

  return (
    <button
      disabled={phase !== "idle"}
      onClick={run}
      className="rounded-md bg-green-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-800 disabled:opacity-70 flex items-center gap-1.5 transition"
      title="通过当前最快国内镜像源在软件内极速更新并自动重启"
    >
      {phase === "idle" && "⬇ 一键更新 (极速)"}
      {phase === "downloading" && (
        <>
          <span className="inline-block h-2 w-2 rounded-full bg-white animate-pulse" />
          <span>
            {pct !== null ? `下载中 ${pct}%` : "建立连接中…"}
            {speed !== null && speed > 0 ? ` (${speed} MB/s)` : ""}
          </span>
        </>
      )}
      {phase === "installing" && "下载完成，正在打开新安装包…"}
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
            <AutoUpdateButton update={update} />
            {update.accelerated_url && (
              <a
                href={update.accelerated_url}
                target="_blank"
                rel="noreferrer"
                onClick={async (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  await openExternalUrl(update.accelerated_url!);
                  notify("已唤起浏览器下载", "正在通过加速镜像下载安装包，请查看您的浏览器下载列表。");
                }}
                className="rounded-md bg-blue-600 dark:bg-blue-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 dark:hover:bg-blue-800"
                title="通过当前最快国内镜像在浏览器中下载完整安装包"
              >
                ⚡ 浏览器极速下载
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
          <div className="mt-3.5 rounded-lg bg-gray-50 dark:bg-gray-800/60 border border-gray-100 dark:border-gray-700/60 p-2.5 text-[11px] text-gray-500 dark:text-gray-400 space-y-1">
            <div className="flex items-start gap-1.5">
              <span className="font-semibold text-gray-700 dark:text-gray-300">⬇ 一键更新：</span>
              <span>软件内自动静默下载、安装并重启，全程无需手动操作。</span>
            </div>
            <div className="flex items-start gap-1.5">
              <span className="font-semibold text-gray-700 dark:text-gray-300">⚡ 浏览器极速下载：</span>
              <span>调用系统默认浏览器经国内最优镜像下载 <code>.exe</code> 安装包，用于手动覆盖安装（网络受阻时的备用方案）。</span>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
