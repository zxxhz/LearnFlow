// 大纲编辑器：章节增删/排序/编辑要点，保存后开始生成（PRD FR-1.2）
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Course, OutlineItem } from "../../lib/types";
import { Button, Input, Modal, Spinner, Textarea } from "../../components/ui";

interface Props {
  course: Course;
}

export default function OutlineEditor({ course }: Props) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<OutlineItem[]>(() =>
    course.outline.map((o, i) => ({ ...o, index: i + 1 }))
  );
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenInstruction, setRegenInstruction] = useState("");
  const [error, setError] = useState("");

  const update = (i: number, patch: Partial<OutlineItem>) =>
    setItems((prev) => prev.map((it, k) => (k === i ? { ...it, ...patch } : it)));

  const move = (i: number, dir: -1 | 1) =>
    setItems((prev) => {
      const j = i + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  const save = useMutation({
    mutationFn: async (thenGenerate: boolean) => {
      const normalized = items
        .filter((it) => it.title.trim())
        .map((it, i) => ({ index: i + 1, title: it.title.trim(), points: it.points.filter((p) => p.trim()) }));
      if (normalized.length === 0) throw new Error("至少需要一个章节");
      await api.courses.saveOutline(course.id, normalized);
      if (thenGenerate) await api.courses.generate(course.id);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["course", course.id] }),
    onError: (e) => setError(e.message),
  });

  const regenerate = useMutation({
    mutationFn: () =>
      // AI 重新生成：创建新草稿（原草稿保留），指令并入 scope（M1 简化实现）
      api.courses.create({
        topic: course.topic,
        level: course.level,
        scope: [course.scope, regenInstruction.trim()].filter(Boolean).join("；") || null,
        chapter_count: course.outline.length || null,
      }),
    onSuccess: (res) => {
      setRegenOpen(false);
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      window.location.assign(`/courses/${res.course.id}`);
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={save.isPending}
          onClick={() => {
            setError("");
            save.mutate(false);
          }}
          variant="secondary"
        >
          保存大纲
        </Button>
        <Button
          disabled={save.isPending}
          onClick={() => {
            setError("");
            save.mutate(true);
          }}
        >
          {save.isPending ? (
            <>
              <Spinner className="border-white/40" /> 处理中…
            </>
          ) : (
            "保存并开始生成文档"
          )}
        </Button>
        <Button variant="ghost" onClick={() => setRegenOpen(true)}>
          🔄 AI 重新生成大纲
        </Button>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      <div className="space-y-3">
        {items.map((it, i) => (
          <div key={i} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
            <div className="flex items-center gap-2">
              <span className="w-6 text-center text-sm font-semibold text-gray-400 dark:text-gray-500">{i + 1}</span>
              <Input
                value={it.title}
                onChange={(e) => update(i, { title: e.target.value })}
                placeholder="章标题"
              />
              <Button variant="ghost" title="上移" onClick={() => move(i, -1)}>
                ↑
              </Button>
              <Button variant="ghost" title="下移" onClick={() => move(i, 1)}>
                ↓
              </Button>
              <Button
                variant="ghost"
                title="删除本章"
                onClick={() => setItems((prev) => prev.filter((_, k) => k !== i))}
              >
                🗑
              </Button>
            </div>
            <Textarea
              className="mt-2"
              rows={3}
              value={it.points.join("\n")}
              onChange={(e) => update(i, { points: e.target.value.split("\n") })}
              placeholder="本章要点，一行一个"
            />
          </div>
        ))}
      </div>
      <Button variant="secondary" onClick={() => setItems((prev) => [...prev, { index: prev.length + 1, title: "", points: [] }])}>
        ＋ 添加章节
      </Button>

      <Modal open={regenOpen} onClose={() => setRegenOpen(false)} title="AI 重新生成大纲">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          将基于同一主题创建<strong>一个新的课程草稿</strong>（当前草稿保留）。可附加调整指令：
        </p>
        <Textarea
          className="mt-2"
          rows={3}
          value={regenInstruction}
          onChange={(e) => setRegenInstruction(e.target.value)}
          placeholder="如：多加练习章节 / 推导再详细一些 / 压缩到 6 章"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRegenOpen(false)}>
            取消
          </Button>
          <Button disabled={regenerate.isPending} onClick={() => regenerate.mutate()}>
            {regenerate.isPending ? "生成中…" : "重新生成"}
          </Button>
        </div>
        {regenerate.isError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{regenerate.error.message}</p>}
      </Modal>
    </div>
  );
}
