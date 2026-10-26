// 划选后的浮动工具条：提问 / 记批注 / 纯高亮 / 四色（PRD FR-3.1 + §5 个人独立批注）
import { useEffect, useRef, useState } from "react";
import type { AnchorRange } from "../../lib/anchor";
import type { AnnotationColor } from "../../lib/types";
import { useHlColors } from "./colors";

const COLORS: AnnotationColor[] = ["yellow", "green", "blue", "pink"];

interface Props {
  anchor: AnchorRange;
  rect: { top: number; left: number; width: number };
  color: AnnotationColor;
  busy: boolean;
  onColorChange: (c: AnnotationColor) => void;
  onAsk: () => void;
  onHighlight: () => void;
  onNote: (noteText: string) => void;
}

export default function SelectionToolbar({
  anchor,
  rect,
  color,
  busy,
  onColorChange,
  onAsk,
  onHighlight,
  onNote,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const hlColors = useHlColors();
  const [isWritingNote, setIsWritingNote] = useState(false);
  const [noteText, setNoteText] = useState("");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const h = el.offsetHeight || 40;
    const w = el.offsetWidth || 260;
    let top = rect.top - h - 8;
    let left = rect.left + rect.width / 2 - w / 2;
    if (top < 8) top = rect.top + 32;
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    el.style.top = `${top}px`;
    el.style.left = `${left}px`;
  }, [rect, anchor, isWritingNote]);

  useEffect(() => {
    if (isWritingNote) {
      inputRef.current?.focus();
    }
  }, [isWritingNote]);

  const handleNoteSubmit = () => {
    const trimmed = noteText.trim();
    if (!trimmed) return;
    onNote(trimmed);
  };

  if (isWritingNote) {
    return (
      <div
        ref={ref}
        className="fixed z-40 flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2.5 py-1.5 shadow-xl animate-fadeIn"
      >
        <span className="text-xs">📝</span>
        <input
          ref={inputRef}
          type="text"
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleNoteSubmit();
            } else if (e.key === "Escape") {
              setIsWritingNote(false);
            }
          }}
          placeholder="输入个人随笔批注（回车保存）…"
          className="w-52 text-xs bg-transparent border-none outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400"
        />
        <button
          disabled={busy || !noteText.trim()}
          onClick={handleNoteSubmit}
          className="rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          保存
        </button>
        <button
          onClick={() => setIsWritingNote(false)}
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xs px-1"
          title="取消"
        >
          ✕
        </button>
      </div>
    );
  }

  return (
    <div
      ref={ref}
      className="fixed z-40 flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-2 py-1.5 shadow-lg"
    >
      <button
        disabled={busy}
        onClick={onAsk}
        className="rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        title="向 AI 助教提问并发起研讨对话"
      >
        💡 提问
      </button>
      <button
        disabled={busy}
        onClick={() => setIsWritingNote(true)}
        className="rounded-md px-2 py-1 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
        title="仅记录随笔批注，不发起 AI 对话，0 Token 消耗"
      >
        📝 批注
      </button>
      <button
        disabled={busy}
        onClick={onHighlight}
        className="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
        title="纯划线高亮"
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
            backgroundColor: hlColors[c],
            borderColor: hlColors[c],
          }}
          title={c}
        />
      ))}
    </div>
  );
}
