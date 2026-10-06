// SSE 客户端：POST（发消息/触发动作）与 GET（订阅进度）两种
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { getAccessToken } from "./api";

function parseEvent(data: string, onEvent: (payload: any) => void) {
  if (!data) return;
  try {
    onEvent(JSON.parse(data));
  } catch {
    /* 非 JSON 事件忽略 */
  }
}

/** POST + SSE：服务端流式返回（对话、评价等）。使用原生 fetch + ReadableStream 逐块实时解析，杜绝自动重试与缓冲挂起。 */
export async function streamSSE(
  url: string,
  body: unknown,
  onEvent: (payload: any) => void,
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
    throw new Error(detail);
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
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        for (const line of part.split("\n")) {
          const trimmed = line.trim();
          if (trimmed.startsWith("data:")) {
            const dataStr = trimmed.slice(5).trim();
            parseEvent(dataStr, onEvent);
          }
        }
      }
    }
    if (buffer.trim()) {
      for (const line of buffer.split("\n")) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data:")) {
          const dataStr = trimmed.slice(5).trim();
          parseEvent(dataStr, onEvent);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** GET + SSE：订阅服务端事件流（生成进度等）。 */
export async function subscribeSSE(
  url: string,
  onEvent: (payload: any) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getAccessToken();
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (token) headers["x-access-token"] = token;
  await fetchEventSource("/api" + url, {
    method: "GET",
    headers,
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      parseEvent(ev.data, onEvent);
    },
    onerror(err) {
      throw err;
    },
  });
}
