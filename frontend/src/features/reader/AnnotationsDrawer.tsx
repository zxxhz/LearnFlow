// 标注抽屉：本文全部标注 + orphan 重新挂载（PRD FR-3.3 / §9.3）
import { useEffect, useState } from "react";
import type { Annotation } from "../../lib/types";
import { Badge, Button } from "../../components/ui";
import { useHlColors } from "./colors";

interface Props {
  annotations: Annotation[];
  activeAnnId: string | null;
  reAnchoring: Annotation | null;
  closing?: boolean;
  onOpen: (a: Annotation) => void;
  onStartReAnchor: (a: Annotation) => void;
  onDelete: (a: Annotation) => void;
  onClose: () => void;
}

export default function AnnotationsDrawer({
  annotations,
  activeAnnId,
  reAnchoring,
  closing = false,
  onOpen,
  onStartReAnchor,
  onDelete,
  onClose,
}: Props) {
  const hlColors = useHlColors();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setMounted(true);
    }, 20);
    return () => clearTimeout(timer);
  }, []);

  const isVisible = mounted && !closing;

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl sm:w-[420px] transition-transform duration-300 ease-out transform ${
        isVisible ? "translate-x-0" : "translate-x-full"
      }`}
    >
      <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">本文标注</span>
          <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-500 dark:text-gray-400">
            {annotations.length}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
          title="关闭"
          aria-label="关闭"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 space-y-2 overflow-auto p-3">
        {annotations.length === 0 && (
          <p className="mt-8 text-center text-xs text-gray-400 dark:text-gray-500">划选正文即可创建标注</p>
        )}
        {annotations.map((a) => (
          <div
            key={a.id}
            className={`rounded-lg border p-2.5 transition-colors ${
              activeAnnId === a.id
                ? "border-brand-500 dark:border-brand-400 bg-brand-50/20 dark:bg-brand-950/20"
                : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600"
            } ${reAnchoring?.id === a.id ? "bg-amber-50 dark:bg-amber-900/30" : "bg-white dark:bg-gray-900"}`}
          >
            <button className="flex w-full items-start gap-2 text-left" onClick={() => onOpen(a)}>
              <span
                className="mt-0.5 h-3 w-3 shrink-0 rounded-full shadow-sm"
                style={{ backgroundColor: hlColors[a.color] }}
              />
              <span className="line-clamp-2 flex-1 text-xs text-gray-700 dark:text-gray-300 leading-relaxed">
                {a.exact}
              </span>
            </button>
            <div className="mt-2 flex items-center justify-between border-t border-gray-100 dark:border-gray-800/80 pt-1.5">
              <div className="flex items-center gap-1.5 overflow-hidden">
                <span className="text-[10px] text-gray-400 dark:text-gray-500">
                  {new Date(a.created_at).toLocaleDateString("zh-CN")}
                </span>
                {a.note && (
                  <span className="truncate max-w-[120px] rounded bg-gray-100 dark:bg-gray-800 px-1 py-0.5 text-[9px] font-medium text-brand-600 dark:text-brand-400">
                    {a.note}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                {a.status === "orphan" && <Badge color="red">原文已变更</Badge>}
                {a.status === "orphan" && reAnchoring?.id !== a.id && (
                  <Button variant="ghost" className="text-[10px]" onClick={() => onStartReAnchor(a)}>
                    重新挂载
                  </Button>
                )}
                <button
                  className="text-[10px] text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 px-1 py-0.5"
                  onClick={() => onDelete(a)}
                  title="删除标注"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
