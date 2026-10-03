// 错题本：最近一次作答未通过的练习（跨课程），重刷通过后自动出池
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { EmptyState, Spinner } from "../../components/ui";
import ExerciseCard from "../reader/ExerciseCard";

export default function WrongBookPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["exercises-wrongbook"],
    queryFn: api.exercises.wrongbook,
  });

  return (
    <div className="mx-auto max-w-5xl p-8">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">📕 错题本</h1>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        最近一次作答未通过的题都在这里；重刷通过后自动出池。
      </p>
      {isLoading ? (
        <div className="mt-10 flex justify-center">
          <Spinner />
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState icon="🎉" title="没有错题" hint="练习里做错的题会自动收集到这里。" />
      ) : (
        <div className="mt-4 space-y-4">
          {data.map((e) => (
            <div key={e.id}>
              <div className="mb-1 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
                <span>
                  {e.kp_title ?? "（知识点已删除）"} ·{" "}
                  {e.kind === "code" ? "代码题" : e.kind === "choice" ? "单选" : e.kind === "fill" ? "填空" : "概念题"}
                </span>
                <Link to={`/read/${e.document_id}`} className="text-brand-600 underline">
                  前往章节 ↗
                </Link>
              </div>
              <ExerciseCard exercise={e} documentId={e.document_id} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
