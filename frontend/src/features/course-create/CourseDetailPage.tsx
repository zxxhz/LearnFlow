// 课程详情：草稿态=大纲编辑器；生成态=章节进度（SSE 实时刷新）（PRD FR-1.3）
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { subscribeSSE } from "../../lib/sse";
import type { ChapterProgress, ProgressSSEEvent } from "../../lib/types";
import { Badge, Button, ConfirmDialog, DropdownMenu, EmptyState, ErrorText, Input, Modal, Spinner } from "../../components/ui";
import OutlineEditor from "./OutlineEditor";
import CourseAskPanel from "./CourseAskPanel";

const DOC_STATUS: Record<string, { label: string; color: "gray" | "green" | "blue" | "red" | "amber" }> = {
  pending: { label: "待生成", color: "gray" },
  generating: { label: "生成中", color: "blue" },
  done: { label: "完成", color: "green" },
  failed: { label: "失败", color: "red" },
};

/** 生成思维导图弹窗：深度选择 + 是否包含章节摘要与知识点 */
function MindMapGenModal({
  open,
  courseId,
  courseTitle,
  doneCount,
  onClose,
}: {
  open: boolean;
  courseId: string;
  courseTitle: string;
  doneCount: number;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [depth, setDepth] = useState(3);
  const [includeDetails, setIncludeDetails] = useState(true);
  const [error, setError] = useState("");

  const gen = useMutation({
    mutationFn: () =>
      api.mindmaps.generate({ course_id: courseId, depth, prompt: "", include_details: includeDetails }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
      onClose();
      navigate(`/mindmap/${res.id}`);
    },
    onError: (e) => setError((e as Error).message),
  });

  // 生成中禁止关闭 Modal（取消按钮不显示、Esc/遮罩无效）：
  // 请求无 AbortSignal，关闭后成功仍会强制跳转、错误无人可见
  const handleClose = () => {
    if (!gen.isPending) onClose();
  };

  return (
    <Modal open={open} onClose={handleClose} title={`🧠 为「${courseTitle}」生成思维导图`}>
      <div className="space-y-4 text-xs">
        <div className="rounded-lg bg-brand-50/60 dark:bg-brand-950/30 p-3 border border-brand-200/80 dark:border-brand-900/60 text-brand-800 dark:text-brand-300 leading-relaxed">
          基于课程大纲{includeDetails && doneCount > 0 ? "、各章内容摘要与核心知识点" : ""}自动构建知识导图：
          一级分支对应章节，逐层展开要点与概念，生成后可继续用导图 Agent 对话式增删改。
        </div>

        <div>
          <div className="mb-1.5 font-medium text-gray-700 dark:text-gray-300">导图层级深度</div>
          <div className="flex items-center gap-2">
            {[2, 3, 4].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDepth(d)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                  depth === d
                    ? "bg-brand-600 text-white shadow-sm"
                    : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-700 hover:border-brand-500"
                }`}
              >
                {d} 层{d === 2 ? "（章节→要点）" : d === 3 ? "（推荐）" : "（更细）"}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-start gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={includeDetails}
            onChange={(e) => setIncludeDetails(e.target.checked)}
            disabled={doneCount === 0}
            className="mt-0.5 rounded text-brand-600 focus:ring-brand-500"
          />
          <span className="text-gray-600 dark:text-gray-300">
            包含各章内容摘要与核心知识点
            {doneCount === 0 ? (
              <span className="ml-1 text-gray-400">（暂无已生成章节，仅按大纲生成）</span>
            ) : (
              <span className="ml-1 text-gray-400">（{doneCount} 个已生成章节）</span>
            )}
          </span>
        </label>

        {error && <ErrorText>{error}</ErrorText>}

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          {!gen.isPending && (
            <Button variant="ghost" onClick={handleClose} className="text-xs">
              取消
            </Button>
          )}
          <Button
            variant="primary"
            disabled={gen.isPending}
            onClick={() => {
              setError("");
              gen.mutate();
            }}
            className="text-xs font-medium"
          >
            {gen.isPending ? (
              <>
                <Spinner className="h-3 w-3 inline mr-1.5" />
                AI 正在构建导图（约 10~40 秒）…
              </>
            ) : (
              "开始生成"
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function CourseDetailPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: course, isLoading, error } = useQuery({
    queryKey: ["course", courseId],
    queryFn: () => api.courses.get(courseId!),
    enabled: !!courseId,
    // 生成中轮询兜底：SSE 断流后进度不再永久冻结（5s 一次，生成结束自动停止）
    refetchInterval: (query) => (query.state.data?.status === "generating" ? 5000 : false),
  });

  const [liveDocs, setLiveDocs] = useState<ChapterProgress[] | null>(null);
  const [doneBanner, setDoneBanner] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [mindmapOpen, setMindmapOpen] = useState(false);

  const rename = useMutation({
    mutationFn: (title: string) => api.courses.rename(courseId!, title),
    onSuccess: () => {
      setRenaming(false);
      queryClient.invalidateQueries({ queryKey: ["course", courseId] });
      queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
    onError: (e) => alert((e as Error).message),
  });
  const abortRef = useRef<AbortController | null>(null);

  // 生成中订阅进度 SSE（snapshot + 实时事件）
  useEffect(() => {
    if (!course || course.status !== "generating" || !courseId) {
      setLiveDocs(null);
      return;
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setLiveDocs(course.documents.length ? course.documents : null);
    subscribeSSE(`/courses/${courseId}/progress`, (ev: ProgressSSEEvent) => {
      if (ev.type === "snapshot" && ev.documents) {
        setLiveDocs(
          ev.documents.map((d) => ({
            document_id: d.document_id,
            chapter_index: d.chapter_index,
            title: d.title,
            status: d.status as ChapterProgress["status"],
            version: d.version,
            error: null,
            source: (d.source ?? "generated") as ChapterProgress["source"],
          }))
        );
      } else if (ev.type === "chapter_start" || ev.type === "chapter_done" || ev.type === "chapter_failed") {
        setLiveDocs((prev) =>
          (prev ?? []).map((d) =>
            d.chapter_index === ev.index
              ? {
                  ...d,
                  status:
                    ev.type === "chapter_start"
                      ? "generating"
                      : ev.type === "chapter_done"
                        ? "done"
                        : "failed",
                  error: ev.type === "chapter_failed" ? ev.error ?? "生成失败" : null,
                }
              : d
          )
        );
      } else if (ev.type === "course_done") {
        setDoneBanner(true);
        queryClient.invalidateQueries({ queryKey: ["course", courseId] });
        queryClient.invalidateQueries({ queryKey: ["courses"] });
      }
    }, ac.signal).catch(() => {
      // 断流兜底：课程仍在生成中时强制刷新一次查询，进度不再停在旧状态
      //（主动 abort 的不算断流，避免卸载/状态切换时的多余请求）
      if (!ac.signal.aborted && courseId) {
        queryClient.invalidateQueries({ queryKey: ["course", courseId] });
      }
    });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [course?.id, course?.status, courseId]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (error || !course) {
    return <EmptyState icon="😕" title={error ? error.message : "课程不存在"} action={<Link to="/" className="text-sm text-brand-600 underline">返回首页</Link>} />;
  }

  const docs = liveDocs ?? course.documents;
  const doneCount = docs.filter((d) => d.status === "done").length;
  const firstDone = docs.find((d) => d.status === "done");

  const retry = async (documentId: string) => {
    try {
      await api.documents.regenerate(documentId);
      // 单章重生成不把课程状态翻回 generating，须自行订阅进度流：
      // 否则章节永远停在"待生成"（后端其实早已生成完成）
      setLiveDocs(
        (prev) =>
          prev ??
          course.documents.map((d) => ({
            document_id: d.document_id,
            chapter_index: d.chapter_index,
            title: d.title,
            status: d.status as ChapterProgress["status"],
            version: d.version,
            error: null,
            source: (d.source ?? "generated") as ChapterProgress["source"],
          }))
      );
      setLiveDocs((prev) =>
        (prev ?? []).map((d) => (d.document_id === documentId ? { ...d, status: "generating", error: null } : d))
      );
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      subscribeSSE<ProgressSSEEvent>(
        `/courses/${courseId}/progress`,
        (ev) => {
          if (ev.document_id && ev.document_id !== documentId) return;
          if (ev.type === "chapter_start" || ev.type === "chapter_done" || ev.type === "chapter_failed") {
            setLiveDocs((prev) =>
              (prev ?? []).map((d) =>
                d.document_id === documentId
                  ? {
                      ...d,
                      status:
                        ev.type === "chapter_start"
                          ? "generating"
                          : ev.type === "chapter_done"
                            ? "done"
                            : "failed",
                      error: ev.type === "chapter_failed" ? ev.error ?? "生成失败" : null,
                    }
                  : d
              )
            );
            if (ev.type === "chapter_done" || ev.type === "chapter_failed") {
              ac.abort();
              queryClient.invalidateQueries({ queryKey: ["course", courseId] });
              queryClient.invalidateQueries({ queryKey: ["courses"] });
            }
          } else if (ev.type === "course_done") {
            ac.abort();
            setDoneBanner(true);
            queryClient.invalidateQueries({ queryKey: ["course", courseId] });
            queryClient.invalidateQueries({ queryKey: ["courses"] });
          }
        },
        ac.signal
      ).catch(() => {
        // 断流兜底：单章重生成中断后强制刷新查询，章节状态不再停在「生成中」
        if (!ac.signal.aborted && courseId) {
          queryClient.invalidateQueries({ queryKey: ["course", courseId] });
        }
      });
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-5xl p-8">
      <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-brand-600">
        ← 返回首页
      </Link>
      <div className="mt-3 flex items-center justify-between gap-3">
        {renaming ? (
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Input
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && titleDraft.trim()) rename.mutate(titleDraft.trim());
                if (e.key === "Escape") setRenaming(false);
              }}
              autoFocus
              aria-label="课程名称"
            />
            <Button
              variant="secondary"
              className="shrink-0 text-xs"
              disabled={!titleDraft.trim() || rename.isPending}
              onClick={() => rename.mutate(titleDraft.trim())}
            >
              {rename.isPending ? <Spinner className="h-3.5 w-3.5" /> : "保存"}
            </Button>
            <Button variant="ghost" className="shrink-0 text-xs" onClick={() => setRenaming(false)}>
              取消
            </Button>
          </div>
        ) : (
          <h1 className="min-w-0 flex-1 truncate text-2xl font-bold text-gray-900 dark:text-gray-100">{course.title}</h1>
        )}
        <div className="flex items-center gap-2">
          {course.status !== "draft" && (
            <Button
              variant="ghost"
              className="text-xs text-brand-600 dark:text-brand-400"
              onClick={() => setMindmapOpen(true)}
              title="基于课程大纲与已生成章节的知识点，一键生成思维导图"
            >
              🧠 生成思维导图
            </Button>
          )}
          {course.status !== "draft" && (
            <DropdownMenu
              label="⬇ 导出 ▾"
              title="导出课程内容"
              triggerClassName="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
              items={[
                { label: "笔记汇编（含批注）", icon: "📝", onSelect: () => api.courses.exportNotesMd(course.id).catch((e) => alert(e.message)) },
                { label: "教材 Markdown", icon: "📄", onSelect: () => api.courses.exportMd(course.id).catch((e) => alert(e.message)) },
                { label: "教材 HTML", icon: "🌐", onSelect: () => api.courses.exportHtml(course.id).catch((e) => alert(e.message)) },
              ]}
            />
          )}
          <DropdownMenu
            label="⋯"
            title="更多操作"
            triggerClassName="inline-flex h-8 w-8 items-center justify-center rounded-lg text-lg leading-none text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
            items={[
              {
                label: "重命名课程",
                icon: "✏️",
                onSelect: () => {
                  setTitleDraft(course.title);
                  setRenaming(true);
                },
              },
              { label: "删除课程", icon: "🗑️", danger: true, onSelect: () => setConfirmDel(true) },
            ]}
          />
        </div>
      </div>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{course.topic}</p>

      {doneBanner && course.status !== "generating" && (
        <div className="mt-4 rounded-lg bg-green-50 dark:bg-green-900/30 px-4 py-3 text-sm text-green-700 dark:text-green-400">
          生成完成，可以开始学习了。
          {firstDone && (
            <Link to={`/read/${firstDone.document_id}`} className="ml-2 underline">
              打开第一章 →
            </Link>
          )}
        </div>
      )}

      {course.status === "draft" ? (
        <div className="mt-6">
          <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">课程大纲（可编辑）</h2>
          <OutlineEditor course={course} />
        </div>
      ) : (
        <div className="mt-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">章节</h2>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {doneCount}/{docs.length} 章
                {course.status === "generating" && (
                  <Badge color="blue">
                    生成中 <Spinner className="ml-1 h-3 w-3 border-white/60" />
                  </Badge>
                )}
              </span>
            </div>
          </div>
          {docs.length > 0 && (
            <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
              <div
                className="h-full rounded-full bg-brand-500 transition-all"
                style={{ width: `${docs.length ? Math.round((doneCount / docs.length) * 100) : 0}%` }}
              />
            </div>
          )}
          <div className="space-y-2">
            {docs.length === 0 && <EmptyState icon="📄" title="暂无章节，请先保存大纲" />}
            {docs.map((d) => {
              const st = DOC_STATUS[d.status] ?? DOC_STATUS.pending;
              return (
                <div
                  key={d.document_id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3"
                >
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <span className="w-6 text-center text-sm font-semibold text-gray-400 dark:text-gray-500">{d.chapter_index}</span>
                    <span className="truncate text-sm font-medium text-gray-800 dark:text-gray-200">{d.title}</span>
                    {d.status === "failed" && (
                      <span className="truncate text-xs text-red-500 dark:text-red-400">{d.error}</span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge color={st.color}>{st.label}</Badge>
                    {d.source === "imported" && <Badge color="blue">导入·原文保留</Badge>}
                    {d.status === "done" && (
                      <Link to={`/read/${d.document_id}`}>
                        <Button>阅读</Button>
                      </Link>
                    )}
                    {d.status === "failed" && (
                      <Button variant="secondary" onClick={() => retry(d.document_id)}>
                        重试本章
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {doneCount > 0 && (
            <div className="mt-4">
              <CourseAskPanel courseId={course.id} />
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirmDel}
        title="删除课程"
        message={`确定删除课程「${course.title}」？全部文档、标注与对话将被删除，且无法恢复。`}
        onCancel={() => setConfirmDel(false)}
        onConfirm={async () => {
          setConfirmDel(false);
          try {
            await api.courses.delete(course.id);
            // 删除会连带清掉练习/标注/对话，课程列表、仪表盘等缓存全部失效；
            // 否则 15s staleTime 内返回首页会直接命中旧缓存，看起来像"没删掉"
            await queryClient.invalidateQueries();
            navigate("/");
          } catch (err) {
            alert((err as Error).message);
          }
        }}
      />
      <MindMapGenModal
        open={mindmapOpen}
        courseId={course.id}
        courseTitle={course.title}
        doneCount={doneCount}
        onClose={() => setMindmapOpen(false)}
      />
    </div>
  );
}
