import { useRef, useState } from "react";
import { Modal, Button, Textarea, Input, Select, Spinner, ErrorText, Badge } from "../../components/ui";
import { api } from "../../lib/api";
import type { BankAnalysis, ParsedTextQuestionItem } from "../../lib/types";

interface Props {
  open: boolean;
  bankId: string;
  bankName: string;
  onClose: () => void;
  onSuccess: (addedCount: number) => void;
}

const SAMPLE_TEXT = `1. 下列关于 HTTP 状态码的描述中，表示请求被服务器拒绝的是（ ）
A. 200 OK
B. 302 Found
C. 403 Forbidden
D. 500 Internal Server Error
答案：C
解析：403 状态码表示服务器理解请求客户端的请求，但是拒绝执行此请求。

2. 下列哪些属于 TCP 协议的特性？（ ）
A. 面向连接
B. 提供可靠交付
C. 支持无连接广播
D. 面向字节流
答案：A,B,D
解析：TCP 是面向连接、可靠交付、面向字节流的传输层协议；UDP 才支持无连接广播。

3. 在对称加密算法中，加密密钥与解密密钥是相同的或容易相互推导。（ ）
答案：正确
解析：对称加密的核心特征就是加解密双方使用同一把密钥。`;

const TYPE_NAME: Record<string, string> = {
  single: "单选题",
  multi: "多选题",
  judge: "判断题",
};

export default function AddQuestionModal({ open, bankId, bankName, onClose, onSuccess }: Props) {
  const [tab, setTab] = useState<"excel" | "manual" | "paste">("excel");

  // 表格导入状态
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<BankAnalysis | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // 手动录入表单状态
  const [qtype, setQtype] = useState<"single" | "multi" | "judge">("single");
  const [title, setTitle] = useState("");
  const [options, setOptions] = useState<string[]>(["", "", "", ""]);
  const [answer, setAnswer] = useState<string>("A"); // single: "A", multi: "A,B", judge: "A"
  const [explanation, setExplanation] = useState("");
  const [difficulty, setDifficulty] = useState("普通");

  // 粘贴切题状态
  const [rawText, setRawText] = useState("");
  const [isParsing, setIsParsing] = useState(false);
  const [parsedQuestions, setParsedQuestions] = useState<ParsedTextQuestionItem[] | null>(null);

  // 提交状态
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const handleReset = () => {
    setFile(null);
    setAnalysis(null);
    setIsAnalyzing(false);
    setTitle("");
    setOptions(["", "", "", ""]);
    setAnswer("A");
    setExplanation("");
    setDifficulty("普通");
    setRawText("");
    setParsedQuestions(null);
    setErrorMsg("");
    onClose();
  };

  // --- 表格导入逻辑 ---
  const handleFileSelect = async (selectedFile?: File) => {
    if (!selectedFile) return;
    setFile(selectedFile);
    setAnalysis(null);
    setErrorMsg("");
    setIsAnalyzing(true);
    try {
      const a = await api.banks.analyze(selectedFile);
      setAnalysis(a);
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleExcelSubmit = async () => {
    if (!file) {
      setErrorMsg("请先选择 .xls 或 .xlsx 表格文件");
      return;
    }
    setErrorMsg("");
    setIsSubmitting(true);
    try {
      const res = await api.banks.importFileToBank(bankId, file);
      onSuccess(res.added);
      handleReset();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- 手动录入逻辑 ---
  const handleTypeChange = (newType: "single" | "multi" | "judge") => {
    setQtype(newType);
    setErrorMsg("");
    if (newType === "judge") {
      setAnswer("A");
    } else if (newType === "single") {
      const firstAns = answer.split(",")[0] || "A";
      setAnswer(firstAns);
    } else {
      if (!answer) setAnswer("A");
    }
  };

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
    const removedLetter = String.fromCharCode(65 + idx);
    setOptions((prev) => prev.filter((_, i) => i !== idx));
    const ansList = answer.split(",").filter((a) => a !== removedLetter);
    setAnswer(ansList.length > 0 ? ansList.join(",") : "A");
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

  const handleManualSubmit = async () => {
    setErrorMsg("");
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      setErrorMsg("请填写题目题干内容");
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
        setErrorMsg("至少需要填写 2 个有效选项");
        return;
      }
      if (cleanOpts.some((o) => !o)) {
        setErrorMsg("所有选项内容均不能为空，如有多余选项请点击右侧删除");
        return;
      }
      if (!answer) {
        setErrorMsg("请至少选择一个正确答案");
        return;
      }
      finalOptions = cleanOpts;
    }

    const item: ParsedTextQuestionItem = {
      qtype,
      title: cleanTitle,
      options: finalOptions,
      answer,
      difficulty,
      explanation: explanation.trim(),
    };

    setIsSubmitting(true);
    try {
      await api.banks.addQuestions(bankId, [item]);
      onSuccess(1);
      handleReset();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- 粘贴切题逻辑 ---
  const handleParse = async () => {
    if (!rawText.trim()) {
      setErrorMsg("请先粘贴试题文本内容");
      return;
    }
    setErrorMsg("");
    setIsParsing(true);
    try {
      const res = await api.banks.pasteParse(rawText.trim());
      if (!res.questions || res.questions.length === 0) {
        setErrorMsg("未能从文本中识别出有效试题，请检查文本格式");
      } else {
        setParsedQuestions(res.questions);
      }
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsParsing(false);
    }
  };

  const handleConfirmBatch = async () => {
    if (!parsedQuestions || parsedQuestions.length === 0) {
      setErrorMsg("没有可添加的试题");
      return;
    }
    setErrorMsg("");
    setIsSubmitting(true);
    try {
      const res = await api.banks.addQuestions(bankId, parsedQuestions);
      onSuccess(res.added || parsedQuestions.length);
      handleReset();
    } catch (e) {
      setErrorMsg((e as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteParsedItem = (idx: number) => {
    if (!parsedQuestions) return;
    setParsedQuestions(parsedQuestions.filter((_, i) => i !== idx));
  };

  return (
    <Modal open={open} onClose={handleReset} title={`➕ 向「${bankName}」增加题目`} width="max-w-2xl">
      <div className="space-y-4">
        {/* 顶部 Tab 模式切换 */}
        <div className="flex border-b border-gray-200 dark:border-gray-700">
          <button
            type="button"
            className={`pb-2 px-3 text-xs font-semibold transition border-b-2 -mb-px ${
              tab === "excel"
                ? "border-brand-600 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
            onClick={() => {
              setTab("excel");
              setErrorMsg("");
            }}
          >
            📥 上传表格导入
          </button>
          <button
            type="button"
            className={`pb-2 px-3 text-xs font-semibold transition border-b-2 -mb-px ${
              tab === "manual"
                ? "border-brand-600 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
            onClick={() => {
              setTab("manual");
              setErrorMsg("");
            }}
          >
            ✍️ 手动添加单题
          </button>
          <button
            type="button"
            className={`pb-2 px-3 text-xs font-semibold transition border-b-2 -mb-px ${
              tab === "paste"
                ? "border-brand-600 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
            onClick={() => {
              setTab("paste");
              setErrorMsg("");
            }}
          >
            📋 文本智能切题
          </button>
        </div>

        {/* Tab 1: 表格导入 */}
        {tab === "excel" && (
          <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
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

            {!file ? (
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 py-12 text-gray-500 dark:text-gray-400 hover:border-brand-400 hover:text-brand-600 dark:hover:text-brand-400 transition bg-gray-50/40 dark:bg-gray-800/20"
              >
                <span className="text-3xl">📄</span>
                <span className="text-sm font-medium">点击选择 .xls / .xlsx 题库文件追加到当前题库</span>
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  标准列布局：题型 / 题干 / 选项A-H / 正确答案 / … / 解析 / 难度
                </span>
              </button>
            ) : isAnalyzing ? (
              <div className="flex flex-col items-center justify-center gap-2 py-12 text-sm text-gray-500 dark:text-gray-400">
                <Spinner className="h-6 w-6" />
                <span>正在解析表格文件，请稍候…</span>
              </div>
            ) : analysis ? (
              <div className="space-y-3.5">
                <div className="flex items-center justify-between rounded-xl bg-gray-50 dark:bg-gray-800/60 p-3 border border-gray-200 dark:border-gray-700">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-gray-900 dark:text-gray-100">
                      📎 文件：{analysis.source_file}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-gray-600 dark:text-gray-300">
                      <span>可解析试题：<strong className="text-brand-600 font-bold">{analysis.question_count}</strong> 题</span>
                      {analysis.by_type.single !== undefined && <span>单选 {analysis.by_type.single}</span>}
                      {analysis.by_type.multi !== undefined && <span>多选 {analysis.by_type.multi}</span>}
                      {analysis.by_type.judge !== undefined && <span>判断 {analysis.by_type.judge}</span>}
                      {analysis.skipped_total > 0 && (
                        <span className="text-amber-600 dark:text-amber-400">跳过空行/表头 {analysis.skipped_total} 行</span>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    className="shrink-0 text-xs ml-2"
                    onClick={() => {
                      setFile(null);
                      setAnalysis(null);
                    }}
                  >
                    重新选文件
                  </Button>
                </div>

                {/* 样题预览 */}
                {analysis.samples && analysis.samples.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                      前 {analysis.samples.length} 道题目抽样预览：
                    </div>
                    <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                      {analysis.samples.map((q, idx) => (
                        <div
                          key={idx}
                          className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/40 p-2 text-xs space-y-1"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-gray-400">#{q.seq}</span>
                            <Badge color={q.qtype === "single" ? "blue" : q.qtype === "multi" ? "purple" : "green"}>
                              {TYPE_NAME[q.qtype] || q.qtype}
                            </Badge>
                            <span className="truncate font-medium text-gray-800 dark:text-gray-200">
                              {q.title}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
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
                onClick={handleExcelSubmit}
                className="text-xs font-medium"
              >
                {isSubmitting ? (
                  <>
                    <Spinner className="h-3 w-3 inline mr-1.5" />
                    正在导入追加中…
                  </>
                ) : (
                  `确认导入追加${analysis ? ` (${analysis.question_count} 题)` : ""}`
                )}
              </Button>
            </div>
          </div>
        )}

        {/* Tab 2: 手动录入 */}
        {tab === "manual" && (
          <div className="space-y-3.5 max-h-[68vh] overflow-y-auto pr-1">
            <div className="flex flex-wrap items-center justify-between gap-3 bg-gray-50 dark:bg-gray-800/40 p-2.5 rounded-lg border border-gray-200 dark:border-gray-700">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-300">题型：</span>
                {(["single", "multi", "judge"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => handleTypeChange(t)}
                    className={`px-2.5 py-1 rounded text-xs font-medium transition ${
                      qtype === t
                        ? "bg-brand-600 text-white shadow-sm"
                        : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-700 hover:border-brand-500"
                    }`}
                  >
                    {TYPE_NAME[t]}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-300">难度：</span>
                <Select
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                  className="!py-0.5 !text-xs !w-24"
                >
                  <option value="简单">简单</option>
                  <option value="普通">普通</option>
                  <option value="困难">困难</option>
                </Select>
              </div>
            </div>

            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
                  题干内容 <span className="text-red-500">*</span>
                </label>
                <span className="text-[11px] text-gray-400">支持直接输入纯文本或 Markdown/LaTeX 公式</span>
              </div>
              <Textarea
                rows={3}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="请输入题目描述与题干…"
                className="text-xs"
              />
            </div>

            {qtype === "judge" ? (
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  正确答案 <span className="text-red-500">*</span>（点击选择）
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
                  <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
                    选项设置 <span className="text-red-500">*</span>
                    <span className="text-[11px] font-normal text-gray-400 ml-1.5">
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

            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                答案解析 <span className="text-[11px] font-normal text-gray-400">（选填）</span>
              </label>
              <Textarea
                rows={2}
                value={explanation}
                onChange={(e) => setExplanation(e.target.value)}
                placeholder="填写答案剖析或考点说明，答错或复盘时可见…"
                className="text-xs"
              />
            </div>

            {errorMsg && <ErrorText>{errorMsg}</ErrorText>}

            <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
              <Button variant="ghost" onClick={handleReset} className="text-xs">
                取消
              </Button>
              <Button
                variant="primary"
                disabled={isSubmitting}
                onClick={handleManualSubmit}
                className="text-xs font-medium"
              >
                {isSubmitting ? (
                  <>
                    <Spinner className="h-3 w-3 inline mr-1.5" />
                    保存中…
                  </>
                ) : (
                  "保存并添加到题库"
                )}
              </Button>
            </div>
          </div>
        )}

        {/* Tab 3: 文本智能切题 */}
        {tab === "paste" && (
          <div className="space-y-4 max-h-[68vh] overflow-y-auto pr-1">
            {!parsedQuestions ? (
              <>
                <div className="flex items-center justify-between">
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    直接粘贴包含单选、多选或判断的题目文本，AI 自动切分题干、选项与答案追加进当前题库。
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
                  rows={10}
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  placeholder="在此粘贴任意纯文本试题，如：
1. 试题题干...
A. 选项1
B. 选项2
答案：A
解析：..."
                  className="text-xs font-mono"
                />

                {errorMsg && <ErrorText>{errorMsg}</ErrorText>}

                <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
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
                        智能切题解析中…
                      </>
                    ) : (
                      "🤖 智能切题识别"
                    )}
                  </Button>
                </div>
              </>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between bg-brand-50/50 dark:bg-brand-950/20 p-2.5 rounded-lg border border-brand-200 dark:border-brand-800">
                  <span className="text-xs text-gray-700 dark:text-gray-300">
                    已切分识别出 <strong className="text-brand-600 dark:text-brand-400">{parsedQuestions.length}</strong> 道试题
                  </span>
                  <button
                    type="button"
                    onClick={() => setParsedQuestions(null)}
                    className="text-xs text-brand-600 dark:text-brand-400 hover:underline"
                  >
                    重新粘贴
                  </button>
                </div>

                <div className="space-y-2.5 max-h-[48vh] overflow-y-auto pr-1">
                  {parsedQuestions.map((q, idx) => (
                    <div
                      key={idx}
                      className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/40 p-2.5 text-xs space-y-1.5 relative group"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-gray-500">#{idx + 1}</span>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
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
                          onClick={() => handleDeleteParsedItem(idx)}
                          className="text-gray-400 hover:text-red-600 text-xs px-1"
                          title="排除此题"
                        >
                          ✕ 排除
                        </button>
                      </div>

                      <p className="font-medium text-gray-800 dark:text-gray-200">{q.title}</p>

                      {q.qtype !== "judge" && q.options && q.options.length > 0 && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 pl-2">
                          {q.options.map((opt, optIdx) => {
                            const letter = String.fromCharCode(65 + optIdx);
                            const isCorrect = q.answer
                              .split(",")
                              .map((s) => s.trim().toUpperCase())
                              .includes(letter);
                            return (
                              <div
                                key={optIdx}
                                className={`rounded px-1.5 py-0.5 text-[11px] flex items-start gap-1 ${
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

                      <div className="text-[11px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/80 p-1.5 rounded flex items-center gap-2">
                        <span>
                          <strong>答案：</strong>
                          <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                            {q.qtype === "judge" ? (q.answer === "A" ? "正确" : "错误") : q.answer}
                          </span>
                        </span>
                        {q.explanation && (
                          <span className="truncate">
                            <strong>解析：</strong>
                            {q.explanation}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {errorMsg && <ErrorText>{errorMsg}</ErrorText>}

                <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
                  <Button variant="ghost" onClick={handleReset} className="text-xs">
                    取消
                  </Button>
                  <Button
                    variant="primary"
                    disabled={isSubmitting || parsedQuestions.length === 0}
                    onClick={handleConfirmBatch}
                    className="text-xs font-medium"
                  >
                    {isSubmitting ? (
                      <>
                        <Spinner className="h-3 w-3 inline mr-1.5" />
                        添加中…
                      </>
                    ) : (
                      `确认追加 ${parsedQuestions.length} 道题目`
                    )}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
