// 页内助教面板开关的全局标记（v0.5.9 体检 P3）：题库刷题/错题本等页面有自己的
// 页内 AI 助教面板（fixed 右侧浮层），全局 Ctrl+J 面板若不避让会与之叠成双层。
// 页面在打开/关闭（含卸载）页内面板时写标记，Layout 的 Ctrl+J 分支据此让位；
// 页面自身再给页内面板补 Esc 关闭出口。仅进程内标记，不落盘。
export function markPageAssistantOpen(open: boolean): void {
  if (typeof window === "undefined") return;
  const w = window as typeof window & { __learnflowPageAssistantOpen?: boolean };
  w.__learnflowPageAssistantOpen = open;
}

export function isPageAssistantOpen(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(
    (window as typeof window & { __learnflowPageAssistantOpen?: boolean })
      .__learnflowPageAssistantOpen
  );
}
