// 课程详情：草稿态=大纲编辑器；生成态=章节进度（SSE 实时刷新）（PRD FR-1.3）
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { subscribeSSE } from "../../lib/sse";
import type { ChapterProgress, ProgressSSEEvent } from "../../lib/types";
import { Badge, Button, EmptyState, Spinner } from "../../components/ui";
import OutlineEditor from "./OutlineEditor";

const DOC_STATUS: Record<string, { label: string; color: "gray" | "green" | "blue" | "red" | "amber" }> = {
  pending: { label: "待生成", color: "gray" },
  generating: { label: "生成中", color: "blue" },
  done: { label: "完成", color: "green" },
  failed: { label: "失败", color: "red" },
};

export default function CourseDetailPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: course, isLoading, error } = useQuery({
    queryKey: ["course", courseId],
    queryFn: () => api.courses.get(courseId!),
    enabled: !!courseId,
  });

  const [liveDocs, setLiveDocs] = useState<ChapterProgress[] | null>(null);
  const [doneBanner, setDoneBanner] = useState(false);
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
      /* 流结束/中断，静默；查询会兜底刷新 */
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

  const docs = course.status === "generating" && liveDocs ? liveDocs : course.documents;
  const doneCount = docs.filter((d) => d.status === "done").length;
  const firstDone = docs.find((d) => d.status === "done");

  const retry = async (documentId: string) => {
    try {
      await api.documents.regenerate(documentId);
      setLiveDocs((prev) => (prev ?? docs).map((d) => (d.document_id === documentId ? { ...d, status: "pending", error: null } : d)));
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-4xl p-8">
      <Link to="/" className="text-sm text-gray-500 hover:text-brand-600">
        ← 返回首页
      </Link>
      <div className="mt-3 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900">{course.title}</h1>
        <Button
          variant="secondary"
          onClick={() => {
            if (confirm(`确定删除课程「${course.title}」？全部文档、标注与对话将被删除。`)) {
              api.courses.delete(course.id).then(() => navigate("/"));
            }
          }}
        >
          删除课程
        </Button>
      </div>
      <p className="mt-1 text-sm text-gray-500">{course.topic}</p>

      {doneBanner && course.status !== "generating" && (
        <div className="mt-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">
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
          <h2 className="mb-3 text-base font-semibold text-gray-900">课程大纲（可编辑）</h2>
          <OutlineEditor course={course} />
        </div>
      ) : (
        <div className="mt-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900">章节</h2>
            <span className="text-sm text-gray-500">
              {doneCount}/{docs.length} 章
              {course.status === "generating" && (
                <Badge color="blue">
                  生成中 <Spinner className="ml-1 h-3 w-3 border-white/60" />
                </Badge>
              )}
            </span>
          </div>
          {docs.length > 0 && (
            <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
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
                  className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="w-6 text-center text-sm font-semibold text-gray-400">{d.chapter_index}</span>
                    <span className="truncate text-sm font-medium text-gray-800">{d.title}</span>
                    {d.status === "failed" && (
                      <span className="truncate text-xs text-red-500">{d.error}</span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge color={st.color}>{st.label}</Badge>
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
        </div>
      )}
    </div>
  );
}
