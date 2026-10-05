// 目录侧栏：标题树 + 当前位置高亮（PRD FR-2.2）
import { useEffect, useState } from "react";
import type { ParsedBlock } from "../../lib/markdown";
import type { ChapterProgress } from "../../lib/types";

export interface TocItem {
  sectionId: string;
  text: string;
  level: number;
}

export function buildToc(blocks: ParsedBlock[], idOf: (i: number) => string | undefined): TocItem[] {
  const items: TocItem[] = [];
  blocks.forEach((b, i) => {
    if (b.type === "heading" && b.headingText) {
      const sid = idOf(i);
      if (sid) items.push({ sectionId: sid, text: b.headingText, level: b.headingLevel ?? 1 });
    }
  });
  return items;
}

export default function TocSidebar({
  items,
  chapters,
  currentDocId,
  onJump,
  onSelectChapter,
}: {
  items: TocItem[];
  chapters?: ChapterProgress[];
  currentDocId?: string;
  onJump: (sectionId: string) => void;
  onSelectChapter?: (docId: string) => void;
}) {
  const [activeId, setActiveId] = useState<string>("");

  useEffect(() => {
    const headings = items
      .map((it) => document.querySelector(`[data-section-id="${it.sectionId}"]`))
      .filter((el): el is Element => !!el);
    if (headings.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setActiveId((e.target as HTMLElement).dataset.sectionId ?? "");
            break;
          }
        }
      },
      { rootMargin: "-64px 0px -70% 0px", threshold: 0 }
    );
    headings.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  // 如果传入了多章节，以章节列表为主，当前章展开显示节目录
  if (chapters && chapters.length > 0) {
    return (
      <nav className="space-y-1 text-sm">
        <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
          课程大纲与目录
        </div>
        {chapters.map((ch) => {
          const isCurrent = ch.document_id === currentDocId;
          return (
            <div key={ch.document_id} className="space-y-0.5">
              <button
                onClick={() => {
                  if (!isCurrent && onSelectChapter) {
                    onSelectChapter(ch.document_id);
                  }
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition ${
                  isCurrent
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300 font-semibold"
                    : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
                }`}
                title={ch.title}
              >
                <span className="shrink-0 text-xs font-bold text-gray-400 dark:text-gray-500">
                  {ch.chapter_index}.
                </span>
                <span className="truncate flex-1">{ch.title}</span>
                {ch.status === "generating" && (
                  <span className="shrink-0 rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-600 dark:bg-blue-900/40 dark:text-blue-300">
                    生成中
                  </span>
                )}
              </button>

              {/* 当前章节展开显示小节目录 */}
              {isCurrent && items.length > 0 && (
                <div className="ml-3 my-1 border-l-2 border-brand-200 dark:border-brand-800/60 pl-2 space-y-0.5">
                  {items.map((it) => (
                    <button
                      key={it.sectionId}
                      onClick={() => onJump(it.sectionId)}
                      className={`block w-full truncate rounded px-2 py-1.5 text-left text-xs transition ${
                        activeId === it.sectionId
                          ? "font-medium text-brand-700 dark:text-brand-300 bg-brand-50/60 dark:bg-brand-900/30"
                          : "text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
                      }`}
                      style={{ paddingLeft: `${Math.max(0, (it.level - 1) * 8)}px` }}
                      title={it.text}
                    >
                      {it.text}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    );
  }

  return (
    <nav className="space-y-0.5 text-sm">
      <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        目录
      </div>
      {items.length === 0 && <p className="px-3 text-xs text-gray-400 dark:text-gray-500">（无标题）</p>}
      {items.map((it) => (
        <button
          key={it.sectionId}
          onClick={() => onJump(it.sectionId)}
          className={`block w-full truncate rounded-md px-3 py-1.5 text-left transition ${
            activeId === it.sectionId
              ? "bg-brand-50 dark:bg-brand-900/40 font-medium text-brand-700 dark:text-brand-300"
              : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
          }`}
          style={{ paddingLeft: `${12 + (it.level - 1) * 12}px` }}
          title={it.text}
        >
          {it.text}
        </button>
      ))}
    </nav>
  );
}
