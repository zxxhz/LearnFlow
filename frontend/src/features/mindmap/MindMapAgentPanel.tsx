// 导图伴学 Agent 面板：自然语言指令交互，驱动思维导图动态增删改查修剪
import { useEffect, useRef, useState } from "react";
import type { MindMapAgentSSEEvent, MindMapNode } from "../../lib/types";
import { api } from "../../lib/api";
import { Button, Spinner } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

interface Props {
  mindmapId: string;
  selectedNode: MindMapNode | null;
  onTreeUpdate: (newTree: MindMapNode) => void;
  closing?: boolean;
  onClose: () => void;
}

interface MessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions?: Array<{ name: string; args: any }>;
}

export default function MindMapAgentPanel({
  mindmapId,
  selectedNode,
  onTreeUpdate,
  closing = false,
  onClose,
}: Props) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 20);
    return () => clearTimeout(t);
  }, []);

  const [messages, setMessages] = useState<MessageItem[]>([
    {
      id: "init",
      role: "assistant",
      content:
        "你好！我是你的思维导图伴学 Agent。你可以直接用自然语言对我下达指令，例如：\n- 「在选中的分支下补充 3 个核心机制」\n- 「把过时的废弃技术分支删掉」\n- 「把导图结构展开得更深入更精细」\n- 「结合我的学习画像精简当前概念」",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [currentActions, setCurrentActions] = useState<Array<{ name: string; args: any }>>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streamingText, currentActions.length]);

  const handleSend = async (customPrompt?: string) => {
    const text = customPrompt || input.trim();
    if (!text || loading) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const userMsg: MessageItem = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setStreamingText("");
    setCurrentActions([]);

    let accText = "";
    const collectedActions: Array<{ name: string; args: any }> = [];

    try {
      await api.mindmaps.agentSSE(
        mindmapId,
        {
          message: text,
          selected_node_id: selectedNode?.id ?? null,
        },
        (ev: MindMapAgentSSEEvent) => {
          if (ev.type === "tool_call" && ev.name) {
            collectedActions.push({ name: ev.name, args: ev.args });
            setCurrentActions([...collectedActions]);
          } else if (ev.type === "tree_update" && ev.tree) {
            onTreeUpdate(ev.tree);
          } else if (ev.type === "delta" && ev.text) {
            accText += ev.text;
            setStreamingText(accText);
          } else if (ev.type === "done") {
            if (ev.tree) {
              onTreeUpdate(ev.tree);
            }
            setMessages((prev) => [
              ...prev,
              {
                id: `asst-${Date.now()}`,
                role: "assistant",
                content: accText || "已完成导图结构调整。",
                actions: collectedActions.length > 0 ? collectedActions : undefined,
              },
            ]);
            setStreamingText("");
            setCurrentActions([]);
            setLoading(false);
          } else if (ev.type === "error") {
            setMessages((prev) => [
              ...prev,
              {
                id: `err-${Date.now()}`,
                role: "assistant",
                content: `⚠️ Agent 执行遇到了问题：${ev.detail || "未知异常"}`,
              },
            ]);
            setStreamingText("");
            setCurrentActions([]);
            setLoading(false);
          }
        },
        ctrl.signal
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "assistant",
            content: `⚠️ 连接错误: ${err.message}`,
          },
        ]);
      }
    } finally {
      setLoading(false);
      setStreamingText("");
      setCurrentActions([]);
    }
  };

  const getActionLabel = (act: { name: string; args: any }) => {
    if (act.name === "add_nodes") {
      const count = act.args?.nodes?.length || 1;
      return `➕ Agent 新增了 ${count} 个概念分支`;
    }
    if (act.name === "delete_nodes") {
      const count = act.args?.node_ids?.length || 1;
      return `🗑️ Agent 修剪了 ${count} 个分支`;
    }
    if (act.name === "update_node") {
      return `✏️ Agent 重命名/更新了节点概念`;
    }
    if (act.name === "expand_branch") {
      return `🔍 Agent 深度展开了分支子概念`;
    }
    return `⚙️ Agent 优化了导图结构`;
  };

  const isVisible = mounted && !closing;

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-full w-full sm:w-[380px] md:w-[420px] flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl transition-transform duration-300 ease-out transform ${
        isVisible ? "translate-x-0" : "translate-x-full"
      }`}
    >
      {/* 头部 */}
      <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-lg">🧠</span>
          <div>
            <div className="text-sm font-bold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
              <span>导图伴学 Agent</span>
              <span className="rounded bg-brand-50 dark:bg-brand-950/40 border border-brand-200 dark:border-brand-800/60 px-1 py-0.2 text-[10px] text-brand-700 dark:text-brand-300 font-medium">
                Active
              </span>
            </div>
            {selectedNode && (
              <p className="text-[10px] text-gray-400 dark:text-gray-500 truncate max-w-[220px]">
                当前焦点：{selectedNode.title}
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
          title="收起 Agent 面板"
        >
          ✕
        </button>
      </div>

      {/* 快捷推荐指令条 */}
      <div className="flex items-center gap-1.5 overflow-x-auto px-3 py-2 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/30 text-[11px] shrink-0 no-scrollbar">
        <button
          type="button"
          disabled={loading}
          onClick={() => handleSend(selectedNode ? `围绕「${selectedNode.title}」深入拆解 2 级核心机制` : "围绕主要核心机制进一步深入拆解")}
          className="rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-2.5 py-0.5 text-gray-600 dark:text-gray-300 hover:border-brand-500 hover:text-brand-600 shrink-0 transition"
        >
          🔍 深度拆解
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => handleSend("帮我精简合并当前思维导图，去除冗余分支")}
          className="rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-2.5 py-0.5 text-gray-600 dark:text-gray-300 hover:border-brand-500 hover:text-brand-600 shrink-0 transition"
        >
          ✂️ 精简分支
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => handleSend("根据我的学习认知画像，补充易混淆的对比分支")}
          className="rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-2.5 py-0.5 text-gray-600 dark:text-gray-300 hover:border-brand-500 hover:text-brand-600 shrink-0 transition"
        >
          🧑‍🎓 画像适配
        </button>
      </div>

      {/* 对话消息区 */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-xs">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[90%] rounded-xl px-3.5 py-2 leading-relaxed ${
                m.role === "user"
                  ? "bg-brand-600 text-white shadow-xs"
                  : "border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/60 text-gray-800 dark:text-gray-200 shadow-xs"
              }`}
            >
              {m.actions && m.actions.length > 0 && (
                <div className="mb-2 space-y-1">
                  {m.actions.map((act, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded bg-brand-50 dark:bg-brand-950/60 border border-brand-200 dark:border-brand-800/60 px-2 py-0.5 text-[10px] text-brand-700 dark:text-brand-300 font-medium mr-1.5 mb-1"
                    >
                      {getActionLabel(act)}
                    </span>
                  ))}
                </div>
              )}
              {m.role === "user" ? (
                <p className="whitespace-pre-wrap">{m.content}</p>
              ) : (
                <div className="msg-md">
                  <MarkdownLite text={m.content} />
                </div>
              )}
            </div>
          </div>
        ))}

        {/* 正在执行的动态工具操作回显 */}
        {currentActions.length > 0 && (
          <div className="flex justify-start">
            <div className="space-y-1">
              {currentActions.map((act, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1.5 rounded-lg border border-brand-200 dark:border-brand-800 bg-brand-50/70 dark:bg-brand-950/40 px-3 py-1.5 text-[11px] text-brand-700 dark:text-brand-300 animate-pulse font-mono"
                >
                  <Spinner className="h-3 w-3 border-brand-600" />
                  <span>{getActionLabel(act)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 流式文本打字机 */}
        {streamingText && (
          <div className="flex justify-start">
            <div className="msg-md max-w-[90%] rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-3.5 py-2 leading-relaxed text-gray-800 dark:text-gray-200 shadow-xs">
              <MarkdownLite text={streamingText} />
              <span className="inline-block h-3.5 w-1.5 ml-0.5 align-middle bg-brand-500 animate-pulse rounded-sm" />
            </div>
          </div>
        )}

        {loading && !streamingText && currentActions.length === 0 && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-3 py-2 text-gray-500 dark:text-gray-400">
              <Spinner className="h-3.5 w-3.5" />
              <span>Agent 正在分析导图上下文并规划调整…</span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* 底部输入框 */}
      <div className="border-t border-gray-100 dark:border-gray-800 p-3 bg-white dark:bg-gray-900 shrink-0">
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={
              selectedNode
                ? `针对「${selectedNode.title}」下达修改指令…`
                : "用自然语言对导图下达增删改指令…"
            }
            disabled={loading}
            className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
          />
          <Button
            className="!px-3 !py-1.5 text-xs font-semibold"
            disabled={loading || !input.trim()}
            onClick={() => handleSend()}
          >
            {loading ? <Spinner className="h-3 w-3 border-white/40" /> : "执行"}
          </Button>
        </div>
        <p className="mt-1.5 text-[10px] text-gray-400 dark:text-gray-500 text-center">
          支持模糊语义，如“把网络模型展开到物理层”、“添加常见握手失败原因”
        </p>
      </div>
    </div>
  );
}
