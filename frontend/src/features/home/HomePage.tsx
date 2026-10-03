import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, Button, EmptyState, Spinner } from "../../components/ui";

const STATUS_BADGE: Record<string, { label: string; color: "gray" | "green" | "blue" | "amber" }> = {
  draft: { label: "草稿", color: "gray" },
  generating: { label: "生成中", color: "blue" },
  ready: { label: "可学习", color: "green" },
};

export default function HomePage() {
  const navigate = useNavigate();
  const { data: courses, isLoading } = useQuery({ queryKey: ["courses"], queryFn: api.courses.list });

  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">我的课程</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">学 · 问 · 练 · 错题重刷，一个闭环</p>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={() => navigate("/courses/new")}>＋ 新建课程</Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-6 w-6" />
        </div>
      ) : !courses || courses.length === 0 ? (
        <EmptyState
          icon="📚"
          title="还没有课程"
          hint="输入你想学的内容（如 C++ 基础、高等数学），AI 会生成大纲和逐章文档"
          action={
            <Button className="mt-3" onClick={() => navigate("/courses/new")}>
              创建第一门课程
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {courses.map((c) => {
            const badge = STATUS_BADGE[c.status] ?? STATUS_BADGE.draft;
            return (
              <div
                key={c.id}
                onClick={() => navigate(`/courses/${c.id}`)}
                className="cursor-pointer rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 transition hover:border-brand-500 hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{c.title}</h3>
                  <Badge color={badge.color}>{badge.label}</Badge>
                </div>
                <p className="mt-1 line-clamp-2 text-sm text-gray-500 dark:text-gray-400">{c.topic}</p>
                <div className="mt-4 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
                  <span>
                    {c.total_chapters > 0 ? `进度 ${c.done_chapters}/${c.total_chapters} 章` : "尚未生成"}
                  </span>
                  <span>{new Date(c.updated_at).toLocaleDateString("zh-CN")}</span>
                </div>
                {c.total_chapters > 0 && (
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
                    <div
                      className="h-full rounded-full bg-brand-500"
                      style={{ width: `${Math.round((c.done_chapters / c.total_chapters) * 100)}%` }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
