// 标注抽屉：本文全部标注 + orphan 重新挂载（PRD FR-3.3 / §9.3）
import type { Annotation } from "../../lib/types";
import { Badge, Button } from "../../components/ui";

const COLOR_HEX: Record<string, string> = {
  yellow: "#fde68a",
  green: "#bbf7d0",
  blue: "#bfdbfe",
  pink: "#fbcfe8",
};

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
  return (
    <div className="fixed right-0 top-0 z-30 flex h-full w-80 flex-col border-l border-gray-200 bg-white shadow-lg">
      <div className="border-b border-gray-100 px-4 py-3 text-sm font-semibold text-gray-900">
        本文标注（{annotations.length}）
      </div>
      <div className="flex-1 space-y-2 overflow-auto p-3">
        {annotations.length === 0 && (
          <p className="mt-8 text-center text-xs text-gray-400">划选正文即可创建标注</p>
        )}
        {annotations.map((a) => (
          <div
            key={a.id}
            className={`rounded-lg border p-2.5 ${
              activeAnnId === a.id ? "border-brand-500" : "border-gray-200"
            } ${reAnchoring?.id === a.id ? "bg-amber-50" : "bg-white"}`}
          >
            <button className="flex w-full items-start gap-2 text-left" onClick={() => onOpen(a)}>
              <span
                className="mt-0.5 h-3 w-3 shrink-0 rounded-full"
                style={{ backgroundColor: COLOR_HEX[a.color] }}
              />
              <span className="line-clamp-2 flex-1 text-xs text-gray-700">{a.exact}</span>
            </button>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-[10px] text-gray-400">
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
                  className="text-[10px] text-gray-300 hover:text-red-500"
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
