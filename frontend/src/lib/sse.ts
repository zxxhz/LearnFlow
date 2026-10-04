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

/** POST + SSE：服务端流式返回（对话、评价等）。异常向上抛出。 */
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
  await fetchEventSource("/api" + url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      parseEvent(ev.data, onEvent);
    },
    onerror(err) {
      throw err; // 不自动重连，让调用方处理错误
    },
  });
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
