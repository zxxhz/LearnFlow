import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { CompareHighlightItem, HighlightComparisonOut } from "../../lib/types";
import { Button, Spinner } from "../../components/ui";

interface ChapterHighlightCompareProps {
  documentId: string;
  userAnnotationCount: number;
  onAdoptHighlight: (item: CompareHighlightItem) => Promise<void>;
  onJumpToSection: (sectionId: string) => void;
}

export function ChapterHighlightCompare({
  documentId,
  userAnnotationCount,
  onAdoptHighlight,
  onJumpToSection,
}: ChapterHighlightCompareProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [adoptedExacts, setAdoptedExacts] = useState<Set<string>>(new Set());
  const [adoptingExact, setAdoptingExact] = useState<string | null>(null);
  const [adoptError, setAdoptError] = useState("");

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery<HighlightComparisonOut>({
    queryKey: ["compare-highlights", documentId],
    queryFn: () => api.documents.compareHighlights(documentId),
    enabled: isOpen,
    staleTime: 10_000,
  });

  const handleAdopt = async (item: CompareHighlightItem) => {
    try {
      setAdoptError("");
      setAdoptingExact(item.exact);
      await onAdoptHighlight(item);
      setAdoptedExacts((prev) => new Set(prev).add(item.exact));
    } catch (e) {
      // 采纳失败必须可见：后端 400（如划线位置无效）静默吞掉会让用户以为已采纳
      setAdoptError(e instanceof Error ? e.message : "采纳失败，请重试");
    } finally {
      setAdoptingExact(null);
    }
  };

  return (
    <div className="mt-12 mb-8 rounded-2xl border border-gray-200 dark:border-gray-700 bg-gradient-to-br from-gray-50/80 to-white dark:from-gray-800/40 dark:to-gray-900/60 p-6 shadow-sm transition-all">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg">🧐</span>
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              抓重点能力自测：与 AI 视野对照
            </h3>
            <span className="rounded-full bg-brand-50 dark:bg-brand-950/40 border border-brand-200 dark:border-brand-800 px-2 py-0.5 text-xs font-medium text-brand-700 dark:text-brand-300">
              自主学习倡导
            </span>
          </div>
          <p className="mt-1.5 text-xs text-gray-600 dark:text-gray-400 leading-relaxed max-w-2xl">
            系统默认不自动划重点，鼓励在精读中自主圈选关键语句。读完本章后，可开启对照查看 AI
            眼中的核心要害与避坑法则，检验你的抓重点敏锐度。
          </p>
        </div>
        {!isOpen ? (
          <Button
            variant="secondary"
            className="shrink-0 text-xs font-medium !py-2 !px-4 border-brand-300 dark:border-brand-700 text-brand-700 dark:text-brand-300 hover:bg-brand-50 dark:hover:bg-brand-950/40 shadow-xs"
            onClick={() => setIsOpen(true)}
          >
            🔍 开启视野对照
          </Button>
        ) : (
          <Button
            variant="ghost"
            className="shrink-0 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            onClick={() => setIsOpen(false)}
          >
            收起对照
          </Button>
        )}
      </div>

      {isOpen && (
        <div className="mt-5 border-t border-gray-100 dark:border-gray-800 pt-5 space-y-4">
          {adoptError && (
            <div className="rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50/60 dark:bg-red-950/20 px-3 py-2 text-xs text-red-600 dark:text-red-400">
              采纳失败：{adoptError}
            </div>
          )}
          {isLoading || isFetching ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-gray-500 dark:text-gray-400">
              <Spinner className="h-4 w-4" /> 正在调取 AI 重点与你的划线对比中…
            </div>
          ) : isError ? (
            <div className="py-4 text-center text-xs text-red-600 dark:text-red-400">
              加载重点对照失败：{error instanceof Error ? error.message : "未知错误"}
              <Button variant="ghost" className="ml-2 !py-0.5 text-xs underline" onClick={() => refetch()}>
                重试
              </Button>
            </div>
          ) : data ? (
            <>
              {/* 汇总三指标卡片 */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-800/50 p-3 text-center">
                  <div className="text-xs text-gray-400 dark:text-gray-500">我的手动标注</div>
                  <div className="mt-1 text-lg font-bold text-gray-800 dark:text-gray-200">
                    {userAnnotationCount} <span className="text-xs font-normal text-gray-400">处</span>
                  </div>
                </div>
                <div className="rounded-xl border border-emerald-100 dark:border-emerald-900/40 bg-emerald-50/40 dark:bg-emerald-950/20 p-3 text-center">
                  <div className="text-xs text-emerald-600 dark:text-emerald-400">与 AI 视野重合</div>
                  <div className="mt-1 text-lg font-bold text-emerald-700 dark:text-emerald-300">
                    {data.matched_count} <span className="text-xs font-normal text-emerald-600/70">处</span>
                  </div>
                </div>
                <div className="rounded-xl border border-amber-100 dark:border-amber-900/40 bg-amber-50/40 dark:bg-amber-950/20 p-3 text-center">
                  <div className="text-xs text-amber-600 dark:text-amber-400">AI 额外建议关注</div>
                  <div className="mt-1 text-lg font-bold text-amber-700 dark:text-amber-300">
                    {Math.max(0, data.missed_count - adoptedExacts.size)}{" "}
                    <span className="text-xs font-normal text-amber-600/70">处</span>
                  </div>
                </div>
              </div>

              {/* 总结评语 */}
              <div className="rounded-xl border border-brand-100 dark:border-brand-900/30 bg-brand-50/30 dark:bg-brand-950/20 px-4 py-2.5 text-xs text-brand-800 dark:text-brand-200 leading-relaxed flex items-center justify-between">
                <span>{data.summary}</span>
                <Button variant="ghost" className="!p-1 text-xs text-brand-600 hover:text-brand-800 dark:text-brand-400" onClick={() => refetch()} title="重新对照">
                  ↻
                </Button>
              </div>

              {/* 重点候选明细卡片 */}
              {data.candidates.length === 0 ? (
                <p className="py-6 text-center text-xs text-gray-400">（本章暂无额外识别到的重点候选）</p>
              ) : (
                <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                  {data.candidates.map((cand, idx) => {
                    const isAdopted = cand.is_matched || adoptedExacts.has(cand.exact);
                    return (
                      <div
                        key={idx}
                        className={`rounded-xl border p-3.5 transition-all text-xs flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 ${
                          isAdopted
                            ? "border-emerald-200 dark:border-emerald-800/40 bg-emerald-50/20 dark:bg-emerald-950/10"
                            : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/50 hover:border-gray-300 dark:hover:border-gray-600"
                        }`}
                      >
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            {isAdopted ? (
                              <span className="inline-flex items-center gap-0.5 rounded-md bg-emerald-100 dark:bg-emerald-900/40 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300">
                                ✓ 已覆盖
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-0.5 rounded-md bg-amber-100 dark:bg-amber-900/40 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300">
                                💡 建议关注
                              </span>
                            )}
                            <span className="rounded-md bg-gray-100 dark:bg-gray-700/60 px-2 py-0.5 text-[11px] text-gray-600 dark:text-gray-300">
                              {cand.note || "核心重点"}
                            </span>
                          </div>
                          <p className="text-gray-800 dark:text-gray-200 font-medium leading-relaxed italic">
                            “{cand.exact}”
                          </p>
                        </div>

                        <div className="shrink-0 flex items-center gap-2">
                          <Button
                            variant="ghost"
                            className="text-xs !py-1 !px-2 text-gray-600 dark:text-gray-300 hover:text-brand-600 dark:hover:text-brand-400"
                            onClick={() => onJumpToSection(cand.section_id)}
                          >
                            🎯 定位原文
                          </Button>
                          {!isAdopted && (
                            <Button
                              variant="secondary"
                              className="text-xs !py-1 !px-2.5 font-medium border-brand-300 dark:border-brand-700 text-brand-700 dark:text-brand-300 hover:bg-brand-50 dark:hover:bg-brand-950/40"
                              disabled={adoptingExact === cand.exact}
                              onClick={() => handleAdopt(cand)}
                            >
                              {adoptingExact === cand.exact ? (
                                <>
                                  <Spinner className="h-3 w-3 inline mr-1" />
                                  采纳中
                                </>
                              ) : (
                                "📌 采纳标注"
                              )}
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
