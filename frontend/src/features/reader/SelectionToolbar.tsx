// 划选后的浮动工具条：提问 / 高亮 / 四色（PRD FR-3.1）
import { useEffect, useRef } from "react";
import type { AnchorRange } from "../../lib/anchor";
import type { AnnotationColor } from "../../lib/types";

const COLORS: AnnotationColor[] = ["yellow", "green", "blue", "pink"];

interface Props {
  anchor: AnchorRange;
  rect: { top: number; left: number; width: number };
  color: AnnotationColor;
  busy: boolean;
  onColorChange: (c: AnnotationColor) => void;
  onAsk: () => void;
  onHighlight: () => void;
}

export default function SelectionToolbar({
  anchor,
  rect,
  color,
  busy,
  onColorChange,
  onAsk,
  onHighlight,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const h = el.offsetHeight || 40;
    const w = el.offsetWidth || 220;
    let top = rect.top - h - 8;
    let left = rect.left + rect.width / 2 - w / 2;
    if (top < 8) top = rect.top + 32;
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    el.style.top = `${top}px`;
    el.style.left = `${left}px`;
  }, [rect, anchor]);

  return (
    <div
      ref={ref}
      className="fixed z-40 flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1.5 shadow-lg"
    >
      <button
        disabled={busy}
        onClick={onAsk}
        className="rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
      >
        提问
      </button>
      <button
        disabled={busy}
        onClick={onHighlight}
        className="rounded-md px-2 py-1 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
      >
        高亮
      </button>
      <span className="mx-1 h-4 w-px bg-gray-200 dark:bg-gray-700" />
      {COLORS.map((c) => (
        <button
          key={c}
          onClick={() => onColorChange(c)}
          className={`h-4 w-4 rounded-full border ${color === c ? "ring-2 ring-brand-500 ring-offset-1" : ""}`}
          style={{
            backgroundColor: { yellow: "#fde68a", green: "#bbf7d0", blue: "#bfdbfe", pink: "#fbcfe8" }[c],
          }}
          title={c}
        />
      ))}
    </div>
  );
}
