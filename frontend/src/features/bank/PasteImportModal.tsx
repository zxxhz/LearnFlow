import { useState } from "react";
import { Modal, Button, Textarea, Input, Spinner, Badge } from "../../components/ui";
import { api } from "../../lib/api";
import type { Bank, ParsedTextQuestionItem } from "../../lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (bank: Bank) => void;
}

const SAMPLE_TEXT = `1. 下列关于虚拟内存的描述中，错误的是（ ）
A. 虚拟地址空间大小可以超过实际物理内存容量
B. 页表通常全部常驻在磁盘扇区中
C. TLB 是页表的高速缓存，用于加速虚实地址转换
D. 缺页异常属于内中断（陷入/故障）
答案：B
解析：页表由操作系统内核维护，常驻在主存（物理内存）中，仅在内存极度紧张时部分换出。

2. 下列哪些机制可以用来避免多线程竞态条件？（ ）
A. 互斥锁（std::mutex）
B. 原子操作（std::atomic）
C. 读写锁（std::shared_mutex）
D. 忙等待普通布尔变量
答案：A,B,C
解析：普通布尔变量在多线程下存在可见性与指令重排问题，必须使用原子操作或同步锁。

3. C++ 中 std::shared_ptr 的内部引用计数增减是线程安全的。（ ）
答案：正确
解析：引用计数的增减是通过原子操作实现的，但所指向的对象本身的访问并不是线程安全的。`;

const TYPE_NAME: Record<string, string> = {
  single: "单选题",
  multi: "多选题",
  judge: "判断题",
};

export default function PasteImportModal({ open, onClose, onSuccess }: Props) {
  const [rawText, setRawText] = useState("");
  const [bankTitle, setBankTitle] = useState("");
  const [isParsing, setIsParsing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [questions, setQuestions] = useState<ParsedTextQuestionItem[] | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  const handleParse = async () => {
    if (!rawText.trim()) {
      setErrorMsg("请先粘贴试题文本内容");
      return;
    }
    setErrorMsg("");
    setIsParsing(true);
    try {
      const res = await api.banks.pasteParse(rawText.trim());
      setBankTitle(res.bank_title || "剪贴板切题题库");
      setQuestions(res.questions);
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsParsing(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!questions || questions.length === 0) {
      setErrorMsg("没有可导入的试题");
      return;
    }
    setErrorMsg("");
    setIsImporting(true);
    try {
      const res = await api.banks.pasteImport(bankTitle.trim() || "剪贴板切题题库", questions);
      onSuccess(res);
      handleReset();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsImporting(false);
    }
  };

  const handleReset = () => {
    setRawText("");
    setBankTitle("");
    setQuestions(null);
    setErrorMsg("");
    onClose();
  };

  const handleDeleteItem = (index: number) => {
    if (!questions) return;
    setQuestions(questions.filter((_, i) => i !== index));
  };

  return (
    <Modal open={open} onClose={handleReset} title="📋 粘贴文本一键切题入库">
      <div className="space-y-4 max-h-[75vh] overflow-y-auto pr-1">
        {!questions ? (
          <>
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                支持直接粘贴从讲义、网页、课件或聊天群复制的散乱试题文本，AI 自动切分题干、选项与答案。
              </p>
              <button
                type="button"
                className="text-xs text-brand-600 dark:text-brand-400 hover:underline shrink-0 ml-2"
                onClick={() => setRawText(SAMPLE_TEXT)}
              >
                填入示例试题
              </button>
            </div>

            <Textarea
              rows={12}
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              placeholder="在此粘贴包含单选、多选或判断题的任意杂乱纯文本…"
              className="text-xs font-mono"
            />

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={handleReset} className="text-xs">
                取消
              </Button>
              <Button
                variant="primary"
                disabled={isParsing || !rawText.trim()}
                onClick={handleParse}
                className="text-xs font-medium"
              >
                {isParsing ? (
                  <>
                    <Spinner className="h-3 w-3 inline mr-1.5" />
                    正在智能切题与格式化中…
                  </>
                ) : (
                  "🤖 智能切题识别"
                )}
              </Button>
            </div>
          </>
        ) : (
          <div className="space-y-4 animate-fadeIn">
            {/* 题库名称与概要统计 */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-gray-50 dark:bg-gray-800/60 p-3 rounded-xl border border-gray-200 dark:border-gray-700">
              <div className="flex-1">
                <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                  题库名称
                </label>
                <Input
                  value={bankTitle}
                  onChange={(e) => setBankTitle(e.target.value)}
                  className="mt-1 text-xs"
                  placeholder="给切分好的题库起个名字"
                />
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400 shrink-0 self-end sm:self-center">
                共识别出 <span className="font-bold text-brand-600">{questions.length}</span> 道试题
              </div>
            </div>

            {/* 试题列表卡片 */}
            <div className="space-y-3 max-h-[50vh] overflow-y-auto pr-1">
              {questions.map((q, idx) => (
                <div
                  key={idx}
                  className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/40 p-3 text-xs space-y-2 relative group hover:border-gray-300 dark:hover:border-gray-600 transition"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-gray-500 dark:text-gray-400">
                        #{idx + 1}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-[11px] font-semibold ${
                          q.qtype === "single"
                            ? "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
                            : q.qtype === "multi"
                            ? "bg-purple-50 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300"
                            : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                        }`}
                      >
                        {TYPE_NAME[q.qtype] || q.qtype}
                      </span>
                      <span className="text-gray-400">[{q.difficulty || "普通"}]</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteItem(idx)}
                      className="text-gray-400 hover:text-red-600 text-xs px-1"
                      title="移除此题"
                    >
                      ✕ 移除
                    </button>
                  </div>

                  <p className="font-medium text-gray-800 dark:text-gray-200 leading-relaxed">
                    {q.title}
                  </p>

                  {/* 选项 */}
                  {q.qtype !== "judge" && q.options && q.options.length > 0 && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pl-2">
                      {q.options.map((opt, optIdx) => {
                        const letter = String.fromCharCode(65 + optIdx);
                        const isCorrect = q.answer.split(",").map((s) => s.trim().toUpperCase()).includes(letter);
                        return (
                          <div
                            key={optIdx}
                            className={`rounded px-2 py-1 text-[11px] leading-relaxed flex items-start gap-1.5 ${
                              isCorrect
                                ? "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-800 dark:text-emerald-300 font-medium border border-emerald-200 dark:border-emerald-800"
                                : "text-gray-600 dark:text-gray-400"
                            }`}
                          >
                            <span className="font-bold">{letter}.</span>
                            <span>{opt}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  <div className="flex items-center gap-3 pt-1 border-t border-gray-100 dark:border-gray-800 text-[11px]">
                    <span className="text-emerald-700 dark:text-emerald-300 font-semibold">
                      答案：{q.qtype === "judge" ? (q.answer === "A" ? "正确" : "错误") : q.answer}
                    </span>
                    {q.explanation && (
                      <span className="text-gray-500 dark:text-gray-400 truncate flex-1" title={q.explanation}>
                        💡 解析：{q.explanation}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-gray-100 dark:border-gray-800">
              <Button variant="ghost" onClick={() => setQuestions(null)} className="text-xs">
                ← 重新粘贴
              </Button>
              <div className="flex items-center gap-2">
                <Button variant="secondary" onClick={handleReset} className="text-xs">
                  取消
                </Button>
                <Button
                  variant="primary"
                  disabled={isImporting || questions.length === 0}
                  onClick={handleConfirmImport}
                  className="text-xs font-medium"
                >
                  {isImporting ? (
                    <>
                      <Spinner className="h-3 w-3 inline mr-1.5" />
                      入库创建中…
                    </>
                  ) : (
                    `✅ 确认导入这 ${questions.length} 道题`
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
