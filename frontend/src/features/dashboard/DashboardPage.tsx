// 仪表盘：课程进度 / 薄弱知识点 / 学习热力图（PRD §5.6）
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, EmptyState, Spinner } from "../../components/ui";

const STATUS_BADGE: Record<string, { label: string; color: "gray" | "blue" | "green" }> = {
  draft: { label: "草稿", color: "gray" },
  generating: { label: "生成中", color: "blue" },
  ready: { label: "可学习", color: "green" },
};

function MasteryPill({ mastery }: { mastery: number }) {
  const cls =
    mastery >= 80
      ? "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400"
      : mastery >= 60
        ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
        : "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${cls}`} title="掌握度：闯关练习通过率">
      掌握 {mastery}%
    </span>
  );
}

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
    if (c === 0) return "bg-gray-100 dark:bg-gray-800";
    if (c <= 2) return "bg-green-200";
    if (c <= 5) return "bg-green-400";
    if (c <= 10) return "bg-green-500";
    return "bg-green-700";
  };

  return (
    <div className="mx-auto max-w-5xl p-8">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">学习仪表盘</h1>

      {/* 课程进度 */}
      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">课程进度</h2>
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
                className="block rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3 transition hover:border-brand-500"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800 dark:text-gray-200">
                    {c.title}
                  </span>
                  <Badge color={badge.color}>{badge.label}</Badge>
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
                    <div
                      className="h-full rounded-full bg-brand-500"
                      style={{
                        width: `${c.total_chapters ? Math.round((c.done_chapters / c.total_chapters) * 100) : 0}%`,
                      }}
                    />
                  </div>
                  <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">
                    {c.done_chapters}/{c.total_chapters} 章
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* 薄弱知识点（按掌握度升序：闯关练习通过率） */}
      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">薄弱知识点</h2>
      {data.weak_points.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500">暂无数据（闯关练习出错后在这里出现）</p>
      ) : (
        <div className="space-y-2">
          {data.weak_points.map((w, i) => (
            <div
              key={w.knowledge_point_id}
              className="flex items-center justify-between rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-3"
            >
              <Link to={`/read/${w.document_id}`} className="flex min-w-0 items-center gap-3 hover:text-brand-600">
                <span className="w-5 text-sm font-semibold text-gray-300 dark:text-gray-600">{i + 1}</span>
                <span className="truncate text-sm font-medium text-gray-800 dark:text-gray-200">{w.title}</span>
              </Link>
              <div className="flex shrink-0 items-center gap-2">
                <MasteryPill mastery={w.mastery} />
                <div className="flex gap-1.5 text-xs">
                  {w.exercise_fail > 0 && <Badge color="red">错题 {w.exercise_fail} 道</Badge>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 学习时长 */}
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">阅读时长</h3>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-brand-600">{data.study_minutes_7d}</span>
            <span className="text-xs text-gray-400 dark:text-gray-500">分钟 / 近 7 天</span>
          </div>
          <div className="mt-2 flex h-12 items-end gap-0.5">
            {data.study_days.slice(-30).map((d) => {
              const h = Math.min(100, Math.round((d.minutes / Math.max(30, ...data.study_days.map((x) => x.minutes))) * 100));
              return (
                <div
                  key={d.date}
                  className={`flex-1 rounded-sm ${d.minutes > 0 ? "bg-brand-400" : "bg-gray-100 dark:bg-gray-800"}`}
                  style={{ height: `${d.minutes > 0 ? Math.max(8, h) : 6}%` }}
                  title={`${d.date}：${d.minutes} 分钟`}
                />
              );
            })}
          </div>
        </div>
      </div>

      {/* LLM Token 用量 */}
      {data.llm_usage && (
        <div className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Token 用量（近 30 天）</h3>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
            <span className="text-gray-700 dark:text-gray-300">
              输入 <strong>{data.llm_usage.prompt_tokens.toLocaleString()}</strong>
            </span>
            <span className="text-gray-700 dark:text-gray-300">
              输出 <strong>{data.llm_usage.completion_tokens.toLocaleString()}</strong>
            </span>
            <span className="text-gray-400 dark:text-gray-500">共 {data.llm_usage.calls} 次调用</span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-2 text-[10px] text-gray-400 dark:text-gray-500">
            {data.llm_usage.by_scene.map((s) => (
              <span key={s.scene} className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5">
                {s.scene === "generation" ? "生成" : "答疑"} {s.tokens.toLocaleString()}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 热力图 */}
      <h2 className="mt-8 mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">学习热力图（近 12 周）</h2>
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
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
        <div className="mt-2 flex items-center gap-1 text-[10px] text-gray-400 dark:text-gray-500">
          少
          <span className="ml-1 h-3 w-3 rounded-sm bg-gray-100 dark:bg-gray-800" />
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
