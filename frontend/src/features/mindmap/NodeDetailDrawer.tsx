// 节点详情抽屉：面包屑层级定位、Markdown 知识深入剖析、AI Agent 针对性生成与多轮专属追问
import { useEffect, useMemo, useRef, useState } from "react";
import type { MindMapNode, MindMapNodeDetailSSEEvent, MindMapNodeQASSEEvent } from "../../lib/types";
import { api } from "../../lib/api";
import { Button, Spinner, Textarea } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";
import { useFontSize } from "../../lib/fontSize";

interface Props {
  mindmapId: string;
  rootNode: MindMapNode;
  nodeId: string | null;
  closing?: boolean;
  onClose: () => void;
  onNodeUpdate: (nodeId: string, updates: Partial<MindMapNode>) => void;
}

function findNodeInTree(node: MindMapNode, targetId: string): MindMapNode | null {
  if (node.id === targetId) return node;
  for (const c of node.children || []) {
    const f = findNodeInTree(c, targetId);
    if (f) return f;
  }
  return null;
}

function getNodePath(node: MindMapNode, targetId: string, current: string[] = []): string[] | null {
  const next = [...current, node.title];
  if (node.id === targetId) return next;
  for (const c of node.children || []) {
    const p = getNodePath(c, targetId, next);
    if (p) return p;
  }
  return null;
}

export default function NodeDetailDrawer({
  mindmapId,
  rootNode,
  nodeId,
  closing = false,
  onClose,
  onNodeUpdate,
}: Props) {
  const [mounted, setMounted] = useState(false);
  const { fontSize } = useFontSize("course");

  const targetNode = useMemo(() => {
    if (!nodeId) return null;
    return findNodeInTree(rootNode, nodeId);
  }, [rootNode, nodeId]);

  const breadcrumbs = useMemo(() => {
    if (!nodeId) return [];
    return getNodePath(rootNode, nodeId) || [];
  }, [rootNode, nodeId]);

  // 编辑态
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [summaryDraft, setSummaryDraft] = useState("");

  // AI 深度生成解析状态
  const [generatingDetail, setGeneratingDetail] = useState(false);
  const [genInstruction, setGenInstruction] = useState("");
  const [streamingDetailText, setStreamingDetailText] = useState("");
  const [detailErr, setDetailErr] = useState("");
  const detailAbortRef = useRef<AbortController | null>(null);

  // 专属追问状态
  const [qaInput, setQaInput] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaStreaming, setQaStreaming] = useState("");
  const [qaHistory, setQaHistory] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const qaAbortRef = useRef<AbortController | null>(null);
  const qaBottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 20);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (targetNode) {
      setTitleDraft(targetNode.title);
      setSummaryDraft(targetNode.summary || "");
      setIsEditingTitle(false);
      setStreamingDetailText("");
      setDetailErr("");
      setQaHistory([]);
      setQaStreaming("");
    }
  }, [targetNode?.id]);

  // 切换目标节点或卸载时中断进行中的流，防止节点 A 的解析串台写入节点 B
  useEffect(() => {
    return () => {
      detailAbortRef.current?.abort();
      qaAbortRef.current?.abort();
    };
  }, [targetNode?.id]);

  useEffect(() => {
    qaBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [qaHistory.length, qaStreaming]);

  // Esc 快捷键由 MindMapCanvasPage 统一处理（优先收起抽屉/Agent 面板），此处不再重复监听

  if (!targetNode || !nodeId) return null;

  const isVisible = mounted && !closing;

  // 触发 AI 深度生成
  const handleGenerateDetail = async () => {
    detailAbortRef.current?.abort();
    const ctrl = new AbortController();
    detailAbortRef.current = ctrl;

    setGeneratingDetail(true);
    setStreamingDetailText("");
    setDetailErr("");

    let acc = "";
    try {
      await api.mindmaps.nodeDetailSSE(
        mindmapId,
        nodeId,
        { instruction: genInstruction.trim() },
        (ev: MindMapNodeDetailSSEEvent) => {
          if (ev.type === "delta" && ev.text) {
            acc += ev.text;
            setStreamingDetailText(acc);
          } else if (ev.type === "done") {
            onNodeUpdate(nodeId, { detail: acc || ev.detail || "" });
            setStreamingDetailText("");
            setGeneratingDetail(false);
          } else if (ev.type === "error") {
            setDetailErr(ev.detail || "生成解析失败");
            setGeneratingDetail(false);
          }
        },
        ctrl.signal
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setDetailErr(err.message || "请求失败");
      }
    } finally {
      setGeneratingDetail(false);
    }
  };

  // 触发专属追问
  const handleSendQa = async () => {
    const q = qaInput.trim();
    if (!q || qaLoading) return;

    qaAbortRef.current?.abort();
    const ctrl = new AbortController();
    qaAbortRef.current = ctrl;

    setQaInput("");
    setQaLoading(true);
    setQaStreaming("");

    const newHist = [...qaHistory, { role: "user" as const, content: q }];
    setQaHistory(newHist);

    let acc = "";
    try {
      await api.mindmaps.nodeQASSE(
        mindmapId,
        nodeId,
        { question: q, history: qaHistory },
        (ev: MindMapNodeQASSEEvent) => {
          if (ev.type === "delta" && ev.text) {
            acc += ev.text;
            setQaStreaming(acc);
          } else if (ev.type === "done") {
            if (acc) {
              setQaHistory([...newHist, { role: "assistant", content: acc }]);
            }
            setQaStreaming("");
            setQaLoading(false);
          } else if (ev.type === "error") {
            setQaHistory([...newHist, { role: "assistant", content: "⚠️ 问答遇到异常，请稍后重试。" }]);
            setQaStreaming("");
            setQaLoading(false);
          }
        },
        ctrl.signal
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setQaHistory([...newHist, { role: "assistant", content: `⚠️ 连接错误: ${err.message}` }]);
      }
    } finally {
      setQaLoading(false);
      setQaStreaming("");
    }
  };

  const currentDetail = streamingDetailText || targetNode.detail;

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl sm:w-[480px] md:w-[520px] transition-transform duration-300 ease-out transform drawer-content-root ${
        isVisible ? "translate-x-0" : "translate-x-full"
      }`}
      style={{
        "--course-font-size": `${fontSize}px`,
      } as React.CSSProperties}
    >
      {/* 头部：面包屑定位与关闭按钮 */}
      <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3 shrink-0">
        <div className="flex items-center gap-1.5 overflow-hidden text-xs text-gray-500 dark:text-gray-400">
          <span className="shrink-0 text-brand-600 dark:text-brand-400 font-semibold">📍 节点详情</span>
          <span>·</span>
          <div className="truncate font-mono text-[11px]" title={breadcrumbs.join(" > ")}>
            {breadcrumbs.join(" > ")}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="ml-2 flex h-7 w-7 items-center justify-center rounded-md text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition"
          title="关闭 (Esc)"
        >
          ✕
        </button>
      </div>

      {/* 滚动容器 */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {/* 概念标题卡片 */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-700/80 bg-gray-50/60 dark:bg-gray-800/40 p-3.5">
          {isEditingTitle ? (
            <div className="space-y-2">
              <input
                type="text"
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                placeholder="概念名称"
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2.5 py-1 text-sm font-semibold text-gray-900 dark:text-gray-100 focus:outline-none focus:border-brand-500"
              />
              <input
                type="text"
                value={summaryDraft}
                onChange={(e) => setSummaryDraft(e.target.value)}
                placeholder="简明要点说明（可选）"
                className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2.5 py-1 text-xs text-gray-600 dark:text-gray-300 focus:outline-none focus:border-brand-500"
              />
              <div className="flex justify-end gap-1.5 pt-1">
                <Button
                  variant="ghost"
                  className="!px-2 !py-0.5 text-xs"
                  onClick={() => setIsEditingTitle(false)}
                >
                  取消
                </Button>
                <Button
                  className="!px-2.5 !py-0.5 text-xs"
                  onClick={() => {
                    onNodeUpdate(nodeId, {
                      title: titleDraft.trim() || targetNode.title,
                      summary: summaryDraft.trim(),
                    });
                    setIsEditingTitle(false);
                  }}
                >
                  保存
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-base font-bold text-gray-900 dark:text-gray-100">
                  {targetNode.title}
                </h2>
                <button
                  type="button"
                  onClick={() => setIsEditingTitle(true)}
                  className="text-xs text-gray-400 hover:text-brand-600 dark:hover:text-brand-400"
                  title="修改名称与摘要"
                >
                  ✏️
                </button>
              </div>
              {targetNode.summary ? (
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                  {targetNode.summary}
                </p>
              ) : (
                <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500 italic">
                  （暂无简明要点，可点击编辑添加）
                </p>
              )}
            </div>
          )}
        </div>

        {/* 详细知识点剖析板块 */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-700/80 bg-white dark:bg-gray-800/40 p-4 shadow-2xs space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-800 dark:text-gray-200">
              <span>📖</span>
              <span>深度知识点剖析</span>
            </div>
            <Button
              variant="secondary"
              className="!px-2.5 !py-1 text-xs font-medium text-brand-700 dark:text-brand-300 shadow-2xs"
              disabled={generatingDetail}
              onClick={handleGenerateDetail}
            >
              {generatingDetail ? (
                <>
                  <Spinner className="mr-1 h-3 w-3" /> 正在深度剖析…
                </>
              ) : currentDetail ? (
                "↻ 重新解析"
              ) : (
                "✨ AI Agent 深入生成"
              )}
            </Button>
          </div>

          {detailErr && (
            <div className="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 p-2 text-xs text-red-600 dark:text-red-400">
              {detailErr}
            </div>
          )}

          {currentDetail ? (
            <div className="msg-md text-xs leading-relaxed text-gray-800 dark:text-gray-200 bg-gray-50/50 dark:bg-gray-900/40 rounded-lg p-3 border border-gray-100 dark:border-gray-800">
              <MarkdownLite text={currentDetail} />
              {generatingDetail && (
                <span className="inline-block h-3.5 w-1.5 ml-0.5 align-middle bg-brand-500 animate-pulse rounded-sm" />
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-gray-200 dark:border-gray-700 p-6 text-center text-xs text-gray-400 dark:text-gray-500">
              <div className="text-2xl mb-1.5">💡</div>
              <p>该节点尚未沉淀详尽剖析文档</p>
              <p className="mt-1 text-[11px] text-gray-400">
                点击上方「AI Agent 深入生成」，系统将结合你的学习画像与认知特点，剖析核心定义、工作机制与直观类比。
              </p>
            </div>
          )}
        </div>

        {/* 专属节点问答互动区 */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-700/80 bg-white dark:bg-gray-800/40 p-4 shadow-2xs space-y-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-800 dark:text-gray-200">
            <span>💬</span>
            <span>关于「{targetNode.title}」专属问答</span>
          </div>

          <div className="space-y-2.5 max-h-72 overflow-y-auto pr-1">
            {qaHistory.length === 0 && !qaStreaming && (
              <p className="text-[11px] text-gray-400 dark:text-gray-500 italic py-2">
                对这个概念有什么卡点或疑问？随时在下方输入向伴学助教提问。
              </p>
            )}
            {qaHistory.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[90%] rounded-xl px-3 py-1.5 text-xs leading-relaxed ${
                    msg.role === "user"
                      ? "bg-brand-600 text-white"
                      : "border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 text-gray-800 dark:text-gray-200"
                  }`}
                >
                  {msg.role === "user" ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <MarkdownLite text={msg.content} />
                  )}
                </div>
              </div>
            ))}
            {qaStreaming && (
              <div className="flex justify-start">
                <div className="msg-md max-w-[90%] rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-3 py-1.5 text-xs text-gray-800 dark:text-gray-200">
                  <MarkdownLite text={qaStreaming} />
                  <span className="inline-block h-3 w-1.5 ml-0.5 align-middle bg-brand-500 animate-pulse rounded-sm" />
                </div>
              </div>
            )}
            <div ref={qaBottomRef} />
          </div>

          <div className="flex items-center gap-1.5 pt-1 border-t border-gray-100 dark:border-gray-800">
            <input
              type="text"
              value={qaInput}
              onChange={(e) => setQaInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendQa();
                }
              }}
              placeholder="就该概念向助教提问…"
              disabled={qaLoading}
              className="flex-1 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2.5 py-1 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
            />
            <Button
              className="!px-3 !py-1 text-xs"
              disabled={qaLoading || !qaInput.trim()}
              onClick={handleSendQa}
            >
              {qaLoading ? <Spinner className="h-3 w-3 border-white/40" /> : "提问"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
