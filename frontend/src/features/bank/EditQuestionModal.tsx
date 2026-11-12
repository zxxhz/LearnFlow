import { useEffect, useState } from "react";
import { Modal, Button, Textarea, Input, Select, Spinner, ErrorText, Badge } from "../../components/ui";
import { api } from "../../lib/api";
import type { BankQuestion, BankQuestionUpdateIn, BankQuestionUpdateOut, BankWrongQuestion } from "../../lib/types";

interface Props {
  open: boolean;
  question: BankQuestion | (BankWrongQuestion & { user_answer?: string });
  initialCorrectAnswer?: string; // 当前卡片上展示的标准答案（如 "A" / "A,C" / "B"）
  initialExplanation?: string;
  suggestedAnswer?: string; // AI 检测出的建议修正答案
  onClose: () => void;
  onSuccess: (res: BankQuestionUpdateOut) => void;
}

const TYPE_NAME: Record<string, string> = {
  single: "单选题",
  multi: "多选题",
  judge: "判断题",
};

export default function EditQuestionModal({
  open,
  question,
  initialCorrectAnswer,
  initialExplanation,
  suggestedAnswer,
  onClose,
  onSuccess,
}: Props) {
  const [title, setTitle] = useState(question.title);
  const [qtype] = useState(question.qtype); // 保持原题型
  const [options, setOptions] = useState<string[]>([]);
  const [answer, setAnswer] = useState<string>("A");
  const [explanation, setExplanation] = useState("");
  const [difficulty, setDifficulty] = useState(question.difficulty || "普通");
  const [recalibrate, setRecalibrate] = useState(true);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  // 弹窗打开时回填当前题目的状态
  useEffect(() => {
    if (!open) return;
    setTitle(question.title);
    setDifficulty(question.difficulty || "普通");

    // 解析当前选项：选择题直接用原始 8 槽位数组并裁掉尾部空槽——
    // 保留内部空槽的占位，保证字母位置与原题一致（用 visibleOptions 压缩回填会使含空槽题错位）
    if (question.qtype === "judge") {
      setOptions([]);
    } else {
      const raw = (question as BankWrongQuestion).options || question.options || [];
      const arr = [...raw];
      while (arr.length > 2 && !String(arr[arr.length - 1] ?? "").trim()) arr.pop();
      setOptions(arr.length > 0 ? arr.map((v) => String(v ?? "")) : ["", "", "", ""]);
    }

    // 正确答案：优先使用传入的标准答案或题目对象自身的答案
    const curAns = (initialCorrectAnswer || (question as BankWrongQuestion).answer || "A").trim().toUpperCase();
    setAnswer(curAns);

    // 解析回填
    const curExp = initialExplanation !== undefined ? initialExplanation : (question as BankWrongQuestion).explanation || "";
    setExplanation(curExp);

    setErrorMsg("");
  }, [open, question, initialCorrectAnswer, initialExplanation]);

  const handleOptionChange = (idx: number, val: string) => {
    setOptions((prev) => {
      const next = [...prev];
      next[idx] = val;
      return next;
    });
  };

  const handleAddOption = () => {
    if (options.length >= 8) return;
    setOptions((prev) => [...prev, ""]);
  };

  const handleRemoveOption = (idx: number) => {
    if (options.length <= 2) return;
    // 删除选项后，其后所有选项字母前移一位，答案字母同步重映射（否则答案指向错位内容）
    setOptions((prev) => prev.filter((_, i) => i !== idx));
    const remap = (letterIdx: number) => (letterIdx > idx ? letterIdx - 1 : letterIdx);
    const kept = answer
      .split(",")
      .map((a) => a.charCodeAt(0) - 65)
      .filter((i) => i !== idx)
      .map(remap)
      .filter((i) => i >= 0)
      .sort((a, b) => a - b)
      .map((i) => String.fromCharCode(65 + i));
    setAnswer(kept.length > 0 ? kept.join(",") : "A");
  };

  const handleToggleAnswer = (letter: string) => {
    if (qtype === "single" || qtype === "judge") {
      setAnswer(letter);
    } else {
      const current = answer ? answer.split(",") : [];
      let updated: string[];
      if (current.includes(letter)) {
        updated = current.filter((a) => a !== letter);
      } else {
        updated = [...current, letter].sort();
      }
      setAnswer(updated.join(","));
    }
  };

  // 一键采纳 AI 建议的答案
  const handleAdoptSuggestion = () => {
    if (!suggestedAnswer) return;
    const clean = suggestedAnswer.trim().toUpperCase();
    if (qtype === "judge") {
      setAnswer(clean === "B" || clean === "错误" || clean === "FALSE" ? "B" : "A");
    } else {
      setAnswer(clean);
    }
  };

  const handleSubmit = async () => {
    setErrorMsg("");
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      setErrorMsg("题干内容不能为空");
      return;
    }

    let finalOptions: string[] = [];
    if (qtype === "judge") {
      finalOptions = [];
      if (answer !== "A" && answer !== "B") {
        setErrorMsg("请选择判断题正确答案（正确或错误）");
        return;
      }
    } else {
      const cleanOpts = options.map((o) => o.trim());
      if (cleanOpts.filter((o) => o).length < 2) {
        setErrorMsg("选择题至少需要保留 2 个有效选项");
        return;
      }
      if (cleanOpts.some((o) => !o)) {
        setErrorMsg("选项内容不能为空，如有多余选项请删除");
        return;
      }
      if (!answer) {
        setErrorMsg("请至少选择一个正确答案");
        return;
      }
      finalOptions = cleanOpts;
    }

    const body: BankQuestionUpdateIn = {
      title: cleanTitle,
      options: finalOptions,
      answer,
      explanation: explanation.trim(),
      difficulty,
      recalibrate_attempts: recalibrate,
    };

    setIsSubmitting(true);
    try {
      const res = await api.banks.updateQuestion(question.id, body);
      onSuccess(res);
      onClose();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="✏️ 题目纠错与修改答案 / 选项"
      width="max-w-xl"
      confirmCloseIf={() =>
        title !== question.title ||
        difficulty !== (question.difficulty || "普通") ||
        explanation.trim() !== (initialExplanation || "").trim() ||
        answer.trim().toUpperCase() !== (initialCorrectAnswer || (question as BankWrongQuestion).answer || "A").trim().toUpperCase()
      }
      confirmCloseMessage="纠错修改尚未保存，确定丢弃并关闭？"
    >
      <div className="space-y-4 max-h-[72vh] overflow-y-auto pr-1 text-xs">
        {/* 顶部题目元信息与 AI 纠错建议条 */}
        <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-800/60 p-2.5 rounded-lg border border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <span className="font-bold text-gray-500">#{question.seq}</span>
            <Badge color={qtype === "single" ? "blue" : qtype === "multi" ? "purple" : "green"}>
              {TYPE_NAME[qtype] || qtype}
            </Badge>
            <span className="text-gray-400">难度：{difficulty}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-gray-500 dark:text-gray-400">调整难度：</span>
            <Select
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
              className="!py-0.5 !text-xs !w-20"
            >
              <option value="简单">简单</option>
              <option value="普通">普通</option>
              <option value="困难">困难</option>
            </Select>
          </div>
        </div>

        {/* AI 纠错建议采纳提示 */}
        {suggestedAnswer && (
          <div className="flex items-center justify-between gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300">
            <div className="flex items-center gap-1.5 truncate">
              <span>💡</span>
              <span>AI 助教建议正确答案为：</span>
              <strong className="font-bold underline text-brand-600 dark:text-brand-400">
                {suggestedAnswer}
              </strong>
            </div>
            <button
              type="button"
              onClick={handleAdoptSuggestion}
              className="px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-700 text-white font-medium text-[11px] shrink-0 transition shadow-xs"
            >
              一键采纳该答案
            </button>
          </div>
        )}

        {/* 题干内容 */}
        <div>
          <label className="block font-medium text-gray-700 dark:text-gray-300 mb-1">
            题干内容 <span className="text-red-500">*</span>
          </label>
          <Textarea
            rows={3}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="text-xs"
            placeholder="题目题干文本…"
          />
        </div>

        {/* 选项与正确答案设定 */}
        {qtype === "judge" ? (
          <div>
            <label className="block font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              正确答案设定 <span className="text-red-500">*</span>（点击选择）
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setAnswer("A")}
                className={`p-3 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition ${
                  answer === "A"
                    ? "border-emerald-500 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300 ring-1 ring-emerald-500"
                    : "border-gray-200 dark:border-gray-700 hover:border-gray-300 text-gray-700 dark:text-gray-300"
                }`}
              >
                <span>✓</span>
                <span>正确（A）</span>
              </button>
              <button
                type="button"
                onClick={() => setAnswer("B")}
                className={`p-3 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition ${
                  answer === "B"
                    ? "border-red-500 bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-300 ring-1 ring-red-500"
                    : "border-gray-200 dark:border-gray-700 hover:border-gray-300 text-gray-700 dark:text-gray-300"
                }`}
              >
                <span>✕</span>
                <span>错误（B）</span>
              </button>
            </div>
          </div>
        ) : (
          <div>
            <div className="flex justify-between items-center mb-1.5">
              <label className="font-medium text-gray-700 dark:text-gray-300">
                选项设置与正确答案 <span className="text-red-500">*</span>
                <span className="font-normal text-gray-400 ml-1.5 text-[11px]">
                  （点击字母徽标标记正确答案{qtype === "multi" ? "，支持多选" : ""}）
                </span>
              </label>
              {options.length < 8 && (
                <button
                  type="button"
                  onClick={handleAddOption}
                  className="text-xs text-brand-600 dark:text-brand-400 hover:underline font-medium"
                >
                  ➕ 添加选项
                </button>
              )}
            </div>

            <div className="space-y-2">
              {options.map((opt, idx) => {
                const letter = String.fromCharCode(65 + idx);
                const isSelected = answer.split(",").includes(letter);
                return (
                  <div key={idx} className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleToggleAnswer(letter)}
                      className={`w-7 h-7 rounded-lg text-xs font-bold shrink-0 transition flex items-center justify-center ${
                        isSelected
                          ? "bg-emerald-600 text-white shadow-sm ring-2 ring-emerald-400"
                          : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
                      }`}
                      title={isSelected ? "当前为正确答案（点击取消）" : "点击设为正确答案"}
                    >
                      {letter}
                    </button>
                    <Input
                      value={opt}
                      onChange={(e) => handleOptionChange(idx, e.target.value)}
                      placeholder={`选项 ${letter} 内容…`}
                      className="flex-1 !py-1 text-xs"
                    />
                    {options.length > 2 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveOption(idx)}
                        className="p-1 text-gray-400 hover:text-red-500 text-xs shrink-0"
                        title="删除此选项"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 答案解析 */}
        <div>
          <label className="block font-medium text-gray-700 dark:text-gray-300 mb-1">
            答案解析 <span className="font-normal text-gray-400">（选填）</span>
          </label>
          <Textarea
            rows={2}
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
            placeholder="修改或补充此题的解析说明…"
            className="text-xs"
          />
        </div>

        {/* 自动重判勾选框 */}
        <div className="rounded-lg bg-brand-50/50 dark:bg-brand-950/20 p-2.5 border border-brand-200/80 dark:border-brand-900/60 flex items-start gap-2">
          <input
            type="checkbox"
            id="recalibrate-checkbox"
            checked={recalibrate}
            onChange={(e) => setRecalibrate(e.target.checked)}
            className="mt-0.5 rounded text-brand-600 focus:ring-brand-500"
          />
          <label htmlFor="recalibrate-checkbox" className="text-[11px] text-gray-600 dark:text-gray-300 cursor-pointer">
            <strong className="font-semibold text-gray-800 dark:text-gray-200">自动根据新答案重新判定作答</strong>
            <p className="mt-0.5 text-gray-500 dark:text-gray-400">
              勾选后，若您此前的作答符合修正后的新答案，系统将即时纠偏为「回答正确」并移出错题池（存疑作答仍保留待重答）。
            </p>
          </label>
        </div>

        {errorMsg && <ErrorText>{errorMsg}</ErrorText>}

        <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <Button variant="ghost" onClick={onClose} className="text-xs">
            取消
          </Button>
          <Button
            variant="primary"
            disabled={isSubmitting}
            onClick={handleSubmit}
            className="text-xs font-medium"
          >
            {isSubmitting ? (
              <>
                <Spinner className="h-3 w-3 inline mr-1.5" />
                正在保存并校准…
              </>
            ) : (
              "保存修改"
            )}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
