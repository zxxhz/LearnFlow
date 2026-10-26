import type { KnowledgePoint, Exercise } from "../../lib/types";
import { Button } from "../../components/ui";

interface Props {
  chapterIndex: number;
  chapterTitle: string;
  activeKps: KnowledgePoint[];
  exercises: Exercise[];
  annotationsCount: number;
  nextChapter?: { chapter_index: number; title: string; document_id: string } | null;
  onNextChapter?: () => void;
  onGoHome: () => void;
}

export function ChapterSummaryCard({
  chapterIndex,
  chapterTitle,
  activeKps,
  exercises,
  annotationsCount,
  nextChapter,
  onNextChapter,
  onGoHome,
}: Props) {
  const passedCount = exercises.filter((e) => e.ever_passed).length;
  const hardBoneCount = exercises.filter((e) => e.is_hard_bone).length;

  return (
    <div className="mt-10 mb-8 rounded-2xl border border-emerald-200 dark:border-emerald-800/60 bg-gradient-to-br from-emerald-50/50 via-white to-brand-50/30 dark:from-emerald-950/20 dark:via-gray-900/40 dark:to-brand-950/20 p-6 shadow-sm transition-all">
      <div className="flex items-center justify-between pb-4 border-b border-gray-100 dark:border-gray-800 flex-wrap gap-2">
        <div className="flex items-center gap-2.5">
          <span className="text-2xl">🎉</span>
          <div>
            <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">
              本章学习达成与结构复盘
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              第 {chapterIndex} 章 《{chapterTitle}》
            </p>
          </div>
        </div>
        <span className="rounded-full bg-emerald-100 dark:bg-emerald-950/60 border border-emerald-300 dark:border-emerald-800 px-3 py-1 text-xs font-bold text-emerald-800 dark:text-emerald-300">
          达成完成
        </span>
      </div>

      {/* 本章斩获核心概念 */}
      <div className="mt-4">
        <div className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-1.5">
          <span>🎯</span>
          <span>本章击穿核心概念</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {activeKps.map((kp) => (
            <span
              key={kp.id}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 px-2.5 py-1 text-xs text-gray-800 dark:text-gray-200 font-medium shadow-2xs"
            >
              <span className="text-emerald-600 font-bold">✓</span>
              <span>{kp.title}</span>
            </span>
          ))}
          {activeKps.length === 0 && (
            <span className="text-xs text-gray-400">（本章未提取出结构化知识点）</span>
          )}
        </div>
      </div>

      {/* 攻坚印记数据 */}
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-center">
        <div className="rounded-xl bg-white/80 dark:bg-gray-800/60 p-3 border border-gray-100 dark:border-gray-800">
          <div className="text-[11px] text-gray-400 dark:text-gray-500">闯关通过</div>
          <div className="text-base font-bold text-gray-800 dark:text-gray-200 mt-0.5">
            {passedCount} / {exercises.length} <span className="text-[11px] font-normal text-gray-400">关</span>
          </div>
        </div>
        <div className="rounded-xl bg-white/80 dark:bg-gray-800/60 p-3 border border-gray-100 dark:border-gray-800">
          <div className="text-[11px] text-gray-400 dark:text-gray-500">硬骨头攻坚</div>
          <div className="text-base font-bold text-amber-600 dark:text-amber-400 mt-0.5">
            {hardBoneCount} <span className="text-[11px] font-normal text-gray-400">关暂存</span>
          </div>
        </div>
        <div className="rounded-xl bg-white/80 dark:bg-gray-800/60 p-3 border border-gray-100 dark:border-gray-800">
          <div className="text-[11px] text-gray-400 dark:text-gray-500">个人批注与划线</div>
          <div className="text-base font-bold text-brand-600 dark:text-brand-400 mt-0.5">
            {annotationsCount} <span className="text-[11px] font-normal text-gray-400">处沉淀</span>
          </div>
        </div>
      </div>

      {/* 下一章预告与行动分流 */}
      <div className="mt-5 pt-4 border-t border-gray-100 dark:border-gray-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          {nextChapter ? (
            <p className="text-xs text-gray-600 dark:text-gray-400">
              <span className="font-semibold text-gray-800 dark:text-gray-200">下一章预告：</span>
              第 {nextChapter.chapter_index} 章 《{nextChapter.title}》
            </p>
          ) : (
            <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
              🏆 恭喜！你已学完全部章节！
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="secondary" className="text-xs !py-1.5" onClick={onGoHome}>
            ☕ 休息一下回到首页
          </Button>
          {nextChapter && onNextChapter && (
            <Button
              variant="primary"
              className="text-xs font-medium !py-1.5 !bg-brand-600 hover:!bg-brand-700 text-white shadow-xs"
              onClick={onNextChapter}
            >
              🚀 开启下一章
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
