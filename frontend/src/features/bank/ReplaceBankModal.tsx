import { useRef, useState } from "react";
import { Modal, Button, Spinner, ErrorText, Badge } from "../../components/ui";
import { api } from "../../lib/api";
import type { Bank, BankReplaceAnalyzeOut } from "../../lib/types";

interface Props {
  open: boolean;
  bankId: string;
  bankName: string;
  currentCount: number;
  onClose: () => void;
  onSuccess: (updatedBank: Bank) => void;
}

export default function ReplaceBankModal({
  open,
  bankId,
  bankName,
  currentCount,
  onClose,
  onSuccess,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const analyzeReqRef = useRef(0);
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<BankReplaceAnalyzeOut | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [tab, setTab] = useState<"recalibrated" | "added" | "removed">("recalibrated");

  const handleReset = () => {
    analyzeReqRef.current++;
    setFile(null);
    setAnalysis(null);
    setIsAnalyzing(false);
    setIsSubmitting(false);
    setErrorMsg("");
    onClose();
  };

  const handleFileSelect = async (selectedFile?: File) => {
    if (!selectedFile) return;
    const reqId = ++analyzeReqRef.current;
    setFile(selectedFile);
    setAnalysis(null);
    setErrorMsg("");
    setIsAnalyzing(true);
    try {
      const res = await api.banks.replaceAnalyze(bankId, selectedFile);
      if (reqId !== analyzeReqRef.current) return;
      setAnalysis(res);
      // 如果没有答案变更题，默认切到新增或移出
      if (res.recalibrated_count === 0 && res.added_count > 0) {
        setTab("added");
      } else if (res.recalibrated_count === 0 && res.removed_count > 0) {
        setTab("removed");
      }
    } catch (e) {
      if (reqId !== analyzeReqRef.current) return;
      setErrorMsg((e as Error).message);
    } finally {
      if (reqId === analyzeReqRef.current) {
        setIsAnalyzing(false);
      }
    }
  };

  const handleConfirmReplace = async () => {
    if (!file) {
      setErrorMsg("请先选择新题库表格文件");
      return;
    }
    setErrorMsg("");
    setIsSubmitting(true);
    try {
      const res = await api.banks.replace(bankId, file);
      // 成功替换后，清理该题库旧的未完成轮草稿（防止引用已移除的旧题目 ID 导致 404）
      try {
        localStorage.removeItem(`learnflow.bank-drill.${bankId}`);
      } catch {
        /* ignore */
      }
      onSuccess(res);
      handleReset();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={handleReset} title={`🔄 替换 / 精简「${bankName}」题库表格`} width="max-w-2xl">
      <div className="space-y-4 max-h-[75vh] overflow-y-auto pr-1 text-xs">
        <input
          ref={fileRef}
          type="file"
          accept=".xls,.xlsx"
          className="hidden"
          onChange={(e) => {
            handleFileSelect(e.target.files?.[0]);
            e.target.value = "";
          }}
        />

        {!file || (!analysis && !isAnalyzing) ? (
          <div className="space-y-3">
            <div className="rounded-xl bg-brand-50/60 dark:bg-brand-950/30 p-3 border border-brand-200/80 dark:border-brand-900/60 text-brand-800 dark:text-brand-300 leading-relaxed">
              <div className="font-semibold flex items-center gap-1.5 mb-1">
                <span>💡</span>
                <span>为什么使用「替换题库表格」？</span>
              </div>
              <p>
                如果您觉得题库题目过多、存在冗余或无用题目，可以上传一份精简/修订后的新表格覆盖当前题库。
                系统将自动根据题目题干与选项<strong>精准对齐匹配</strong>：
                <strong>新表格中保留的题目，您此前做过的作答状态、正确率与错题记录将 100% 完整继承保留</strong>，未做题作为新题，被移出的题目干净清理。
              </p>
            </div>

            {errorMsg && (
              <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400">
                ❌ 表格比对失败：{errorMsg}
                <div className="mt-1 text-[11px] text-gray-500">
                  请检查表格列布局是否规范（题型/题干/选项A-H/答案/解析/难度），或点击下方按钮重新选文件。
                </div>
              </div>
            )}

            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex w-full flex-col items-center gap-2.5 rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 py-12 text-gray-500 dark:text-gray-400 hover:border-brand-400 hover:text-brand-600 dark:hover:text-brand-400 transition bg-gray-50/40 dark:bg-gray-800/20"
            >
              <span className="text-3xl">📄</span>
              <span className="text-sm font-medium">
                {file ? `已选文件：${file.name}（点击重新选择）` : "点击选择新版 .xls / .xlsx 题库表格文件"}
              </span>
              <span className="text-xs text-gray-400 dark:text-gray-500">
                当前题库共有 {currentCount} 道题目；新表格支持单选、多选与判断题
              </span>
            </button>
          </div>
        ) : isAnalyzing ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-sm text-gray-500 dark:text-gray-400">
            <Spinner className="h-6 w-6" />
            <span>正在比对新旧题目与作答历史状态，请稍候…</span>
          </div>
        ) : analysis ? (
          <div className="space-y-4 animate-fadeIn">
            {/* 文件概览 */}
            <div className="flex items-center justify-between rounded-xl bg-gray-50 dark:bg-gray-800/60 p-3 border border-gray-200 dark:border-gray-700">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-gray-900 dark:text-gray-100">
                  📎 新表格：{analysis.new_source_file}
                </p>
                <p className="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">
                  原总题数：<strong className="text-gray-700 dark:text-gray-300">{analysis.current_total}</strong> 题 ➔ 
                  替换后总题数：<strong className="text-brand-600 dark:text-brand-400 font-bold">{analysis.new_total}</strong> 题
                  {analysis.new_total < analysis.current_total && (
                    <span className="ml-1 text-emerald-600 dark:text-emerald-400 font-medium">
                      （精简了 {analysis.current_total - analysis.new_total} 题）
                    </span>
                  )}
                </p>
              </div>
              <Button
                variant="ghost"
                className="shrink-0 text-xs ml-2"
                onClick={() => {
                  setFile(null);
                  setAnalysis(null);
                }}
              >
                重选文件
              </Button>
            </div>

            {/* 四色指标看板 */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              <div className="rounded-xl border border-green-200 dark:border-green-800/70 bg-green-50/60 dark:bg-green-950/20 p-2.5">
                <div className="text-green-700 dark:text-green-300 font-semibold flex items-center justify-between">
                  <span>🟢 继承保留</span>
                  <span className="text-base font-bold">{analysis.matched_count}</span>
                </div>
                <div className="mt-1 text-[11px] text-green-800/80 dark:text-green-400 leading-tight">
                  含 <strong className="underline">{analysis.answered_retained}</strong> 题已作答状态
                </div>
              </div>

              <div className="rounded-xl border border-blue-200 dark:border-blue-800/70 bg-blue-50/60 dark:bg-blue-950/20 p-2.5">
                <div className="text-blue-700 dark:text-blue-300 font-semibold flex items-center justify-between">
                  <span>🔵 答案校正</span>
                  <span className="text-base font-bold">{analysis.recalibrated_count}</span>
                </div>
                <div className="mt-1 text-[11px] text-blue-800/80 dark:text-blue-400 leading-tight">
                  答案变更自动重判出池
                </div>
              </div>

              <div className="rounded-xl border border-amber-200 dark:border-amber-800/70 bg-amber-50/60 dark:bg-amber-950/20 p-2.5">
                <div className="text-amber-700 dark:text-amber-300 font-semibold flex items-center justify-between">
                  <span>🟠 精简移出</span>
                  <span className="text-base font-bold">{analysis.removed_count}</span>
                </div>
                <div className="mt-1 text-[11px] text-amber-800/80 dark:text-amber-400 leading-tight">
                  新表格已淘汰剔除
                </div>
              </div>

              <div className="rounded-xl border border-purple-200 dark:border-purple-800/70 bg-purple-50/60 dark:bg-purple-950/20 p-2.5">
                <div className="text-purple-700 dark:text-purple-300 font-semibold flex items-center justify-between">
                  <span>🟣 全新题目</span>
                  <span className="text-base font-bold">{analysis.added_count}</span>
                </div>
                <div className="mt-1 text-[11px] text-purple-800/80 dark:text-purple-400 leading-tight">
                  作为未做新题待刷
                </div>
              </div>
            </div>

            {/* 变动明细预览抽屉 */}
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/40 p-3 space-y-2.5">
              <div className="flex border-b border-gray-100 dark:border-gray-700/60 pb-1.5 gap-3">
                <button
                  type="button"
                  onClick={() => setTab("recalibrated")}
                  className={`font-semibold pb-1 transition ${
                    tab === "recalibrated"
                      ? "text-brand-600 border-b-2 border-brand-600"
                      : "text-gray-500 hover:text-gray-700"
                  }`}
                >
                  答案校准项 ({analysis.recalibrated_count})
                </button>
                <button
                  type="button"
                  onClick={() => setTab("added")}
                  className={`font-semibold pb-1 transition ${
                    tab === "added"
                      ? "text-brand-600 border-b-2 border-brand-600"
                      : "text-gray-500 hover:text-gray-700"
                  }`}
                >
                  新增题目项 ({analysis.added_count})
                </button>
                <button
                  type="button"
                  onClick={() => setTab("removed")}
                  className={`font-semibold pb-1 transition ${
                    tab === "removed"
                      ? "text-brand-600 border-b-2 border-brand-600"
                      : "text-gray-500 hover:text-gray-700"
                  }`}
                >
                  移出淘汰项 ({analysis.removed_count})
                </button>
              </div>

              <div className="max-h-40 overflow-y-auto pr-1 space-y-1.5">
                {tab === "recalibrated" && (
                  analysis.samples_recalibrated.length === 0 ? (
                    <div className="py-4 text-center text-gray-400">所有匹配题目的参考答案均保持一致</div>
                  ) : (
                    analysis.samples_recalibrated.map((item, idx) => (
                      <div key={idx} className="p-2 rounded bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 space-y-1">
                        <div className="truncate font-medium text-gray-800 dark:text-gray-200">{item.title}</div>
                        <div className="flex items-center gap-2 text-[11px] text-gray-500">
                          <span>原答案：<del className="text-red-500">{item.old_answer}</del></span>
                          <span>➔ 新答案：<strong className="text-emerald-600 font-bold">{item.new_answer}</strong></span>
                          {item.user_answer && (
                            <span className="ml-auto">
                              你曾作答：<strong>{item.user_answer}</strong>
                              {item.recalibrated_passed ? (
                                <Badge color="green" className="ml-1 text-[10px]">校正为答对(出池)</Badge>
                              ) : (
                                <Badge color="red" className="ml-1 text-[10px]">仍未答对</Badge>
                              )}
                            </span>
                          )}
                        </div>
                      </div>
                    ))
                  )
                )}

                {tab === "added" && (
                  analysis.samples_added.length === 0 ? (
                    <div className="py-4 text-center text-gray-400">新表格没有引入额外全新题目</div>
                  ) : (
                    analysis.samples_added.map((t, idx) => (
                      <div key={idx} className="p-1.5 rounded bg-gray-50 dark:bg-gray-800/60 text-gray-700 dark:text-gray-300 truncate">
                        #{idx + 1} {t}
                      </div>
                    ))
                  )
                )}

                {tab === "removed" && (
                  analysis.samples_removed.length === 0 ? (
                    <div className="py-4 text-center text-gray-400">原题库没有题目被剔除</div>
                  ) : (
                    analysis.samples_removed.map((t, idx) => (
                      <div key={idx} className="p-1.5 rounded bg-gray-50 dark:bg-gray-800/60 text-gray-500 line-through truncate">
                        #{idx + 1} {t}
                      </div>
                    ))
                  )
                )}
              </div>
            </div>

            <div className="text-[11px] text-gray-500 dark:text-gray-400 bg-amber-50/50 dark:bg-amber-950/20 p-2 rounded-lg border border-amber-200/60 dark:border-amber-900/40">
              ⚠️ 确认替换后，题库将全量切换为新表格结构；被移出的题目及其历史流水将被清理，匹配保留的 <strong>{analysis.answered_retained}</strong> 题作答记录完好如初。
            </div>
          </div>
        ) : null}

        {errorMsg && <ErrorText>{errorMsg}</ErrorText>}

        <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <Button variant="ghost" onClick={handleReset} className="text-xs">
            取消
          </Button>
          <Button
            variant="primary"
            disabled={isSubmitting || !file || isAnalyzing}
            onClick={handleConfirmReplace}
            className="text-xs font-medium"
          >
            {isSubmitting ? (
              <>
                <Spinner className="h-3 w-3 inline mr-1.5" />
                正在执行替换并继承状态…
              </>
            ) : (
              `确认替换题库${analysis ? ` (保留 ${analysis.answered_retained} 题作答状态)` : ""}`
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
