// 仪表盘：今日概览 / 课程进度 / 薄弱知识点 / 学习热力图（PRD §5.6）
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, EmptyState, Spinner } from "../../components/ui";

const STATUS_BADGE: Record<string, { label: string; color: "gray" | "blue" | "green" }> = {
  draft: { label: "草稿", color: "gray" },
  generating: { label: "生成中", color: "blue" },
  ready: { label: "可学习", color: "green" },
};

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard.summary,
  });

  if (isLoading || !data) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  // 热力图：83 天补齐并对齐到周一开列
  const days = [...data.heatmap];
  const firstDow = days.length ? (new Date(days[0].date + "T00:00:00").getDay() + 6) % 7 : 0;
  const cells: (string | null)[] = [...Array<null>(firstDow), ...days.map((d) => d.date)];
  const countBy = new Map(days.map((d) => [d.date, d.count]));
  const weeks: (string | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  const heatColor = (date: string | null) => {
    if (!date) return "bg-transparent";
    const c = countBy.get(date) ?? 0;
    if (c === 0) return "bg-gray-100";
    if (c <= 2) return "bg-green-200";
    if (c <= 5) return "bg-green-400";
    if (c <= 10) return "bg-green-500";
    return "bg-green-700";
  };

  return (
    <div className="mx-auto max-w-4xl p-8">
      <h1 className="text-2xl font-bold text-gray-900">学习仪表盘</h1>

      {/* 今日概览 */}
      <div className="mt-5 grid grid-cols-2 gap-4">
        <Link to="/review" className="rounded-xl border border-gray-200 bg-white p-5 transition hover:border-brand-500">
          <div className="text-3xl font-bold text-brand-600">{data.today.due_reviews}</div>
          <div className="mt-1 text-sm text-gray-500">今日待复习</div>
        </Link>
        <Link to="/feynman" className="rounded-xl border border-gray-200 bg-white p-5 transition hover:border-brand-500">
          <div className="text-3xl font-bold text-brand-600">{data.today.feynman_active}</div>
          <div className="mt-1 text-sm text-gray-500">进行中的费曼讲解</div>
        </Link>
      </div>

      {/* 课程进度 */}
      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900">课程进度</h2>
      {data.courses.length === 0 ? (
        <EmptyState icon="📚" title="还没有课程" hint="从首页创建一门课程开始学习" />
      ) : (
        <div className="space-y-2">
          {data.courses.map((c) => {
            const badge = STATUS_BADGE[c.status] ?? STATUS_BADGE.draft;
            return (
              <Link
                key={c.id}
                to={`/courses/${c.id}`}
                className="block rounded-xl border border-gray-200 bg-white px-4 py-3 transition hover:border-brand-500"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-800">{c.title}</span>
                  <Badge color={badge.color}>{badge.label}</Badge>
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                    <div
                      className="h-full rounded-full bg-brand-500"
                      style={{
                        width: `${c.total_chapters ? Math.round((c.done_chapters / c.total_chapters) * 100) : 0}%`,
                      }}
                    />
                  </div>
                  <span className="shrink-0 text-xs text-gray-400">
                    {c.done_chapters}/{c.total_chapters} 章
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* 薄弱知识点 */}
      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900">薄弱知识点</h2>
      {data.weak_points.length === 0 ? (
        <p className="text-sm text-gray-400">暂无数据（复习遗忘或费曼暴露漏洞后在这里出现）</p>
      ) : (
        <div className="space-y-2">
          {data.weak_points.map((w, i) => (
            <Link
              key={w.knowledge_point_id}
              to={`/read/${w.document_id}`}
              className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 transition hover:border-brand-500"
            >
              <div className="flex items-center gap-3">
                <span className="w-5 text-sm font-semibold text-gray-300">{i + 1}</span>
                <span className="text-sm font-medium text-gray-800">{w.title}</span>
              </div>
              <div className="flex gap-2 text-xs">
                {w.lapses > 0 && <Badge color="red">遗忘 {w.lapses} 次</Badge>}
                {w.gap_count > 0 && <Badge color="amber">漏洞 {w.gap_count} 个</Badge>}
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* 热力图 */}
      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900">学习热力图（近 12 周）</h2>
      <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex gap-1">
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-1">
              {week.map((date, di) => (
                <div
                  key={di}
                  className={`h-3.5 w-3.5 rounded-sm ${heatColor(date)}`}
                  title={date ? `${date}：${countBy.get(date) ?? 0} 次学习动作` : ""}
                />
              ))}
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-1 text-[10px] text-gray-400">
          少
          <span className="ml-1 h-3 w-3 rounded-sm bg-gray-100" />
          <span className="h-3 w-3 rounded-sm bg-green-200" />
          <span className="h-3 w-3 rounded-sm bg-green-400" />
          <span className="h-3 w-3 rounded-sm bg-green-500" />
          <span className="h-3 w-3 rounded-sm bg-green-700" />
          多
        </div>
      </div>
    </div>
  );
}
