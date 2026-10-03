// 全局搜索：跨课程 FTS5 全文检索（词法），命中片段直达阅读位置
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Button, EmptyState, Spinner } from "../../components/ui";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState("");
  const { data, isFetching } = useQuery({
    queryKey: ["search", submitted],
    queryFn: () => api.search(submitted),
    enabled: submitted.trim().length > 0,
  });

  // FTS 片段含我们自己的 <mark> 标记：先整体转义再恢复标记，防止正文里的其他 HTML 被当标签渲染
  const safeSnippet = (snippet: string) =>
    snippet
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/&lt;mark&gt;/g, '<mark class="bg-yellow-200 dark:bg-yellow-500/40">')
      .replace(/&lt;\/mark&gt;/g, "</mark>");

  return (
    <div className="mx-auto max-w-5xl p-8">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">🔍 全局搜索</h1>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(q.trim());
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索所有课程的内容…"
          autoFocus
          className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <Button type="submit" disabled={!q.trim() || isFetching}>
          搜索
        </Button>
      </form>

      {isFetching && (
        <div className="mt-10 flex justify-center">
          <Spinner />
        </div>
      )}
      {!isFetching && submitted && data && data.results.length === 0 && (
        <EmptyState icon="🫥" title="没有找到相关内容" hint="换个关键词试试；只搜已生成/导入的章节正文。" />
      )}
      {data && data.results.length > 0 && (
        <div className="mt-4 space-y-3">
          <p className="text-xs text-gray-400 dark:text-gray-500">共 {data.results.length} 条结果</p>
          {data.results.map((hit, i) => (
            <Link
              key={`${hit.section_id}-${i}`}
              to={`/read/${hit.document_id}`}
              className="block rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 hover:border-brand-300"
            >
              <div className="text-xs text-gray-400 dark:text-gray-500">
                {hit.course_title} · {hit.document_title}
                {hit.heading && ` · ${hit.heading}`}
              </div>
              <div
                className="mt-1 text-sm text-gray-700 dark:text-gray-300"
                dangerouslySetInnerHTML={{ __html: safeSnippet(hit.snippet) }}
              />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
