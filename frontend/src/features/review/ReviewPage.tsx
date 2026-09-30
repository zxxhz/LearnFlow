// 复习页：今日队列 + 四档自评（SM-2）+ 统计（PRD FR-5.2 / §10.1）
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { ReviewCard } from "../../lib/types";
import { Badge, Button, ConfirmDialog, EmptyState, Modal, Spinner, Textarea } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

const SOURCE_LABEL: Record<string, string> = {
  knowledge_point: "知识点",
  annotation: "划线",
  feynman_gap: "费曼漏洞",
  manual: "手动",
};

const STATE_LABEL: Record<string, { label: string; color: "gray" | "blue" | "green" | "amber" }> = {
  new: { label: "新卡", color: "blue" },
  learning: { label: "学习中", color: "amber" },
  review: { label: "复习中", color: "green" },
  relearning: { label: "重学", color: "amber" },
};

const GRADES = [
  { q: 1 as const, label: "忘了", hint: "10分钟后再来", cls: "bg-red-600 hover:bg-red-700" },
  { q: 3 as const, label: "模糊", hint: "明天再来", cls: "bg-amber-500 hover:bg-amber-600" },
  { q: 4 as const, label: "记得", hint: "按间隔延长", cls: "bg-blue-600 hover:bg-blue-700" },
  { q: 5 as const, label: "轻松", hint: "间隔拉更长", cls: "bg-green-600 hover:bg-green-700" },
];

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const { data: queue, isLoading } = useQuery({ queryKey: ["review-queue"], queryFn: api.review.queueToday });
  const { data: stats } = useQuery({ queryKey: ["review-stats"], queryFn: api.review.stats });

  // 本地队列：忘了的卡 push 到队尾（当天重现，PRD FR-5.2）
  const [localQueue, setLocalQueue] = useState<ReviewCard[] | null>(null);
  const [idx, setIdx] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [editing, setEditing] = useState<ReviewCard | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<ReviewCard | null>(null);

  const cards = localQueue ?? queue?.cards ?? null;
  const current = cards && idx < cards.length ? cards[idx] : null;

  const grade = useMutation({
    mutationFn: ({ card, q }: { card: ReviewCard; q: 1 | 3 | 4 | 5 }) => api.review.grade(card.id, q),
    onSuccess: (updated, { q }) => {
      setRevealed(false);
      queryClient.invalidateQueries({ queryKey: ["review-stats"] });
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      // 从队列移除当前卡后，idx 原地即指向下一张；忘了的卡追加到队尾（当天重现）
      setLocalQueue((prev) => {
        const base = prev ?? queue?.cards ?? [];
        const rest = base.filter((c) => c.id !== updated.id);
        return q === 1 ? [...rest, updated] : rest;
      });
    },
  });

  const maxBars = useMemo(
    () => Math.max(1, ...(stats?.due_next_7_days.map((d) => d.count) ?? [1])),
    [stats]
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const finished = !current;

  return (
    <div className="mx-auto max-w-3xl p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">复习</h1>
        <div className="flex items-center gap-3">
          {stats && (
            <span className="text-sm text-gray-500">
              今日已复习 {stats.today_reviewed} · 剩余{" "}
              {queue ? queue.due_total + queue.new_quota_remaining : stats.due_remaining} · 连续{" "}
              {stats.streak_days} 天
            </span>
          )}
          <Button variant="secondary" className="text-xs" onClick={() => setCreating(true)}>
            ＋ 新建卡片
          </Button>
        </div>
      </div>

      {finished ? (
        <div>
          <EmptyState
            icon="🎉"
            title={cards && cards.length > 0 ? "这一轮复习完成！" : "没有到期的卡片"}
            hint="复习队列每天更新；新学章节的知识点会自动进入队列"
            action={
              <Button
                className="mt-3"
                variant="secondary"
                onClick={() => {
                  setLocalQueue(null);
                  setIdx(0);
                  queryClient.invalidateQueries({ queryKey: ["review-queue"] });
                }}
              >
                刷新队列
              </Button>
            }
          />
          {stats && (
            <div className="mt-6 rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-gray-900">统计</h2>
              <div className="mt-3 grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-2xl font-bold text-gray-900">{stats.total_reviews}</div>
                  <div className="text-xs text-gray-500">累计复习</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-gray-900">{stats.total_cards}</div>
                  <div className="text-xs text-gray-500">复习卡总数</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-gray-900">{stats.streak_days}</div>
                  <div className="text-xs text-gray-500">连续打卡</div>
                </div>
              </div>
              <h3 className="mt-4 text-xs font-medium text-gray-500">未来 7 天到期</h3>
              <div className="mt-2 flex h-20 items-end gap-2">
                {stats.due_next_7_days.map((d) => (
                  <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                    <div
                      className="w-full rounded-t bg-brand-500/80"
                      style={{ height: `${(d.count / maxBars) * 60}px` }}
                      title={`${d.date}：${d.count} 张`}
                    />
                    <span className="text-[10px] text-gray-400">{d.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        current && (
          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
              <span>
                {idx + 1} / {cards!.length}
              </span>
              <div className="flex items-center gap-2">
                <Badge color="gray">{SOURCE_LABEL[current.source_type] ?? "手动"}</Badge>
                <Badge color={STATE_LABEL[current.state]?.color ?? "gray"}>
                  {STATE_LABEL[current.state]?.label ?? current.state}
                </Badge>
                <button className="underline hover:text-gray-600" onClick={() => setEditing(current)}>
                  编辑
                </button>
                <button className="underline hover:text-gray-600" onClick={() => setConfirmDelete(current)}>
                  删除
                </button>
              </div>
            </div>

            <div className="min-h-[240px] rounded-2xl border border-gray-200 bg-white p-8">
              <div className="text-lg font-medium text-gray-900">
                <MarkdownLite text={current.front} />
              </div>
              {revealed ? (
                <div className="mt-6 border-t border-gray-100 pt-6">
                  {current.back ? (
                    <MarkdownLite text={current.back} />
                  ) : (
                    <p className="text-sm text-gray-400">（无背面内容）</p>
                  )}
                </div>
              ) : (
                <Button className="mt-8" onClick={() => setRevealed(true)}>
                  显示答案
                </Button>
              )}
            </div>

            {revealed && (
              <div className="mt-4 grid grid-cols-4 gap-2">
                {GRADES.map((g) => (
                  <button
                    key={g.q}
                    disabled={grade.isPending}
                    onClick={() => grade.mutate({ card: current, q: g.q })}
                    className={`rounded-xl px-3 py-3 text-sm font-medium text-white transition disabled:opacity-50 ${g.cls}`}
                  >
                    <div>{g.label}</div>
                    <div className="mt-0.5 text-[10px] font-normal opacity-80">{g.hint}</div>
                  </button>
                ))}
              </div>
            )}
            {grade.isError && <p className="mt-2 text-sm text-red-600">{grade.error.message}</p>}
          </div>
        )
      )}

      {/* 编辑卡片 */}
      {editing && <EditCardModal card={editing} onClose={() => setEditing(null)} />}

      {/* 手工新建卡片（PRD FR-5.1） */}
      {creating && <CreateCardModal onClose={() => setCreating(false)} />}

      <ConfirmDialog
        open={!!confirmDelete}
        title="删除复习卡"
        message="删除后该卡的复习记录也将删除，确定？"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          if (confirmDelete) {
            api.review.deleteCard(confirmDelete.id).then(() => {
              setLocalQueue((prev) => (prev ?? queue?.cards ?? []).filter((c) => c.id !== confirmDelete.id));
              setConfirmDelete(null);
              queryClient.invalidateQueries({ queryKey: ["review-queue"] });
            });
          }
        }}
      />
    </div>
  );
}

function CreateCardModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  const create = useMutation({
    mutationFn: () => api.review.createCard({ front: front.trim(), back: back.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      queryClient.invalidateQueries({ queryKey: ["review-stats"] });
      onClose();
    },
  });
  return (
    <Modal open onClose={onClose} title="新建复习卡">
      <label className="mb-1 block text-xs font-medium text-gray-500">
        正面（问题）<span className="text-red-500">*</span>
      </label>
      <Textarea
        rows={2}
        value={front}
        onChange={(e) => setFront(e.target.value)}
        placeholder="如：std::vector 扩容时会发生什么？"
        autoFocus
      />
      <label className="mb-1 mt-3 block text-xs font-medium text-gray-500">背面（答案）</label>
      <Textarea
        rows={4}
        value={back}
        onChange={(e) => setBack(e.target.value)}
        placeholder="答案要点（支持 Markdown 与 $公式$）"
      />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          取消
        </Button>
        <Button disabled={create.isPending || !front.trim()} onClick={() => create.mutate()}>
          创建
        </Button>
      </div>
      {create.isError && <p className="mt-2 text-sm text-red-600">{create.error.message}</p>}
    </Modal>
  );
}

function EditCardModal({ card, onClose }: { card: ReviewCard; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [front, setFront] = useState(card.front);
  const [back, setBack] = useState(card.back);
  const save = useMutation({
    mutationFn: (suspended?: boolean) =>
      api.review.updateCard(card.id, { front, back, ...(suspended === undefined ? {} : { suspended }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      onClose();
    },
  });
  return (
    <Modal open onClose={onClose} title="编辑复习卡">
      <label className="mb-1 block text-xs font-medium text-gray-500">正面（问题）</label>
      <Textarea rows={2} value={front} onChange={(e) => setFront(e.target.value)} />
      <label className="mb-1 mt-3 block text-xs font-medium text-gray-500">背面（答案）</label>
      <Textarea rows={4} value={back} onChange={(e) => setBack(e.target.value)} />
      <div className="mt-4 flex items-center justify-between">
        <Button
          variant="ghost"
          className="text-xs"
          onClick={() => save.mutate(!card.suspended)}
        >
          {card.suspended ? "恢复卡片" : "暂停这张卡"}
        </Button>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button disabled={save.isPending || !front.trim()} onClick={() => save.mutate()}>
            保存
          </Button>
        </div>
      </div>
      {save.isError && <p className="mt-2 text-sm text-red-600">{save.error.message}</p>}
    </Modal>
  );
}
