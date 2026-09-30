// 目录侧栏：标题树 + 当前位置高亮（PRD FR-2.2）
import { useEffect, useState } from "react";
import type { ParsedBlock } from "../../lib/markdown";

interface TocItem {
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
  onJump,
}: {
  items: TocItem[];
  onJump: (sectionId: string) => void;
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

  return (
    <nav className="space-y-0.5 text-sm">
      <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-gray-400">目录</div>
      {items.length === 0 && <p className="px-3 text-xs text-gray-400">（无标题）</p>}
      {items.map((it) => (
        <button
          key={it.sectionId}
          onClick={() => onJump(it.sectionId)}
          className={`block w-full truncate rounded-md px-3 py-1.5 text-left transition ${
            activeId === it.sectionId
              ? "bg-brand-50 font-medium text-brand-700"
              : "text-gray-600 hover:bg-gray-100"
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
