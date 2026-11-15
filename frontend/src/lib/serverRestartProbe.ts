// 服务端重启探测共享 helper（v0.5.9 体检 P3）：容器重启耗时可能超过预估秒数，
// 盲目 reload 会撞上停机窗口直接白屏。以 2s/4s/8s…（单次间隔上限 60s）指数退避
// 轮询 check()，服务恢复（返回 true）后才 reload。ServerUpdateDialog 与设置页
// ServerUpdateCard 共用，各自保留自己的探测目标接口。
export interface ProbeOptions {
  /** 取消探测（effect cleanup / 重新触发时） */
  signal?: AbortSignal;
  /** 总时限（ms）：超时后停止探测并调用 onTimeout，不再无限等待 */
  timeoutMs?: number;
  /** 超时回调（提示用户手动检查、解锁界面等） */
  onTimeout?: () => void;
}

export function probeServerRestartThenReload(
  check: () => Promise<boolean>,
  opts: ProbeOptions = {}
): void {
  void (async () => {
    let delay = 2000;
    const startedAt = Date.now();
    // fire-and-forget 循环：调用方不 await；reload 是唯一成功出口
    for (;;) {
      if (opts.signal?.aborted) return;
      if (opts.timeoutMs !== undefined && Date.now() - startedAt >= opts.timeoutMs) {
        opts.onTimeout?.();
        return;
      }
      try {
        if (await check()) {
          window.location.reload();
          return;
        }
      } catch {
        /* 服务仍在重启，继续退避重试 */
      }
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 60_000);
    }
  })();
}
