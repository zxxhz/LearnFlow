// 桌面通知：Tauri 插件优先，浏览器 Notification 兜底（两者都不可用则静默）
export async function notify(title: string, body: string): Promise<void> {
  try {
    const mod = await import("@tauri-apps/plugin-notification");
    let granted = await mod.isPermissionGranted();
    if (!granted) granted = (await mod.requestPermission()) === "granted";
    if (granted) {
      mod.sendNotification({ title, body });
      return;
    }
  } catch {
    /* 非 Tauri 环境，走浏览器通知 */
  }
  try {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    } else if (Notification.permission !== "denied") {
      const p = await Notification.requestPermission();
      if (p === "granted") new Notification(title, { body });
    }
  } catch {
    /* 通知不可用：静默 */
  }
}
