// 提问卡片：右侧滑出面板，划线原文 + 多轮流式对话 + 管理操作（PRD FR-3.2/3.3）
import { useEffect, useRef, useState } from "react";
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
  onClose: () => void;
  onJump: (a: Annotation) => void;
}

export default function AnnotationCard({
  annotation,
  conversationId,
  onClose,
  onJump,
}: Props) {
  const queryClient = useQueryClient();
  const hlColors = useHlColors();
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState("");
  const [streamErr, setStreamErr] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState(annotation.note ?? "");
  const [confirmDel, setConfirmDel] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);

  const { data: msgs, isLoading } = useQuery({
    queryKey: ["conv", conversationId],
    queryFn: () => api.conversations.messages(conversationId),
  });

  useEffect(() => {
    setNoteDraft(annotation.note ?? "");
  }, [annotation.id, annotation.note]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs?.length, streaming]);

  // 流式气泡：innerHTML 变化后补渲染公式
  useEffect(() => {
    if (streamRef.current) {
      renderMathInElement(streamRef.current, { delimiters: KATEX_DELIMITERS, throwOnError: false });
    }
  }, [streaming]);

  const send = async () => {
    const content = input.trim();
    if (!content || streaming) return;
    setInput("");
    setStreamErr("");
    let acc = "";
    try {
      await streamSSE(
        `/conversations/${conversationId}/messages`,
        { content },
        (ev: ChatSSEEvent) => {
          if (ev.type === "delta" && ev.text) {
            acc += ev.text;
            setStreaming(acc);
          } else if (ev.type === "done") {
            setStreaming("");
            queryClient.invalidateQueries({ queryKey: ["conv", conversationId] });
          } else if (ev.type === "error") {
            setStreamErr(ev.detail ?? "生成失败");
            setStreaming("");
          }
        }
      );
    } catch (e) {
      setStreamErr(`网络错误：${(e as Error).message}`);
      setStreaming("");
    }
  };

  const patch = useMutation({
    mutationFn: (body: { color?: AnnotationColor; note?: string }) =>
      api.annotations.update(annotation.id, body),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["doc-anns", annotation.document_id] }),
  });

  const makeCard = useMutation({
    mutationFn: () =>
      api.review.createCard({
        front: `请解释：${annotation.exact.slice(0, 60)}`,
        back: annotation.exact,
        annotation_id: annotation.id,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      setStreamErr("");
    },
  });

  const remove = useMutation({
    mutationFn: () => api.annotations.remove(annotation.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["doc-anns", annotation.document_id] });
      onClose();
    },
  });

  return (
    <div className="fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 bg-white shadow-xl sm:w-[420px]">
      {/* 头部：颜色切换 */}
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className="h-3.5 w-3.5 rounded-full"
            style={{ backgroundColor: hlColors[annotation.color] }}
          />
          <span className="text-sm font-semibold text-gray-900">划线提问</span>
          {annotation.status === "orphan" && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] text-red-600">
              原文已变更
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {HL_COLOR_KEYS.map((c) => (
            <button
              key={c}
              onClick={() => patch.mutate({ color: c })}
              className={`h-3.5 w-3.5 rounded-full border ${
                annotation.color === c ? "ring-2 ring-brand-500 ring-offset-1" : ""
              }`}
              style={{ backgroundColor: hlColors[c] }}
              title="更换颜色"
            />
          ))}
          <button
            onClick={onClose}
            className="ml-2 text-gray-400 hover:text-gray-600"
            title="关闭"
          >
            ✕
          </button>
        </div>
      </div>

      {/* 划线原文 */}
      <div className="border-b border-gray-100 px-4 py-3">
        <div className="flex gap-2">
          <span
            className="w-1 shrink-0 rounded"
            style={{ backgroundColor: hlColors[annotation.color] }}
          />
          <p className="line-clamp-6 flex-1 text-sm text-gray-600">{annotation.exact}</p>
        </div>
        <div className="mt-2 flex items-center gap-1 text-xs">
          <Button variant="ghost" className="text-xs" onClick={() => onJump(annotation)}>
            📍 定位原文
          </Button>
          <Button
            variant="ghost"
            className="text-xs"
            disabled={makeCard.isPending}
            onClick={() => makeCard.mutate()}
          >
            ➕ 转复习卡
          </Button>
          <Button variant="ghost" className="text-xs" onClick={() => setNoteOpen((v) => !v)}>
            📝 备注
          </Button>
          <Button
            variant="ghost"
            className="ml-auto text-xs text-red-500"
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
        {makeCard.isSuccess && <p className="mt-1 text-xs text-green-600">已加入复习队列 ✓</p>}
      </div>

      {/* 对话区 */}
      <div className="flex-1 space-y-3 overflow-auto px-4 py-3">
        {isLoading ? (
          <Spinner className="mx-auto mt-8 h-5 w-5" />
        ) : (
          (msgs ?? []).map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] rounded-xl px-3.5 py-2 ${
                  m.role === "user" ? "bg-brand-600 text-white" : "border border-gray-200 bg-gray-50"
                }`}
              >
                {m.role === "user" ? (
                  <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                ) : (
                  <MarkdownLite text={m.content} />
                )}
              </div>
            </div>
          ))
        )}
        {streaming && (
          <div className="flex justify-start">
            <div
              ref={streamRef}
              className="msg-md max-w-[90%] rounded-xl border border-gray-200 bg-gray-50 px-3.5 py-2"
              dangerouslySetInnerHTML={{ __html: md.render(streaming) }}
            />
          </div>
        )}
        {streamErr && <p className="text-center text-xs text-red-600">{streamErr}</p>}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div className="border-t border-gray-100 p-3">
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
          disabled={!!streaming}
        />
        <div className="mt-2 flex justify-end">
          <Button disabled={!input.trim() || !!streaming} onClick={send}>
            {streaming ? <Spinner className="border-white/40" /> : "发送"}
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
