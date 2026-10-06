// 提问卡片：右侧滑出面板，划线原文 + 多轮流式对话 + 管理操作（PRD FR-3.2/3.3）
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import MarkdownIt from "markdown-it";
import renderMathInElement from "katex/contrib/auto-render";
import { api } from "../../lib/api";
import { streamSSE } from "../../lib/sse";
import type { Annotation, AnnotationColor, ChatSSEEvent } from "../../lib/types";
import { Button, ConfirmDialog, Spinner, Textarea } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";
import { HL_COLOR_KEYS, useHlColors } from "./colors";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
const KATEX_DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "$", right: "$", display: false },
];

interface Props {
  annotation: Annotation;
  conversationId: string;
  closing?: boolean;
  onClose: () => void;
  onJump: (a: Annotation) => void;
}

export default function AnnotationCard({
  annotation,
  conversationId,
  closing = false,
  onClose,
  onJump,
}: Props) {
  const queryClient = useQueryClient();
  const hlColors = useHlColors();
  const [mounted, setMounted] = useState(false);
  const [input, setInput] = useState("");
  // 本地临时/乐观消息（用户刚发出的问题与刚完成的回复，避免等网络回包闪烁）
  const [localMsgs, setLocalMsgs] = useState<
    Array<{ id: string; role: "user" | "assistant"; content: string }>
  >([]);
  const [isThinking, setIsThinking] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [streamErr, setStreamErr] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState(annotation.note ?? "");
  const [confirmDel, setConfirmDel] = useState(false);
  const [currentColor, setCurrentColor] = useState<AnnotationColor>(annotation.color);
  const bottomRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setMounted(true);
    }, 20);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    setCurrentColor(annotation.color);
  }, [annotation.color]);

  const { data: serverMsgs, isLoading } = useQuery({
    queryKey: ["conv", conversationId],
    queryFn: () => api.conversations.messages(conversationId),
  });

  // 合并服务端消息与本地乐观消息，确保用户输入后 0ms 瞬间显示在对话中
  const displayMsgs = useMemo(() => {
    const list = [...(serverMsgs ?? [])];
    const serverIds = new Set(list.map((m) => m.id));
    const serverUserContents = new Set(
      list.filter((m) => m.role === "user").map((m) => m.content.trim())
    );

    for (const lm of localMsgs) {
      if (serverIds.has(lm.id)) continue;
      if (lm.role === "user" && serverUserContents.has(lm.content.trim())) continue;
      list.push({
        id: lm.id,
        conversation_id: conversationId,
        role: lm.role,
        content: lm.content,
        created_at: new Date().toISOString(),
      });
    }
    return list;
  }, [serverMsgs, localMsgs, conversationId]);

  useEffect(() => {
    setNoteDraft(annotation.note ?? "");
  }, [annotation.id, annotation.note]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayMsgs.length, isThinking, streaming]);

  // 流式气泡：innerHTML 变化后补渲染公式
  useEffect(() => {
    if (streamRef.current) {
      renderMathInElement(streamRef.current, { delimiters: KATEX_DELIMITERS, throwOnError: false });
    }
  }, [streaming]);

  const send = async () => {
    const content = input.trim();
    if (!content || streaming || isThinking) return;

    // 1. 立即清空输入，并在 UI 上乐观插入用户提问气泡
    const tempUserId = `temp-user-${Date.now()}`;
    setLocalMsgs((prev) => [...prev, { id: tempUserId, role: "user", content }]);
    setInput("");
    setStreamErr("");
    setIsThinking(true);
    setStreaming("");

    setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 30);

    let acc = "";
    try {
      await streamSSE(
        `/conversations/${conversationId}/messages`,
        { content },
        (ev: any) => {
          if (ev.type === "user_ack" && ev.message) {
            // 后端持久化成功，将乐观消息 ID 对齐
            setLocalMsgs((prev) =>
              prev.map((m) => (m.id === tempUserId ? { ...m, id: ev.message.id } : m))
            );
          } else if (ev.type === "delta" && ev.text) {
            setIsThinking(false);
            acc += ev.text;
            setStreaming(acc);
          } else if (ev.type === "done") {
            const assistantText = acc || ev.content || "";
            if (assistantText) {
              setLocalMsgs((prev) => [
                ...prev,
                {
                  id: ev.message_id || `temp-asst-${Date.now()}`,
                  role: "assistant",
                  content: assistantText,
                },
              ]);
            }
            setStreaming("");
            setIsThinking(false);
            queryClient.invalidateQueries({ queryKey: ["conv", conversationId] });
          } else if (ev.type === "error") {
            setIsThinking(false);
            setStreamErr(ev.detail ?? "生成失败，请重试");
            if (!acc) {
              setStreaming("");
            }
          }
        }
      );
    } catch (e) {
      setIsThinking(false);
      setStreamErr(`网络错误：${(e as Error).message}`);
    }
  };

  const patch = useMutation({
    mutationFn: (body: { color?: AnnotationColor; note?: string }) =>
      api.annotations.update(annotation.id, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["doc-anns", annotation.document_id] }),
  });

  const handleColorChange = (c: AnnotationColor) => {
    setCurrentColor(c);
    patch.mutate({ color: c });
  };

  const remove = useMutation({
    mutationFn: () => api.annotations.remove(annotation.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["doc-anns", annotation.document_id] });
      onClose();
    },
  });

  const isVisible = mounted && !closing;

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl sm:w-[420px] transition-transform duration-300 ease-out transform ${
        isVisible ? "translate-x-0" : "translate-x-full"
      }`}
    >
      {/* 头部：颜色切换与关闭 */}
      <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className="h-3.5 w-3.5 rounded-full shadow-sm"
            style={{ backgroundColor: hlColors[currentColor] }}
          />
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">划线提问</span>
          {annotation.status === "orphan" && (
            <span className="rounded-full bg-red-100 dark:bg-red-900/40 px-2 py-0.5 text-[10px] text-red-600 dark:text-red-400">
              原文已变更
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {HL_COLOR_KEYS.map((c) => (
            <button
              key={c}
              onClick={() => handleColorChange(c)}
              className={`h-3.5 w-3.5 rounded-full border transition-transform ${
                currentColor === c ? "scale-110 ring-2 ring-brand-500 ring-offset-1" : "hover:scale-105"
              }`}
              style={{ backgroundColor: hlColors[c] }}
              title="更换颜色"
            />
          ))}
          <button
            onClick={onClose}
            className="ml-2 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
            title="关闭"
          >
            ✕
          </button>
        </div>
      </div>

      {/* 划线原文 */}
      <div className="border-b border-gray-100 dark:border-gray-800 px-4 py-3 bg-gray-50/50 dark:bg-gray-800/30">
        <div className="flex gap-2">
          <span
            className="w-1 shrink-0 rounded"
            style={{ backgroundColor: hlColors[currentColor] }}
          />
          <p className="line-clamp-6 flex-1 text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
            {annotation.exact}
          </p>
        </div>
        <div className="mt-2 flex items-center gap-1 text-xs">
          <Button variant="ghost" className="text-xs" onClick={() => onJump(annotation)}>
            📍 定位原文
          </Button>
          <Button variant="ghost" className="text-xs" onClick={() => setNoteOpen((v) => !v)}>
            📝 备注
          </Button>
          <Button
            variant="ghost"
            className="ml-auto text-xs text-red-500 dark:text-red-400 hover:text-red-600"
            onClick={() => setConfirmDel(true)}
          >
            删除
          </Button>
        </div>
        {noteOpen && (
          <div className="mt-2">
            <Textarea
              rows={2}
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="私有备注（不进入对话）"
            />
            <div className="mt-1 text-right">
              <Button
                variant="secondary"
                className="text-xs"
                onClick={() => {
                  patch.mutate({ note: noteDraft });
                  setNoteOpen(false);
                }}
              >
                保存备注
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* 对话区 */}
      <div className="flex-1 space-y-3 overflow-auto px-4 py-3">
        {isLoading && displayMsgs.length === 0 ? (
          <Spinner className="mx-auto mt-8 h-5 w-5" />
        ) : (
          displayMsgs.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] rounded-xl px-3.5 py-2 leading-relaxed ${
                  m.role === "user"
                    ? "bg-brand-600 text-white shadow-sm"
                    : "border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 text-gray-800 dark:text-gray-200 shadow-sm"
                }`}
              >
                {m.role === "user" ? (
                  <p className="whitespace-pre-wrap text-sm break-words">{m.content}</p>
                ) : (
                  <MarkdownLite text={m.content} />
                )}
              </div>
            </div>
          ))
        )}

        {/* AI 思考中动效 */}
        {isThinking && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-3.5 py-2 text-xs text-gray-500 dark:text-gray-400">
              <div className="flex items-center space-x-1">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
              <span>AI 助教正在思考解答…</span>
            </div>
          </div>
        )}

        {/* AI 流式打字机输出 */}
        {streaming && (
          <div className="flex justify-start">
            <div
              ref={streamRef}
              className="msg-md max-w-[90%] rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-3.5 py-2 text-sm text-gray-800 dark:text-gray-200 shadow-sm"
            >
              <div dangerouslySetInnerHTML={{ __html: md.render(streaming) }} />
              <span className="inline-block h-3.5 w-1.5 ml-0.5 align-middle bg-brand-500 animate-pulse rounded-sm" />
            </div>
          </div>
        )}

        {streamErr && (
          <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 p-2 text-center text-xs text-red-600 dark:text-red-400">
            {streamErr}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div className="border-t border-gray-100 dark:border-gray-800 p-3 bg-white dark:bg-gray-900">
        <Textarea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="就划线内容提问…（Enter 发送，Shift+Enter 换行）"
          disabled={!!streaming || isThinking}
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[11px] text-gray-400 dark:text-gray-500">
            Enter 发送 / Shift+Enter 换行
          </span>
          <Button disabled={!input.trim() || !!streaming || isThinking} onClick={send}>
            {streaming || isThinking ? <Spinner className="border-white/40" /> : "发送"}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDel}
        title="删除标注"
        message="将删除该划线及其全部对话记录，确定？"
        onCancel={() => setConfirmDel(false)}
        onConfirm={() => {
          setConfirmDel(false);
          remove.mutate();
        }}
      />
    </div>
  );
}
