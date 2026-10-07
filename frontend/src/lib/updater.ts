// 应用内自动更新：tauri-plugin-updater 封装（PRD 实现备注 19）。
// 桌面壳内（__TAURI_INTERNALS__ 存在）走插件检查/下载/静默安装；浏览器与局域网模式返回 null，
// 调用方回退「查看发布页」链接。latest.json 随 GitHub Release 发布（见 README 发布流程）。
import { api } from "./api";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

let lastOpenUrl = "";
let lastOpenTime = 0;

/** 打开外部链接：优先委托后端在操作系统默认浏览器中打开；若失败则兜底使用 window.open */
export async function openExternalUrl(url: string): Promise<boolean> {
  const now = Date.now();
  if (url === lastOpenUrl && now - lastOpenTime < 1000) {
    return true;
  }
  lastOpenUrl = url;
  lastOpenTime = now;

  let opened = false;
  try {
    const res = await api.system.openUrl(url);
    if (res && res.ok) {
      opened = true;
    }
  } catch (err) {
    console.warn("api.system.openUrl failed:", err);
  }

  if (!opened) {
    try {
      window.open(url, "_blank", "noopener,noreferrer");
      opened = true;
    } catch (err) {
      console.warn("window.open failed:", err);
    }
  }
  return opened;
}

export async function tauriSelfUpdate(
  onProgress?: (downloaded: number, total: number | null) => void
): Promise<{ version: string } | null> {
  if (!isTauri()) return null;
  const { check } = await import("@tauri-apps/plugin-updater");
  const update = await check();
  if (!update) return null;
  let downloaded = 0;
  let total: number | null = null;
  await update.downloadAndInstall((event) => {
    if (event.event === "Started") {
      total = event.data.contentLength ?? null;
      onProgress?.(0, total);
    } else if (event.event === "Progress") {
      downloaded += event.data.chunkLength;
      onProgress?.(downloaded, total);
    } else if (event.event === "Finished") {
      onProgress?.(total ?? downloaded, total);
    }
  });
  return { version: update.version };
}

export async function relaunchApp(): Promise<void> {
  const { relaunch } = await import("@tauri-apps/plugin-process");
  await relaunch();
}
