// 统一「AI 助教」面板（v0.5.0）：全站唯一的答疑交互面。
// 阅读页（讲义+练习共用 document 会话）/ 题库单题 / 全局呼出，同一张脸、同一套流式协议。
// 顶部自动挂当前场景上下文标签；支持旧知/错题来源跳转标签、函数图像、思维导图与随堂微测卡（经 MarkdownLite）。
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type {
  Annotation,
  AnnotationColor,
  AssistantContextType,
  AssistantReference,
  AssistantSceneContext,
  AssistantSSEEvent,
  Message,
} from "../lib/types";
import { Button, ConfirmDialog, Spinner, Textarea } from "./ui";
import MarkdownLite from "./MarkdownLite";
import { createStreamFlusher } from "../lib/streamFlusher";
import { sanitizeSvg } from "../lib/sanitize";
import { HL_COLOR_KEYS, useHlColors } from "../features/reader/colors";
import { useFontSize } from "../lib/fontSize";

interface Props {
  open: boolean;
  closing?: boolean;
  contextType: AssistantContextType;
  contextId: string;
  /** 场景标签文案，如「📖 当前章节：《计网》第2节」 */
  contextLabel: string;
  /** 本轮消息附带的现场上下文（划选片段/练习代码与判题/题库作答） */
  scene: AssistantSceneContext | null;
  /** 从划线高亮打开时携带的标注（头部展示颜色/备注/定位/删除管理） */
  annotation?: Annotation | null;
  fontSize?: number;
  onClose: () => void;
  onJumpAnnotation?: (a: Annotation) => void;
  onColorChange?: (a: Annotation, c: AnnotationColor) => void;
  onNoteSave?: (a: Annotation, note: string) => void;
  onDeleteAnnotation?: (a: Annotation) => void;
}

const TOOL_STATUS: Record<string, string> = {
  run_sandbox_code: "⚙️ 助教正在沙箱中实测代码…",
  render_math_plot: "📐 助教正在绘制函数图像…",
  lookup_learned_section: "🔍 助教正在翻阅你学过的课程…",
  lookup_past_mistakes: "📖 助教正在翻查你的历史错题…",
  inspect_exercise: "🛠️ 助教正在查看题目信息…",
};

/** 引用标签跳转：/read/{docId}?section=… 与 /bank 等应用内路由直跳 */
function ReferenceChips({ refs }: { refs: AssistantReference[] }) {
  const navigate = useNavigate();
  if (refs.length === 0) return null;
  return (
    <div className="mb-1.5 flex flex-wrap gap-1.5">
      {refs.map((r, i) => (
        <button
          key={`${r.label}-${i}`}
          type="button"
          onClick={() => {
            if (r.href && r.href.startsWith("/")) navigate(r.href);
          }}
          title={r.href ? "点击跳转查看" : undefined}
          className="max-w-full truncate rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[0.78em] text-sky-700 transition hover:bg-sky-100 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-300 dark:hover:bg-sky-900/50"
        >
          🔗 {r.label}
        </button>
      ))}
    </div>
  );
}

export default function AssistantPanel({
  open,
  closing = false,
  contextType,
  contextId,
  contextLabel,
  scene,
  annotation = null,
  fontSize: propFontSize,
  onClose,
  onJumpAnnotation,
  onColorChange,
  onNoteSave,
  onDeleteAnnotation,
}: Props) {
  const queryClient = useQueryClient();
  const hlColors = useHlColors();
  const { fontSize: fallbackFontSize } = useFontSize("course");
  const currentFontSize = propFontSize ?? fallbackFontSize;

  const [input, setInput] = useState("");
  const [localMsgs, setLocalMsgs] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [streamErr, setStreamErr] = useState("");
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [turnPlots, setTurnPlots] = useState<string[]>([]);
  const [turnRefs, setTurnRefs] = useState<AssistantReference[]>([]);
  // 模型自主沙箱运行的一次性授权卡（v0.5.1 体检 P1）：后端挂起等待，超时/拒绝即跳过
  const [pendingConfirm, setPendingConfirm] = useState<{ name: string; seq: number } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  // 标注管理（仅阅读页划线入口）
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState(annotation?.note ?? "");
  const [currentColor, setCurrentColor] = useState<AnnotationColor>(annotation?.color ?? "yellow");
  const [confirmDel, setConfirmDel] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const sseAbortRef = useRef<AbortController | null>(null);
  // 会话随归属域幂等：contextType+contextId 变化即切换/创建对应连续会话
  const sessionKey = open ? `${contextType}:${contextId}` : "";

  const session = useQuery({
    queryKey: ["assistant-session", sessionKey],
    queryFn: () =>
      api.assistant.session({ context_type: contextType, context_id: contextId }),
    enabled: !!sessionKey,
    staleTime: Infinity,
    gcTime: 0,
  });
  const convId = session.data?.conversation_id ?? null;

  const { data: serverMsgs, isLoading } = useQuery({
    queryKey: ["assistant-conv", convId],
    queryFn: () => api.assistant.messages(convId as string),
    enabled: !!convId,
  });

  // 切换会话/标注时清空本地流式与乐观状态
  useEffect(() => {
    setLocalMsgs([]);
    setStreaming("");
    setStreamErr("");
    setToolStatus(null);
    setTurnPlots([]);
    setTurnRefs([]);
    setPendingConfirm(null);
    setNoteDraft(annotation?.note ?? "");
    setCurrentColor(annotation?.color ?? "yellow");
    setNoteOpen(false);
  }, [convId, annotation?.id]);

  useEffect(() => {
    return () => {
      sseAbortRef.current?.abort();
    };
  }, [convId]);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMsgs.length, isThinking, streaming, toolStatus, turnPlots.length, open]);

  const displayMsgs = useMemo(() => {
    const list = [...(serverMsgs ?? [])];
    const serverIds = new Set(list.map((m) => m.id));
    const serverUserContents = list.filter((m) => m.role === "user").map((m) => m.content.trim());
    const matched = new Set<number>();
    for (const lm of localMsgs) {
      // done 事件回传的 assistant 消息已带服务端 ID，服务端列表刷新后按 ID 去重
      if (serverIds.has(lm.id)) continue;
      if (lm.role === "user") {
        // 与服务端消息按内容 FIFO 配对去重（相同内容重复提问不被误吞）
        const idx = serverUserContents.findIndex((c, i) => c === lm.content.trim() && !matched.has(i));
        if (idx >= 0) {
          matched.add(idx);
          continue;
        }
      }
      list.push(lm);
    }
    return list;
  }, [serverMsgs, localMsgs]);

  const send = async () => {
    const content = input.trim();
    if (!content || !convId || streaming || isThinking) return;
    const tempId = `temp-user-${Date.now()}`;
    setLocalMsgs((prev) => [
      ...prev,
      { id: tempId, conversation_id: convId, role: "user", content, created_at: new Date().toISOString() },
    ]);
    setInput("");
    setStreamErr("");
    setIsThinking(true);
    setStreaming("");
    setTurnPlots([]);
    setTurnRefs([]);

    let acc = "";
    // 流式增量缓冲：delta 只进 flusher，120ms 批量刷新进 state，避免每 token 全量重渲染
    const flusher = createStreamFlusher((text) => setStreaming(text));
    sseAbortRef.current?.abort();
    const ctrl = new AbortController();
    sseAbortRef.current = ctrl;
    try {
      await api.assistant.streamSSE(
        convId,
        { content, scene: scene ?? undefined },
        (ev: AssistantSSEEvent) => {
          if (ev.type === "user_ack" && ev.message?.id) {
            const acked = ev.message.id;
            setLocalMsgs((prev) => prev.map((m) => (m.id === tempId ? { ...m, id: acked } : m)));
          } else if (ev.type === "tool_call" && ev.name) {
            if (ev.needs_confirm) {
              // 沙箱等敏感工具：后端已挂起等待授权，弹卡而非状态行
              setPendingConfirm({ name: ev.name, seq: ev.confirm_seq ?? 0 });
              return;
            }
            setToolStatus(TOOL_STATUS[ev.name] ?? `🛠️ 助教正在调用工具 ${ev.name}…`);
          } else if (ev.type === "tool_result") {
            // 授权卡要么已处理、要么超时被服务端跳过：一律收起
            setPendingConfirm(null);
            setToolStatus(null);
            const svg = ev.result?.svg;
            if (ev.name === "render_math_plot" && typeof svg === "string" && svg) {
              // 与 MarkdownLite 同一净化口径（v0.5.1 体检 P2）：SSE 事件里的 SVG 进 innerHTML 前剥脚本与 on*
              setTurnPlots((prev) => [...prev, sanitizeSvg(svg)]);
            }
          } else if (ev.type === "reference" && Array.isArray(ev.references)) {
            const refs: AssistantReference[] = ev.references;
            setTurnRefs((prev) => [...prev, ...refs]);
          } else if (ev.type === "delta" && ev.text) {
            setIsThinking(false);
            setToolStatus(null);
            acc += ev.text;
            flusher.push(acc);
          } else if (ev.type === "error") {
            flusher.flushNow();
            setIsThinking(false);
            setToolStatus(null);
            setStreamErr(ev.detail ?? "生成失败，请重试");
            if (!acc) setStreaming("");
          } else if (ev.type === "done") {
            flusher.cancel(); // 最终全文走 localMsgs 的 MarkdownLite 完整渲染
            const assistantText = acc || ev.content || "";
            if (assistantText) {
              setLocalMsgs((prev) => [
                ...prev,
                {
                  id: ev.message_id || `temp-asst-${Date.now()}`,
                  conversation_id: convId,
                  role: "assistant",
                  content: assistantText,
                  created_at: new Date().toISOString(),
                },
              ]);
            }
            setStreaming("");
            setIsThinking(false);
            setToolStatus(null);
            queryClient.invalidateQueries({ queryKey: ["assistant-conv", convId] });
          }
        },
        ctrl.signal
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        flusher.flushNow();
        setIsThinking(false);
        setToolStatus(null);
        setStreamErr(`网络错误：${(e as Error).message}`);
      }
    } finally {
      // 服务端干净关流但未发 done/error（如静默断连）时不能永久卡在思考态
      setIsThinking(false);
      setToolStatus(null);
    }
  };

  /** 落学员的沙箱授权决定（remember=true 后本会话内不再逐次询问） */
  const answerConfirm = async (approve: boolean, remember: boolean) => {
    if (!convId || !pendingConfirm || confirmBusy) return;
    setConfirmBusy(true);
    try {
      await api.assistant.confirmTool(convId, { approve, remember });
    } catch {
      /* 409（超时已被服务端跳过）等竞态：收起卡片即可 */
    }
    setPendingConfirm(null);
    setConfirmBusy(false);
  };

  const isVisible = open && !closing;

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 bg-white shadow-2xl transition-transform duration-300 ease-out sm:w-[440px] drawer-content-root ${
        isVisible ? "translate-x-0" : "translate-x-full"
      } dark:border-gray-700 dark:bg-gray-900`}
      style={{ "--course-font-size": `${currentFontSize}px` } as React.CSSProperties}
    >
      {/* 头部：场景标签 + 关闭 */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-800">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-base">🤖</span>
          <span className="drawer-title shrink-0 font-semibold text-gray-900 dark:text-gray-100">AI 助教</span>
          <span className="min-w-0 truncate rounded-full bg-brand-50 px-2 py-0.5 text-[0.78em] text-brand-700 dark:bg-brand-900/40 dark:text-brand-300">
            {contextLabel}
          </span>
        </div>
        <button onClick={onClose} className="shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" title="关闭">
          ✕
        </button>
      </div>

      {/* 划线管理头部（仅阅读页划线入口） */}
      {annotation && (
        <div className="shrink-0 border-b border-gray-100 bg-gray-50/50 px-4 py-3 dark:border-gray-800 dark:bg-gray-800/30">
          <div className="flex gap-2">
            <span className="w-1 shrink-0 rounded" style={{ backgroundColor: hlColors[currentColor] }} />
            <p className="line-clamp-5 flex-1 text-[0.92em] leading-relaxed text-gray-600 dark:text-gray-300">
              {annotation.exact}
            </p>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1 text-[0.85em]">
            {HL_COLOR_KEYS.map((c) => (
              <button
                key={c}
                onClick={() => {
                  setCurrentColor(c);
                  onColorChange?.(annotation, c);
                }}
                className={`h-3.5 w-3.5 rounded-full border transition-transform ${
                  currentColor === c ? "scale-110 ring-2 ring-brand-500 ring-offset-1" : "hover:scale-105"
                }`}
                style={{ backgroundColor: hlColors[c] }}
                title="更换颜色"
              />
            ))}
            {onJumpAnnotation && (
              <Button variant="ghost" className="ml-1 text-xs" onClick={() => onJumpAnnotation(annotation)}>
                📍 定位原文
              </Button>
            )}
            <Button variant="ghost" className="text-xs" onClick={() => setNoteOpen((v) => !v)}>
              📝 备注
            </Button>
            {onDeleteAnnotation && (
              <Button
                variant="ghost"
                className="ml-auto text-xs text-red-500 hover:text-red-600 dark:text-red-400"
                onClick={() => setConfirmDel(true)}
              >
                删除
              </Button>
            )}
          </div>
          {noteOpen && (
            <div className="mt-2">
              <Textarea
                rows={2}
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                placeholder="私有备注（不进入对话）"
                className="text-[0.9em]"
              />
              <div className="mt-1 text-right">
                <Button
                  variant="secondary"
                  className="text-xs"
                  onClick={() => {
                    onNoteSave?.(annotation, noteDraft);
                    setNoteOpen(false);
                  }}
                >
                  保存备注
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 对话区 */}
      <div className="flex-1 space-y-3 overflow-auto px-4 py-3">
        {session.isLoading && <Spinner className="mx-auto mt-8 h-5 w-5" />}
        {session.isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-center text-[0.85em] text-red-600 dark:border-red-800 dark:bg-red-950/40 dark:text-red-400">
            {(session.error as Error).message}
          </div>
        )}
        {!session.isLoading &&
          displayMsgs.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] rounded-xl px-3.5 py-2 leading-relaxed shadow-sm ${
                  m.role === "user"
                    ? "bg-brand-600 text-white"
                    : "border border-gray-200 bg-gray-50 text-gray-800 dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-200"
                }`}
              >
                {m.role === "user" ? (
                  <p className="whitespace-pre-wrap break-words text-[0.95em] leading-relaxed">{m.content}</p>
                ) : (
                  <div className="text-[0.95em] leading-relaxed">
                    <MarkdownLite text={m.content} />
                  </div>
                )}
              </div>
            </div>
          ))}

        {/* 沙箱授权卡：模型请求自主运行代码，须学员放行（v0.5.1 体检 P1） */}
        {pendingConfirm && (
          <div className="flex justify-start">
            <div className="max-w-[92%] rounded-xl border border-amber-300 bg-amber-50 p-3 shadow-sm dark:border-amber-700 dark:bg-amber-950/40">
              <p className="text-[0.9em] font-medium text-amber-800 dark:text-amber-200">
                ⚠️ AI 助教请求在沙箱中运行一段代码
              </p>
              <p className="mt-1 text-[0.82em] leading-relaxed text-gray-600 dark:text-gray-400">
                代码将在本地真实执行，经你授权后才会运行；3 分钟未确认将自动跳过。
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Button
                  className="bg-amber-600 text-white hover:bg-amber-700"
                  disabled={confirmBusy}
                  onClick={() => answerConfirm(true, false)}
                >
                  ▶ 仅这次运行
                </Button>
                <Button variant="secondary" disabled={confirmBusy} onClick={() => answerConfirm(true, true)}>
                  ✓ 本会话自动运行
                </Button>
                <Button variant="ghost" disabled={confirmBusy} onClick={() => answerConfirm(false, false)}>
                  跳过
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* 本轮来源引用标签（旧知/历史错题跳转）——回复结束后保留至下次提问（v0.5.1 体检 P2） */}
        {turnRefs.length > 0 && (
          <div className="flex justify-start">
            <ReferenceChips refs={turnRefs} />
          </div>
        )}
        {/* 本轮工具绘制的函数图像——回复结束后保留至下次提问（v0.5.1 体检 P2） */}
        {turnPlots.length > 0 && (
          <div className="flex justify-start">
            <div className="max-w-[95%] space-y-2">
              {turnPlots.map((svg, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-violet-100 bg-white p-2 dark:border-violet-900/50 dark:bg-gray-900/80 [&_svg]:h-auto [&_svg]:max-w-full"
                  dangerouslySetInnerHTML={{ __html: svg }}
                />
              ))}
            </div>
          </div>
        )}

        {/* 工具调用状态行 */}
        {toolStatus && (
          <div className="flex items-center gap-1.5 py-1 font-mono text-[0.85em] text-amber-600 dark:text-amber-300">
            <Spinner className="h-3 w-3 border-amber-400 border-t-transparent" />
            <span className="animate-pulse">{toolStatus}</span>
          </div>
        )}

        {/* AI 思考中动效 */}
        {isThinking && !streaming && !toolStatus && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3.5 py-2 text-[0.85em] text-gray-500 dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-400">
              <div className="flex items-center space-x-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500" style={{ animationDelay: "0ms" }} />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500" style={{ animationDelay: "150ms" }} />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-500" style={{ animationDelay: "300ms" }} />
              </div>
              <span>AI 助教正在思考解答…</span>
            </div>
          </div>
        )}

        {/* 流式打字机输出 */}
        {streaming && (
          <div className="flex justify-start">
            <div className="msg-md max-w-[90%] rounded-xl border border-gray-200 bg-gray-50 px-3.5 py-2 text-[0.95em] text-gray-800 shadow-sm dark:border-gray-700 dark:bg-gray-800/60 dark:text-gray-200">
              <MarkdownLite text={streaming} deferMath />
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-sm bg-brand-500 align-middle" />
            </div>
          </div>
        )}

        {streamErr && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-center text-[0.85em] text-red-600 dark:border-red-800 dark:bg-red-950/40 dark:text-red-400">
            {streamErr}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div className="shrink-0 border-t border-gray-100 bg-white p-3 dark:border-gray-800 dark:bg-gray-900">
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
          placeholder="向 AI 助教提问…（Enter 发送，Shift+Enter 换行）"
          disabled={!!streaming || isThinking || !convId}
          className="text-[0.92em]"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[0.78em] text-gray-400 dark:text-gray-500">
            {scene?.kind === "exercise"
              ? "已随附当前练习与你的作答 · Enter 发送"
              : scene?.kind === "bank"
              ? "已随附当前题目与你的作答 · Enter 发送"
              : scene?.kind === "reading"
              ? "已随附当前章节上下文 · Enter 发送"
              : "Enter 发送 / Shift+Enter 换行"}
          </span>
          <Button disabled={!input.trim() || !!streaming || isThinking || !convId} onClick={send}>
            {streaming || isThinking ? <Spinner className="border-white/40" /> : "发送"}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDel}
        title="删除标注"
        message="将删除该划线及其高亮与备注，对话记录保留在本章助教会话中，确定？"
        onCancel={() => setConfirmDel(false)}
        onConfirm={() => {
          setConfirmDel(false);
          if (annotation) onDeleteAnnotation?.(annotation);
          onClose();
        }}
      />
    </div>
  );
}
