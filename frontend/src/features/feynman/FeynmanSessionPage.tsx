// 费曼会话页：追问对话 → 评价 → 漏洞闭环（PRD §10.2 / FR-4.3）
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { streamSSE } from "../../lib/sse";
import type { ChatSSEEvent, Message } from "../../lib/types";
import { Badge, Button, Spinner, Textarea } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

const SEVERITY: Record<string, { label: string; color: "red" | "amber" | "gray" }> = {
  high: { label: "严重", color: "red" },
  medium: { label: "中等", color: "amber" },
  low: { label: "轻微", color: "gray" },
};

function GapItem({ desc, severity, sectionId, documentId }: {
  desc: string;
  severity: string;
  sectionId: string | null;
  documentId: string;
}) {
  const [cardMade, setCardMade] = useState(false);
  const sev = SEVERITY[severity] ?? SEVERITY.medium;
  return (
    <li className="flex items-start justify-between gap-3 rounded-lg border border-gray-200 p-3">
      <div className="min-w-0">
        <Badge color={sev.color}>{sev.label}</Badge>
        <p className="mt-1 text-sm text-gray-700">{desc}</p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        {sectionId && (
          <Link to={`/read/${documentId}?section=${sectionId}`} className="text-xs text-brand-600 underline">
            查看原文
          </Link>
        )}
        <Button
          variant={cardMade ? "secondary" : "ghost"}
          className="text-xs"
          disabled={cardMade}
          onClick={() =>
            api.review
              .createCard({
                front: `讲解一下：${desc.slice(0, 50)}`,
                back: `费曼讲解中暴露的漏洞：${desc}。回到文档对应位置重新学习。`,
              })
              .then(() => setCardMade(true))
          }
        >
          {cardMade ? "已生成 ✓" : "生成复习卡"}
        </Button>
      </div>
    </li>
  );
}

export default function FeynmanSessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState("");
  const [streamErr, setStreamErr] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: session, isLoading } = useQuery({
    queryKey: ["feynman", sessionId],
    queryFn: () => api.feynman.get(sessionId!),
    enabled: !!sessionId,
  });
  const { data: ctx } = useQuery({
    queryKey: ["kp-ctx", session?.knowledge_point_id],
    queryFn: () => api.feynman.kpContext(session!.knowledge_point_id),
    enabled: !!session,
  });
  const { data: prefs } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });

  const evaluate = useMutation({
    mutationFn: () => api.feynman.evaluate(sessionId!),
    onMutate: () => setEvaluating(true),
    onSettled: () => setEvaluating(false),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["feynman", sessionId] }),
  });

  const send = async () => {
    const content = input.trim();
    if (!content || streaming || !session) return;
    setInput("");
    setStreamErr("");
    const optimistic: Message = {
      id: `tmp-${Date.now()}`,
      conversation_id: session.conversation_id,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    let acc = "";
    setStreaming("");
    try {
      await streamSSE(
        `/conversations/${session.conversation_id}/messages`,
        { content },
        (ev: ChatSSEEvent) => {
          if (ev.type === "delta" && ev.text) {
            acc += ev.text;
            setStreaming(acc);
          } else if (ev.type === "done") {
            setStreaming("");
            queryClient.invalidateQueries({ queryKey: ["feynman", sessionId] });
            if (ev.suggest_evaluate) {
              // 达到最大轮数 → 自动评价（PRD FR-4.2）
              evaluate.mutate();
            }
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length, streaming]);

  if (isLoading || !session) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const maxRounds = prefs?.preferences.feynman_max_rounds;
  const done = session.status === "done" && session.evaluation;

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col p-8">
      <div className="flex items-start justify-between gap-3">
        <div>
          <Link to="/feynman" className="text-sm text-gray-500 hover:text-brand-600">
            ← 费曼讲解
          </Link>
          <h1 className="mt-2 text-xl font-bold text-gray-900">
            {ctx?.knowledge_point.title ?? "费曼讲解"}
          </h1>
          {ctx && (
            <p className="mt-0.5 text-xs text-gray-400">
              来自《{ctx.course_title}》·{" "}
              <Link to={`/read/${ctx.document_id}`} className="underline">
                {ctx.document_title}
              </Link>
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-gray-500">
          {maxRounds && !done && <span>第 {Math.min(session.round_count + 1, maxRounds)}/{maxRounds} 轮</span>}
          <Badge color={done ? "green" : "blue"}>{done ? "已完成" : "进行中"}</Badge>
        </div>
      </div>

      {evaluating && (
        <div className="mt-6 flex items-center justify-center gap-3 rounded-xl border border-amber-200 bg-amber-50 py-8 text-sm text-amber-700">
          <Spinner /> 正在生成评价…
        </div>
      )}

      {done && session.evaluation ? (
        <div className="mt-6 space-y-4">
          <div className="flex items-center gap-4 rounded-xl border border-gray-200 bg-white p-5">
            <div
              className={`text-4xl font-bold ${
                session.evaluation.score >= 85
                  ? "text-green-600"
                  : session.evaluation.score >= 60
                    ? "text-amber-600"
                    : "text-red-600"
              }`}
            >
              {session.evaluation.score}
            </div>
            <div className="text-sm text-gray-600">
              {session.evaluation.score >= 85
                ? "讲得很清楚，已经真正理解了。"
                : session.evaluation.score >= 60
                  ? "基本掌握，还有细节需要补。"
                  : "需要回到文档重新学习这个知识点。"}
            </div>
          </div>

          {session.evaluation.strengths.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-gray-900">✓ 讲得好的地方</h3>
              <ul className="mt-2 space-y-1">
                {session.evaluation.strengths.map((s, i) => (
                  <li key={i} className="text-sm text-gray-700">
                    <span className="mr-1 text-green-600">✓</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {session.evaluation.gaps.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900">理解漏洞（{session.evaluation.gaps.length}）</h3>
                <Button
                  variant="ghost"
                  className="text-xs"
                  onClick={() => {
                    for (const g of session.evaluation!.gaps) {
                      api.review
                        .createCard({
                          front: `讲解一下：${g.desc.slice(0, 50)}`,
                          back: `费曼讲解中暴露的漏洞：${g.desc}。回到文档对应位置重新学习。`,
                        })
                        .catch(() => {});
                    }
                  }}
                >
                  全部生成复习卡
                </Button>
              </div>
              <ul className="mt-2 space-y-2">
                {session.evaluation.gaps.map((g, i) => (
                  <GapItem
                    key={i}
                    desc={g.desc}
                    severity={g.severity}
                    sectionId={g.section_id}
                    documentId={session.document_id}
                  />
                ))}
              </ul>
            </div>
          )}

          {session.evaluation.advice && (
            <div className="rounded-xl border-l-4 border-brand-300 bg-brand-50/50 p-4 text-sm text-gray-700">
              💡 {session.evaluation.advice}
            </div>
          )}

          <Link to={`/feynman?kp=${session.knowledge_point_id}`}>
            <Button variant="secondary">🔁 再讲一遍</Button>
          </Link>
        </div>
      ) : (
        <>
          <div className="mt-4 flex-1 space-y-3 overflow-auto pb-4">
            {session.messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-xl px-4 py-2.5 ${
                    m.role === "user" ? "bg-brand-600 text-white" : "border border-gray-200 bg-white"
                  }`}
                >
                  {m.role === "user" ? (
                    <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                  ) : (
                    <MarkdownLite text={m.content} />
                  )}
                </div>
              </div>
            ))}
            {streaming && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-xl border border-gray-200 bg-white px-4 py-2.5">
                  <MarkdownLite text={streaming} />
                  <Spinner className="ml-1 inline-block h-3 w-3" />
                </div>
              </div>
            )}
            {streamErr && <p className="text-sm text-red-600">{streamErr}</p>}
            <div ref={bottomRef} />
          </div>

          <div className="mt-3 rounded-xl border border-gray-200 bg-white p-3">
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
              placeholder="回答学生的问题…（Enter 发送，Shift+Enter 换行）"
              disabled={!!streaming || evaluating}
            />
            <div className="mt-2 flex items-center justify-between">
              <Button
                variant="ghost"
                className="text-xs"
                disabled={evaluating || evaluate.isPending}
                onClick={() => {
                  if (confirm("结束追问并生成评价？")) evaluate.mutate();
                }}
              >
                请求评价
              </Button>
              <Button disabled={!input.trim() || !!streaming || evaluating} onClick={send}>
                回答
              </Button>
            </div>
            {evaluate.isError && <p className="mt-1 text-xs text-red-600">{evaluate.error.message}</p>}
          </div>
        </>
      )}
    </div>
  );
}
