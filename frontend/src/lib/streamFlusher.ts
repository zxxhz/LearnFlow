// 流式输出渲染节流：SSE delta 先写入缓冲，120ms 尾沿批量刷进 state，
// 避免每个 token 都触发全量 setState + markdown 重渲染（O(n²) 卡顿）。
export interface StreamFlusher {
  /** 记录最新全文并确保 120ms 内有一次刷新（尾沿节流，非防抖，长流不会丢中间帧） */
  push(text: string): void;
  /** 立即刷新缓冲中的最新全文（done / 终止 / 出错时调用，保证最终渲染完整） */
  flushNow(): void;
  /** 丢弃缓冲与定时器（最终结果已另行落 state 时使用） */
  cancel(): void;
}

export function createStreamFlusher(
  flush: (text: string) => void,
  intervalMs = 120
): StreamFlusher {
  let pending: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const doFlush = () => {
    timer = null;
    if (pending != null) {
      const text = pending;
      pending = null;
      flush(text);
    }
  };
  return {
    push(text: string) {
      pending = text;
      if (timer == null) timer = setTimeout(doFlush, intervalMs);
    },
    flushNow() {
      if (timer != null) {
        clearTimeout(timer);
        doFlush();
      } else if (pending != null) {
        const text = pending;
        pending = null;
        flush(text);
      }
    },
    cancel() {
      if (timer != null) {
        clearTimeout(timer);
        timer = null;
      }
      pending = null;
    },
  };
}
