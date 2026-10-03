// 标注抽屉：本文全部标注 + orphan 重新挂载（PRD FR-3.3 / §9.3）
import type { Annotation } from "../../lib/types";
import { Badge, Button } from "../../components/ui";
import { useHlColors } from "./colors";

interface Props {
  annotations: Annotation[];
  activeAnnId: string | null;
  reAnchoring: Annotation | null;
  onOpen: (a: Annotation) => void;
  onStartReAnchor: (a: Annotation) => void;
  onDelete: (a: Annotation) => void;
}

export default function AnnotationsDrawer({
  annotations,
  activeAnnId,
  reAnchoring,
  onOpen,
  onStartReAnchor,
  onDelete,
}: Props) {
  const hlColors = useHlColors();
  return (
    <div className="fixed right-0 top-0 z-30 flex h-full w-full flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg sm:w-80">
      <div className="border-b border-gray-100 dark:border-gray-800 px-4 py-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
        本文标注（{annotations.length}）
      </div>
      <div className="flex-1 space-y-2 overflow-auto p-3">
        {annotations.length === 0 && (
          <p className="mt-8 text-center text-xs text-gray-400 dark:text-gray-500">划选正文即可创建标注</p>
        )}
        {annotations.map((a) => (
          <div
            key={a.id}
            className={`rounded-lg border p-2.5 ${
              activeAnnId === a.id ? "border-brand-500 dark:border-brand-400" : "border-gray-200 dark:border-gray-700"
            } ${reAnchoring?.id === a.id ? "bg-amber-50 dark:bg-amber-900/30" : "bg-white dark:bg-gray-900"}`}
          >
            <button className="flex w-full items-start gap-2 text-left" onClick={() => onOpen(a)}>
              <span
                className="mt-0.5 h-3 w-3 shrink-0 rounded-full"
                style={{ backgroundColor: hlColors[a.color] }}
              />
              <span className="line-clamp-2 flex-1 text-xs text-gray-700 dark:text-gray-300">{a.exact}</span>
            </button>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-[10px] text-gray-400 dark:text-gray-500">
                {new Date(a.created_at).toLocaleDateString("zh-CN")}
              </span>
              <div className="flex items-center gap-1">
                {a.status === "orphan" && <Badge color="red">原文已变更</Badge>}
                {a.status === "orphan" && reAnchoring?.id !== a.id && (
                  <Button variant="ghost" className="text-[10px]" onClick={() => onStartReAnchor(a)}>
                    重新挂载
                  </Button>
                )}
                <button
                  className="text-[10px] text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400"
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
