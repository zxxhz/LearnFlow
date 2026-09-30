// 费曼列表 + 通过 ?kp=xxx 发起新讲解（阅读器知识点入口跳转目标）
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, Button, EmptyState, Spinner, Textarea } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

const STATUS_BADGE = {
  explaining: { label: "讲解中", color: "gray" as const },
  questioning: { label: "进行中", color: "blue" as const },
  evaluating: { label: "评价中", color: "amber" as const },
  done: { label: "已完成", color: "green" as const },
};

function StartPanel({ kpId }: { kpId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [explanation, setExplanation] = useState("");
  const { data: ctx, isLoading } = useQuery({
    queryKey: ["kp-ctx", kpId],
    queryFn: () => api.feynman.kpContext(kpId),
  });

  const start = useMutation({
    mutationFn: () => api.feynman.start({ knowledge_point_id: kpId, explanation: explanation.trim() }),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ["feynman-list"] });
      navigate(`/feynman/${session.id}`);
    },
  });

  if (isLoading) return <Spinner className="h-5 w-5" />;
  if (!ctx) return <p className="text-sm text-red-600">知识点不存在</p>;

  return (
    <div className="rounded-xl border border-brand-200 bg-brand-50/40 p-5">
      <h2 className="text-base font-semibold text-gray-900">费曼讲解：{ctx.knowledge_point.title}</h2>
      <p className="mt-1 text-sm text-gray-600">{ctx.knowledge_point.summary}</p>
      <p className="mt-1 text-xs text-gray-400">
        来自《{ctx.course_title}》·{" "}
        <Link to={`/read/${ctx.document_id}`} className="underline">
          {ctx.document_title}
        </Link>
      </p>
      <p className="mt-3 text-sm font-medium text-gray-700">用自己的话讲解这个知识点，就像讲给完全不懂的人听：</p>
      <Textarea
        className="mt-2"
        rows={8}
        value={explanation}
        onChange={(e) => setExplanation(e.target.value)}
        placeholder="写下你的讲解。可以用自己的话、举例子、写公式（$...$）和代码。AI 会扮演一个好奇的学生向你追问。"
      />
      {start.isError && <p className="mt-2 text-sm text-red-600">{start.error.message}</p>}
      <Button
        className="mt-3"
        disabled={!explanation.trim() || start.isPending}
        onClick={() => start.mutate()}
      >
        {start.isPending ? (
          <>
            <Spinner className="border-white/40" /> 学生正在思考你的讲解…
          </>
        ) : (
          "开始讲解"
        )}
      </Button>
    </div>
  );
}

export default function FeynmanIndexPage() {
  const [params] = useSearchParams();
  const kpId = params.get("kp");

  const { data: sessions, isLoading } = useQuery({
    queryKey: ["feynman-list"],
    queryFn: () => api.feynman.list(),
    refetchInterval: 10_000,
  });

  useEffect(() => {
    document.title = "费曼讲解 · LearnFlow";
  }, []);

  return (
    <div className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-bold text-gray-900">费曼讲解</h1>
      <p className="mt-1 text-sm text-gray-500">
        用自己的话讲解知识点，AI 扮演学生追问，暴露理解漏洞。
        {kpId && " 在下方开始新讲解。"}
      </p>

      {kpId && (
        <div className="mt-5">
          <StartPanel kpId={kpId} />
        </div>
      )}

      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900">历史会话</h2>
      {isLoading ? (
        <Spinner className="h-5 w-5" />
      ) : !sessions || sessions.length === 0 ? (
        <EmptyState
          icon="🎤"
          title="还没有费曼讲解记录"
          hint="在阅读文档时点击知识点的「费曼讲解」按钮，或从仪表盘薄弱知识点进入"
        />
      ) : (
        <div className="space-y-2">
          {sessions.map((s) => {
            const badge = STATUS_BADGE[s.status] ?? STATUS_BADGE.questioning;
            return (
              <Link
                key={s.id}
                to={`/feynman/${s.id}`}
                className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 transition hover:border-brand-500"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-gray-800">
                      {s.knowledge_point_id.slice(0, 8)}…
                    </span>
                    <Badge color={badge.color}>{badge.label}</Badge>
                  </div>
                  <div className="mt-0.5 text-xs text-gray-400">
                    {s.round_count} 轮追问 · {new Date(s.updated_at).toLocaleString("zh-CN")}
                    {s.evaluation && ` · 评分 ${s.evaluation.score}`}
                  </div>
                </div>
                {s.evaluation && (
                  <span
                    className={`text-lg font-bold ${
                      s.evaluation.score >= 85
                        ? "text-green-600"
                        : s.evaluation.score >= 60
                          ? "text-amber-600"
                          : "text-red-600"
                    }`}
                  >
                    {s.evaluation.score}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
