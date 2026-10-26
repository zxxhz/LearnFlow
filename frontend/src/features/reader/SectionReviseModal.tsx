import { useState } from "react";
import { Modal, Button, Textarea, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import type { SectionReviseResponse } from "../../lib/types";

interface SectionReviseModalProps {
  isOpen: boolean;
  onClose: () => void;
  documentId: string;
  sectionId: string;
  sectionRaw: string;
  onSuccess: (updatedMarkdown?: string | null) => void;
}

const QUICK_CHIPS = [
  { label: "📐 公式推导存疑", prompt: "请严密核对本段涉及的数学符号、公式展开与推导结论是否有误" },
  { label: "⚠️ 结论与事实相反", prompt: "请严肃核对本段核心概念与结论是否与权威教材存在矛盾或误导" },
  { label: "💻 代码逻辑有缺陷", prompt: "请逐行审校本段代码示例，核查语法、边界条件或输出是否异常" },
  { label: "💡 解释生硬，求通俗化", prompt: "本段概念解释较生硬，请结合具体生动比喻与直观逻辑予以通俗化重构" },
];

export function SectionReviseModal({
  isOpen,
  onClose,
  documentId,
  sectionId,
  sectionRaw,
  onSuccess,
}: SectionReviseModalProps) {
  const [instruction, setInstruction] = useState("");
  const [isReviewing, setIsReviewing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [reviewResult, setReviewResult] = useState<SectionReviseResponse | null>(null);
  const [editedMarkdown, setEditedMarkdown] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const handleReview = async () => {
    if (!instruction.trim()) {
      setErrorMsg("请先填写具体的质疑理由或重写要求");
      return;
    }
    setErrorMsg("");
    setIsReviewing(true);
    try {
      const res = await api.documents.reviseSection(documentId, sectionId, {
        instruction: instruction.trim(),
        apply: false,
      });
      setReviewResult(res);
      setEditedMarkdown(res.revised_markdown);
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsReviewing(false);
    }
  };

  const handleApply = async () => {
    if (!editedMarkdown.trim()) {
      setErrorMsg("修订后的正文不能为空");
      return;
    }
    setErrorMsg("");
    setIsApplying(true);
    try {
      const res = await api.documents.reviseSection(documentId, sectionId, {
        instruction: instruction.trim(),
        apply: true,
        revised_markdown: editedMarkdown.trim(),
      });
      onSuccess(res.updated_full_markdown);
      onClose();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsApplying(false);
    }
  };

  const resetAll = () => {
    setInstruction("");
    setReviewResult(null);
    setEditedMarkdown("");
    setErrorMsg("");
    onClose();
  };

  return (
    <Modal open={isOpen} onClose={resetAll} title="🚩 段落核验与手术式重写">
      <div className="space-y-4 max-h-[75vh] overflow-y-auto pr-1">
        {/* 原段落引用 */}
        <div>
          <label className="text-xs font-semibold text-gray-500 dark:text-gray-400">
            待核查段落原文
          </label>
          <div className="mt-1 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-800/40 p-3 text-xs text-gray-700 dark:text-gray-300 font-mono leading-relaxed line-clamp-4">
            {sectionRaw}
          </div>
        </div>

        {/* 快捷理由预填 */}
        <div>
          <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
            快捷预设要求（点击填入）：
          </div>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_CHIPS.map((chip, i) => (
              <button
                key={i}
                type="button"
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-2 py-1 text-[11px] text-gray-700 dark:text-gray-300 hover:border-brand-300 hover:text-brand-600 dark:hover:border-brand-700 dark:hover:text-brand-400 transition"
                onClick={() => setInstruction(chip.prompt)}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>

        {/* 质疑输入框 */}
        <div>
          <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">
            质疑或调整说明 <span className="text-red-500">*</span>
          </label>
          <Textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="请详细说明你质疑的地方（如：某某推导少了一个负号；或者希望多给一个生动代码示例）"
            className="mt-1.5 h-20 text-xs resize-none"
          />
        </div>

        {/* 触发审校按钮 */}
        {!reviewResult && (
          <div className="flex justify-end pt-2">
            <Button
              variant="primary"
              disabled={isReviewing || !instruction.trim()}
              onClick={handleReview}
              className="text-xs font-medium"
            >
              {isReviewing ? (
                <>
                  <Spinner className="h-3 w-3 inline mr-1.5" />
                  AI 正在交叉核验审校…
                </>
              ) : (
                "🤖 AI 客观审校并生成修订方案"
              )}
            </Button>
          </div>
        )}

        {/* 审校与方案展示区域 */}
        {reviewResult && (
          <div className="rounded-xl border border-brand-200 dark:border-brand-800/60 bg-brand-50/20 dark:bg-brand-950/20 p-4 space-y-3.5 mt-2 animate-fadeIn">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-gray-900 dark:text-gray-100">
                  审校结论
                </span>
                {reviewResult.verification_status === "confirmed_error" ? (
                  <span className="rounded-full bg-rose-100 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-800 px-2.5 py-0.5 text-[11px] font-bold text-rose-700 dark:text-rose-300">
                    ⚠️ 证实存在错误或缺陷
                  </span>
                ) : reviewResult.verification_status === "verified_correct" ? (
                  <span className="rounded-full bg-emerald-100 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800 px-2.5 py-0.5 text-[11px] font-bold text-emerald-700 dark:text-emerald-300">
                    ✓ 原理核验正确（增补说明）
                  </span>
                ) : (
                  <span className="rounded-full bg-blue-100 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800 px-2.5 py-0.5 text-[11px] font-bold text-blue-700 dark:text-blue-300">
                    ✨ 优化重构方案
                  </span>
                )}
              </div>
              <Button
                variant="ghost"
                className="!py-0.5 text-[11px] text-gray-400 hover:text-gray-600"
                onClick={handleReview}
                disabled={isReviewing}
              >
                ↻ 重新审校
              </Button>
            </div>

            <p className="text-xs text-gray-700 dark:text-gray-300 leading-relaxed bg-white/70 dark:bg-gray-800/60 rounded-lg p-2.5 border border-brand-100 dark:border-brand-900/40">
              {reviewResult.explanation}
            </p>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                  修订后内容（直接替换原文，可就地二次编辑）：
                </label>
              </div>
              <Textarea
                value={editedMarkdown}
                onChange={(e) => setEditedMarkdown(e.target.value)}
                className="h-32 text-xs font-mono leading-relaxed"
              />
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-brand-100 dark:border-brand-900/40">
              <span className="text-[11px] text-gray-400">
                将仅替换当前段落，不破坏前后章节与已有划线。
              </span>
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={resetAll} className="text-xs">
                  取消
                </Button>
                <Button
                  variant="primary"
                  disabled={isApplying || !editedMarkdown.trim()}
                  onClick={handleApply}
                  className="text-xs font-medium !bg-brand-600 hover:!bg-brand-700 text-white"
                >
                  {isApplying ? (
                    <>
                      <Spinner className="h-3 w-3 inline mr-1" />
                      应用替换中…
                    </>
                  ) : (
                    "✅ 确认替换到讲义"
                  )}
                </Button>
              </div>
            </div>
          </div>
        )}

        {errorMsg && (
          <p className="text-xs text-red-600 dark:text-red-400 pt-1">
            ❌ {errorMsg}
          </p>
        )}
      </div>
    </Modal>
  );
}
