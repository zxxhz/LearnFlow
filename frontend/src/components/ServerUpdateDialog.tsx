// 服务端在线更新弹窗（ServerUpdateDialog）
// 当直接访问 VPS 服务端（Web 模式）发现新版本时弹出，支持一键在线直接更新服务端容器并重启倒计时
import { useEffect, useState } from "react";
import type { ServerSystemVersion, ServerUpdateTriggerResult } from "../lib/types";
import { Button, Modal, Spinner } from "./ui";
import { triggerServerUpdate } from "../lib/api";
import { showToast } from "../lib/toast";
import MarkdownLite from "./MarkdownLite";

export default function ServerUpdateDialog({
  update,
  onClose,
}: {
  update: ServerSystemVersion | null;
  onClose: () => void;
}) {
  const [updating, setUpdating] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);

  // 倒计时并在归零后轮询服务端健康检查（v0.5.3 体检 P2）：容器重启耗时可能超过
  // estimated_seconds，盲目 reload 会撞上停机窗口直接白屏；改为 2s/4s/8s…（上限 60s）
  // 指数退避探测版本接口，服务恢复后才刷新重连
  const [reconnecting, setReconnecting] = useState(false);
  useEffect(() => {
    if (countdown === null) return;
    if (countdown > 0) {
      const timer = setTimeout(() => {
        setCountdown((prev) => (prev !== null ? prev - 1 : 0));
      }, 1000);
      return () => clearTimeout(timer);
    }
    setReconnecting(true);
    let cancelled = false;
    let delay = 2000;
    const poll = async () => {
      while (!cancelled) {
        try {
          const res = await fetch("/api/relay/system/version", { cache: "no-store" });
          if (res.ok) {
            window.location.reload();
            return;
          }
        } catch {
          /* 服务仍在重启，继续退避重试 */
        }
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(delay * 2, 60_000);
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [countdown]);

  if (!update || !update.has_update) return null;

  const handleUpdate = async () => {
    try {
      setUpdating(true);
      const res: ServerUpdateTriggerResult = await triggerServerUpdate();
      if (res.status === "triggered") {
        const waitSec = res.estimated_seconds || 15;
        setCountdown(waitSec);
        showToast(res.message || "✅ 已触发云端服务端平滑升级");
      } else {
        setUpdating(false);
        showToast(res.message);
      }
    } catch (err: any) {
      setUpdating(false);
      showToast(`❌ 更新触发失败: ${err.message}`);
    }
  };

  return (
    <Modal
      open={true}
      onClose={updating ? () => {} : onClose}
      title="🚀 发现云端服务端新版本"
      width="max-w-lg"
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-1">
          <p className="text-sm text-gray-700 dark:text-gray-300">
            服务端新版本{" "}
            <strong className="text-brand-600 dark:text-brand-400">
              v{update.latest_version?.replace(/^v/, "")}
            </strong>{" "}
            已发布（当前运行版本 v{update.current_version}）。
          </p>
          {update.in_container && (
            <span className="inline-flex items-center rounded-md bg-blue-50 dark:bg-blue-950/60 px-1.5 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
              Docker 容器
            </span>
          )}
        </div>

        {update.release_notes ? (
          <div>
            <div className="mb-1.5 flex items-center justify-between text-xs font-semibold text-gray-500 dark:text-gray-400">
              <span>更新日志</span>
              {update.published_at && (
                <span className="font-normal text-[11px]">
                  {new Date(update.published_at).toLocaleString("zh-CN")}
                </span>
              )}
            </div>
            <div className="max-h-72 sm:max-h-80 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700/80 bg-gray-50/80 dark:bg-gray-800/50 p-3.5 text-xs text-gray-800 dark:text-gray-200">
              <MarkdownLite
                text={update.release_notes}
                className="[&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_h1]:text-gray-900 dark:[&_h1]:text-gray-100 [&_h2]:text-gray-900 dark:[&_h2]:text-gray-100 [&_h3]:text-gray-800 dark:[&_h3]:text-gray-200 [&_h1]:mt-2 [&_h2]:mt-2 [&_h3]:mt-2 [&_h1]:mb-1 [&_h2]:mb-1 [&_h3]:mb-1 [&>*:first-child]:mt-0 [&_hr]:my-2.5 [&_hr]:border-gray-200 dark:[&_hr]:border-gray-700"
              />
            </div>
          </div>
        ) : null}

        {updating && (
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-900/50 p-3 text-xs text-blue-800 dark:text-blue-300 flex items-center gap-2">
            <Spinner className="h-4 w-4" />
            <div>
              <span className="font-medium">
                正在拉取最新镜像并重启服务容器，{reconnecting ? "服务重启中，正在探测恢复（指数退避重试）…" : `预计将在 ${countdown ?? 15} 秒后自动刷新重连…`}
              </span>
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <Button
            disabled={updating}
            onClick={handleUpdate}
            className="text-xs bg-brand-600 hover:bg-brand-700 text-white font-medium px-4 py-1.5"
          >
            {updating ? (
              <>
                <Spinner className="h-3.5 w-3.5" /> 正在更新服务端 ({countdown}s)…
              </>
            ) : (
              "🚀 立即在线更新服务端"
            )}
          </Button>

          {update.html_url && (
            <a
              href={update.html_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-gray-300 dark:border-gray-600 px-2.5 py-1 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              查看 Release 详情 ↗
            </a>
          )}

          <Button
            variant="ghost"
            className="ml-auto text-xs"
            disabled={updating}
            onClick={onClose}
          >
            {updating ? "更新中…" : "稍后"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
