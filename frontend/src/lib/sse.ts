// SSE 客户端：POST（发消息/触发动作）与 GET/POST（订阅进度）两种
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { getAccessToken, notifyAuthExpired } from "./api";

function parseEvent<T>(data: string, onEvent: (payload: T) => void) {
  if (!data) return;
  try {
    onEvent(JSON.parse(data) as T);
  } catch {
    /* 非 JSON 事件忽略 */
  }
}

/**
 * 按规范处理一个 SSE 事件帧：同一事件内多行 `data:` 用 "\n" 拼接后再整体 JSON.parse。
 * 逐行 parse 会把多行事件（跨行 JSON 或含换行的文本负载）拆碎丢弃；
 * event:/id:/retry: 等字段本客户端不消费，忽略。
 */
function dispatchFrame<T>(frame: string, onEvent: (payload: T) => void) {
  const dataLines: string[] = [];
  for (const rawLine of frame.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (dataLines.length > 0) {
    parseEvent(dataLines.join("\n"), onEvent);
  }
}

/** POST + SSE：服务端流式返回（对话、评价等）。使用原生 fetch + ReadableStream 逐块实时解析，杜绝自动重试与缓冲挂起。 */
export async function streamSSE<T = unknown>(
  url: string,
  body: unknown,
  onEvent: (payload: T) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (token) headers["x-access-token"] = token;

  const res = await fetch("/api" + url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    let detail = `请求失败（HTTP ${res.status}）`;
    try {
      const errJson = await res.json();
      if (errJson?.detail) {
        detail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      /* ignore */
    }
    if (res.status === 401) notifyAuthExpired();
    throw new Error(detail);
  }

  // 非 SSE 响应（如网关返回 JSON/HTML 错误页）直接报错：
  // 否则上层收不到任何事件，表现为静默无回复
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("text/event-stream")) {
    throw new Error(`响应不是 SSE 事件流（HTTP ${res.status}，Content-Type: ${contentType || "未知"}）`);
  }

  if (!res.body) {
    throw new Error("服务端未返回数据流");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // 事件以空行分帧（\r\n\r\n 或 \n\n 均合法）
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() ?? "";
      for (const frame of parts) {
        dispatchFrame(frame, onEvent);
      }
    }
    if (buffer.trim()) {
      dispatchFrame(buffer, onEvent);
    }
  } finally {
    reader.releaseLock();
  }
}

/** SSE 订阅额外选项 */
export interface SubscribeSSEOptions {
  /** 请求方法，默认 GET（保持既有调用方不变）；带副作用的端点（如 in-app-install）应传 POST */
  method?: "GET" | "POST";
}

/** GET/POST + SSE：订阅服务端事件流（生成进度、应用内更新安装等）。 */
export async function subscribeSSE<T = unknown>(
  url: string,
  onEvent: (payload: T) => void,
  signal?: AbortSignal,
  opts?: SubscribeSSEOptions
): Promise<void> {
  const token = getAccessToken();
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (token) headers["x-access-token"] = token;
  await fetchEventSource("/api" + url, {
    method: opts?.method ?? "GET",
    headers,
    signal,
    openWhenHidden: true,
    // 自带 onopen 才拿得到 response.status：默认实现抛的错不带 status，401 无法识别
    async onopen(res) {
      if (res.status === 401) notifyAuthExpired();
      if (res.ok && (res.headers.get("content-type") || "").includes("text/event-stream")) {
        return;
      }
      throw new Error(`请求失败（HTTP ${res.status}）`);
    },
    onmessage(ev) {
      parseEvent(ev.data, onEvent);
    },
    onerror(err) {
      throw err;
    },
  });
}
