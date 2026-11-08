// 导入课程：三种方式——📄 上传 Markdown 原文导入 / 📑 轻量 PDF 导入 / 📸 拍照导入（视觉 AI 转写+解释扩充）
// 共用后续链路：章节切分确认 → 原文/转写稿入库 → 知识点提取（PRD 实现备注 12）
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { ImportAnalysis, ImportChapter } from "../../lib/types";
import { Badge, Button, Input, Spinner, Textarea } from "../../components/ui";

interface EditableChapter extends ImportChapter {
  include: boolean;
}

const MAX_PHOTOS = 8;
const MAX_PHOTO_MB = 10;
const MAX_PDFS = 3;
const MAX_PDF_MB = 5;

export default function ImportPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // ===== 共用：分析/确认状态（文件/拍照/PDF 三条路径汇合到这里） =====
  const [tab, setTab] = useState<"file" | "photo" | "pdf">("file");
  const [files, setFiles] = useState<File[] | null>(null);
  const [analysis, setAnalysis] = useState<ImportAnalysis | null>(null);
  const [title, setTitle] = useState("");
  const [chapters, setChapters] = useState<EditableChapter[]>([]);
  const [analyzeErr, setAnalyzeErr] = useState("");
  // 请求序号：快速换选文件时丢弃过期分析响应，防止 A 文件的行号配上 B 文件内容
  const analyzeReqRef = useRef(0);

  const analyze = useMutation({
    mutationFn: async ({ fs, reqId }: { fs: File[]; reqId: number }) => {
      const res = await api.courses.importAnalyze(fs);
      return { res, reqId };
    },
    onSuccess: ({ res, reqId }) => {
      if (reqId !== analyzeReqRef.current) return; // 已换选其他文件，丢弃过期结果
      setAnalysis(res);
      setTitle(res.title);
      setChapters(res.chapters.map((c) => ({ ...c, include: true })));
    },
    onError: (e, { reqId }) => {
      if (reqId !== analyzeReqRef.current) return; // 旧文件的失败不覆盖新文件状态
      setAnalyzeErr(e.message);
    },
  });

  const confirm = useMutation({
    mutationFn: () => {
      const spec = {
        title: title.trim(),
        chapters: chapters
          .filter((c) => c.include)
          .map(({ file_index, title: t, start_line, end_line }) => ({
            file_index,
            title: t.trim(),
            start_line,
            end_line,
          })),
      };
      return api.courses.importConfirm(files!, spec);
    },
    onSuccess: (course) => {
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      navigate(`/courses/${course.id}`);
    },
  });

  const startAnalyze = (fs: File[]) => {
    const reqId = ++analyzeReqRef.current;
    setFiles(fs);
    setAnalysis(null);
    setChapters([]);
    setAnalyzeErr("");
    analyze.mutate({ fs, reqId });
  };

  const resetAll = () => {
    analyzeReqRef.current++;
    setFiles(null);
    setAnalysis(null);
    setChapters([]);
    setAnalyzeErr("");
    revokeAllPreviews();
    setPhotos([]);
    setPreviews([]);
    setPdfFiles([]);
    setTranscribed("");
    setTranscribeErr("");
    if (fileRef.current) fileRef.current.value = "";
  };

  const updateChapter = (i: number, patch: Partial<EditableChapter>) =>
    setChapters((prev) => prev.map((c, k) => (k === i ? { ...c, ...patch } : c)));

  const included = chapters.filter((c) => c.include).length;

  // ===== 文件导入（原有流程） =====
  const fileRef = useRef<HTMLInputElement>(null);
  const pickFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    const fs = Array.from(list).sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
    if (fileRef.current) fileRef.current.value = "";
    startAnalyze(fs);
  };

  // ===== 拍照导入 =====
  const cameraRef = useRef<HTMLInputElement>(null);
  const albumRef = useRef<HTMLInputElement>(null);
  const [photos, setPhotos] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [hint, setHint] = useState("");
  const [transcribed, setTranscribed] = useState("");
  const [transcribeErr, setTranscribeErr] = useState("");
  // 预览 URL 单一路径管理：每个 File 只 create 一次，revoke 只走 revokeAllPreviews
  const previewsRef = useRef<string[]>([]);

  const revokeAllPreviews = () => {
    previewsRef.current.forEach((u) => URL.revokeObjectURL(u));
    previewsRef.current = [];
  };

  // 组件卸载时释放全部预览 URL（经 ref 取最新值，避免 stale closure 漏 revoke）
  useEffect(() => {
    return () => revokeAllPreviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addPhotos = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    setTranscribeErr("");
    const incoming: File[] = [];
    for (const f of Array.from(list)) {
      if (!f.type.startsWith("image/")) {
        setTranscribeErr(`「${f.name}」不是图片文件`);
        return;
      }
      if (f.size > MAX_PHOTO_MB * 1024 * 1024) {
        setTranscribeErr(`「${f.name}」超过 ${MAX_PHOTO_MB}MB 上限`);
        return;
      }
      incoming.push(f);
    }
    const overflow = photos.length + incoming.length > MAX_PHOTOS;
    const merged = [...photos, ...incoming].slice(0, MAX_PHOTOS);
    // 每个 File 只创建一次预览 URL；被 slice 丢弃的文件也要回收
    const incomingUrls = incoming.map((f) => URL.createObjectURL(f));
    const keptUrls = incomingUrls.slice(0, Math.max(0, merged.length - photos.length));
    incomingUrls.slice(keptUrls.length).forEach((u) => URL.revokeObjectURL(u));
    setPhotos(merged);
    setPreviews([...previews, ...keptUrls]);
    previewsRef.current = [...previewsRef.current, ...keptUrls];
    if (overflow) {
      setTranscribeErr(`最多上传 ${MAX_PHOTOS} 张图片，多余的已忽略`);
    }
  };

  const removePhoto = (i: number) => {
    // 只 revoke 被删项，其余 URL 保持不变（避免重建造成引用丢失）
    URL.revokeObjectURL(previews[i]);
    previewsRef.current = previewsRef.current.filter((_, k) => k !== i);
    setPhotos(photos.filter((_, k) => k !== i));
    setPreviews(previews.filter((_, k) => k !== i));
  };

  const clearPhotos = () => {
    revokeAllPreviews();
    setPhotos([]);
    setPreviews([]);
    setTranscribed("");
  };

  const transcribe = useMutation({
    mutationFn: () => api.courses.photoTranscribe(photos, hint),
    onSuccess: (res) => {
      setTranscribed(res.content);
      setTranscribeErr("");
    },
    onError: (e) => setTranscribeErr((e as Error).message),
  });

  // 把转写稿合成虚拟 Markdown 文件，走与文件导入完全相同的切章/确认/入库链路
  const proceedToChapters = () => {
    const text = transcribed.trim();
    if (!text) return;
    const virtualFile = new File([text], "拍照导入.md", { type: "text/markdown" });
    startAnalyze([virtualFile]);
  };

  const pickPhotoInput = (list: FileList | null) => {
    addPhotos(list);
    if (cameraRef.current) cameraRef.current.value = "";
    if (albumRef.current) albumRef.current.value = "";
  };

  // ===== 轻量 PDF 导入（文本层直取零消耗；扫描版走视觉转写） =====
  const pdfRef = useRef<HTMLInputElement>(null);
  const [pdfFiles, setPdfFiles] = useState<File[]>([]);

  const pickPdfs = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    setTranscribeErr("");
    const incoming: File[] = [];
    for (const f of Array.from(list)) {
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        setTranscribeErr(`「${f.name}」不是 PDF 文件`);
        return;
      }
      if (f.size > MAX_PDF_MB * 1024 * 1024) {
        setTranscribeErr(`「${f.name}」超过 ${MAX_PDF_MB}MB 上限`);
        return;
      }
      incoming.push(f);
    }
    const merged = [...pdfFiles, ...incoming].slice(0, MAX_PDFS);
    setPdfFiles(merged);
    if (pdfFiles.length + incoming.length > MAX_PDFS) {
      setTranscribeErr(`最多导入 ${MAX_PDFS} 个 PDF，多余的已忽略`);
    }
    if (pdfRef.current) pdfRef.current.value = "";
  };

  const pdfTranscribe = useMutation({
    mutationFn: () => api.courses.pdfTranscribe(pdfFiles, hint),
    onSuccess: (res) => {
      setTranscribed(res.content);
      setTranscribeErr("");
    },
    onError: (e) => setTranscribeErr((e as Error).message),
  });

  // 把 PDF 转写稿合成虚拟 Markdown 文件，走与文件导入完全相同的切章/确认/入库链路
  const proceedPdfToChapters = () => {
    const text = transcribed.trim();
    if (!text) return;
    const virtualFile = new File([text], "PDF导入.md", { type: "text/markdown" });
    startAnalyze([virtualFile]);
  };

  return (
    <div className="mx-auto max-w-5xl p-8">
      <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-brand-600">
        ← 返回首页
      </Link>
      <h1 className="mt-4 text-2xl font-bold text-gray-900 dark:text-gray-100">导入课程</h1>

      {/* 方式切换 */}
      {!analysis && (
        <div className="mt-4 flex border-b border-gray-200 dark:border-gray-700">
          <button
            type="button"
            onClick={() => setTab("file")}
            className={`pb-2 px-4 text-sm font-semibold transition border-b-2 -mb-px ${
              tab === "file"
                ? "border-brand-600 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            📄 上传 Markdown
          </button>
          <button
            type="button"
            onClick={() => setTab("pdf")}
            className={`pb-2 px-4 text-sm font-semibold transition border-b-2 -mb-px ${
              tab === "pdf"
                ? "border-brand-600 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            📑 PDF 导入
          </button>
          <button
            type="button"
            onClick={() => setTab("photo")}
            className={`pb-2 px-4 text-sm font-semibold transition border-b-2 -mb-px ${
              tab === "photo"
                ? "border-brand-600 text-brand-600 dark:border-brand-400 dark:text-brand-400"
                : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            📸 拍照导入
          </button>
        </div>
      )}

      {/* ===== 文件导入 ===== */}
      {tab === "file" && !analysis && (
        <>
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
            选择你自己的 .md 文件，系统按标题结构自动识别章节；原文保留、不做改写，并提取知识点。
          </p>
          <div
            className="mt-6 cursor-pointer rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 p-8 text-center transition hover:border-brand-500"
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pickFiles(e.dataTransfer.files);
            }}
          >
            <input
              ref={fileRef}
              type="file"
              multiple
              accept=".md,.markdown,.mdown,.mkd"
              className="hidden"
              onChange={(e) => pickFiles(e.target.files)}
            />
            <div className="text-3xl">📄</div>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              点击选择或拖入 Markdown 文件（可多选，单文件 ≤ 5MB，最多 20 个）
            </p>
            {files && !analysis && (
              <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                已选择 {files.length} 个：{files.map((f) => f.name).join("、")}
              </p>
            )}
          </div>

          {analyze.isPending && (
            <div className="mt-4 flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
              <Spinner /> 正在识别章节结构…
            </div>
          )}
          {analyzeErr && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{analyzeErr}</p>}
        </>
      )}

      {/* ===== 轻量 PDF 导入 ===== */}
      {tab === "pdf" && !analysis && (
        <>
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
            选择 PDF 教材或讲义：有文字层的 PDF 直接抽取全文（不消耗 AI）；扫描版/图片型 PDF 自动逐页视觉转写（≤16 页，需配置多模态模型）。
          </p>
          <div
            className="mt-6 cursor-pointer rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 p-8 text-center transition hover:border-brand-500"
            onClick={() => pdfRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pickPdfs(e.dataTransfer.files);
            }}
          >
            <input
              ref={pdfRef}
              type="file"
              multiple
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={(e) => pickPdfs(e.target.files)}
            />
            <div className="text-3xl">📑</div>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              点击选择或拖入 PDF 文件（可多选，单文件 ≤ 5MB，最多 {MAX_PDFS} 个）
            </p>
            {pdfFiles.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
                {pdfFiles.map((f, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-2.5 py-1 text-xs text-gray-600 dark:text-gray-300"
                  >
                    {f.name}
                    <button
                      type="button"
                      className="text-gray-400 hover:text-red-500"
                      onClick={(e) => {
                        e.stopPropagation();
                        setPdfFiles(pdfFiles.filter((_, k) => k !== i));
                      }}
                    >
                      ✕
                    </button>
                  </span>
                ))}
                <button
                  type="button"
                  className="text-xs text-brand-600 dark:text-brand-400 hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    setPdfFiles([]);
                  }}
                >
                  清空
                </button>
              </div>
            )}
          </div>

          <div className="mt-4">
            <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
              处理方式说明（可选，扫描版转写时使用）
            </label>
            <Input
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              placeholder="如：忠实复刻原文 / 这是高数讲义，重点保留公式与推导"
              className="text-xs"
            />
          </div>

          {transcribeErr && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{transcribeErr}</p>}

          {!transcribed && (
            <Button
              className="mt-4 w-full"
              disabled={pdfFiles.length === 0 || pdfTranscribe.isPending}
              onClick={() => pdfTranscribe.mutate()}
            >
              {pdfTranscribe.isPending ? (
                <>
                  <Spinner className="border-white/40" /> 正在提取/转写 PDF（扫描版约 20~60 秒/文件）…
                </>
              ) : (
                `📑 提取为学习材料${pdfFiles.length ? `（${pdfFiles.length} 个 PDF）` : ""}`
              )}
            </Button>
          )}

          {transcribed && (
            <div className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  ✅ 提取完成（可手动修正后再切章）
                </span>
                <Button
                  variant="ghost"
                  className="text-xs"
                  disabled={pdfTranscribe.isPending || pdfFiles.length === 0}
                  onClick={() => pdfTranscribe.mutate()}
                >
                  ↻ 重新提取
                </Button>
              </div>
              <Textarea
                rows={14}
                value={transcribed}
                onChange={(e) => setTranscribed(e.target.value)}
                className="font-mono text-xs"
              />
              <Button className="mt-3 w-full" disabled={!transcribed.trim()} onClick={proceedPdfToChapters}>
                下一步：切章确认 →
              </Button>
            </div>
          )}
        </>
      )}

      {/* ===== 拍照导入 ===== */}
      {tab === "photo" && !analysis && (
        <div
          className="mt-3"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (e.dataTransfer.files.length > 0) pickPhotoInput(e.dataTransfer.files);
          }}
        >
          <p className="text-sm text-gray-500 dark:text-gray-400">
            拍摄书上的内容或例题（手机点「拍照」直接拉起相机），AI 转写为结构化教材并解释扩充——例题自动补全解题过程，建课后即可针对章节出练习题。
          </p>

          {/* 拍照 / 相册入口：capture 属性在局域网 HTTP 下也能拉起手机相机（getUserMedia 需 HTTPS 不可用） */}
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => cameraRef.current?.click()}
              className="flex flex-col items-center gap-1.5 rounded-xl border-2 border-dashed border-brand-300 dark:border-brand-800 bg-brand-50/50 dark:bg-brand-950/20 py-6 text-brand-700 dark:text-brand-300 hover:border-brand-500 hover:bg-brand-50 dark:hover:bg-brand-900/30 transition"
            >
              <input
                ref={cameraRef}
                type="file"
                accept="image/*"
                capture="environment"
                multiple
                className="hidden"
                onChange={(e) => pickPhotoInput(e.target.files)}
              />
              <span className="text-2xl">📸</span>
              <span className="text-sm font-semibold">拍照</span>
              <span className="text-[11px] text-gray-400">手机直接拉起相机</span>
            </button>
            <button
              type="button"
              onClick={() => albumRef.current?.click()}
              className="flex flex-col items-center gap-1.5 rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 py-6 text-gray-600 dark:text-gray-300 hover:border-brand-500 hover:text-brand-600 dark:hover:text-brand-400 transition"
            >
              <input
                ref={albumRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => pickPhotoInput(e.target.files)}
              />
              <span className="text-2xl">🖼️</span>
              <span className="text-sm font-semibold">从相册选择</span>
              <span className="text-[11px] text-gray-400">或把图片拖到本页任意位置</span>
            </button>
          </div>

          {/* 缩略图预览 */}
          {photos.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                <span>
                  已选 {photos.length}/{MAX_PHOTOS} 张
                </span>
                <button
                  type="button"
                  className="text-brand-600 dark:text-brand-400 hover:underline"
                  onClick={clearPhotos}
                >
                  清空重拍
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {photos.map((p, i) => (
                  <div key={i} className="group relative">
                    <img
                      src={previews[i]}
                      alt={`图片 ${i + 1}`}
                      className="h-24 w-full rounded-lg border border-gray-200 dark:border-gray-700 object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => removePhoto(i)}
                      className="absolute right-1 top-1 rounded-full bg-black/60 px-1.5 text-xs text-white opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
                      title="移除"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 意图提示（可选） */}
          <div className="mt-4">
            <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
              处理方式说明（可选）
            </label>
            <Input
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              placeholder="如：解释扩充概念 / 忠实复刻原文 / 这是高数例题，重点补全解题过程"
              className="text-xs"
            />
          </div>

          {transcribeErr && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{transcribeErr}</p>}

          {/* AI 转写 */}
          {!transcribed && (
            <Button
              className="mt-4 w-full"
              disabled={photos.length === 0 || transcribe.isPending}
              onClick={() => transcribe.mutate()}
            >
              {transcribe.isPending ? (
                <>
                  <Spinner className="border-white/40" /> AI 正在识别与转写（约 20~60 秒，取决于张数）…
                </>
              ) : (
                `🤖 AI 转写${photos.length ? `（${photos.length} 张图片）` : ""}`
              )}
            </Button>
          )}

          {/* 转写结果编辑 */}
          {transcribed && (
            <div className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  ✅ 转写完成（可手动修正识别误差）
                </span>
                <Button
                  variant="ghost"
                  className="text-xs"
                  disabled={transcribe.isPending || photos.length === 0}
                  onClick={() => transcribe.mutate()}
                >
                  ↻ 重新转写
                </Button>
              </div>
              <Textarea
                rows={14}
                value={transcribed}
                onChange={(e) => setTranscribed(e.target.value)}
                className="font-mono text-xs"
              />
              <Button className="mt-3 w-full" disabled={!transcribed.trim()} onClick={proceedToChapters}>
                下一步：切章确认 →
              </Button>
            </div>
          )}
        </div>
      )}

      {/* ===== 共用：章节切分确认（文件与拍照两条路径汇合） ===== */}
      {analysis && (
        <div className="mt-6 space-y-4">
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">课程标题</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            {analysis.title_from_llm && (
              <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">✨ 由 AI 根据章节内容拟定，可修改</p>
            )}
            {!analysis.llm_available && (
              <p className="mt-1 text-amber-600 dark:text-amber-400">
                未配置 LLM：将跳过知识点提取（文档本身正常导入），可稍后在设置页配置后重新导入。
              </p>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                识别到 {chapters.length} 个章节（勾选要导入的部分，标题可改）
              </span>
              <Button variant="ghost" className="text-xs" onClick={resetAll}>
                {tab === "photo" ? "重新拍照/选图" : "重选文件"}
              </Button>            </div>
            <div className="space-y-2">
              {chapters.map((c, i) => (
                <div
                  key={`${c.file_index}-${c.start_line}`}
                  className={`rounded-lg border p-3 ${c.include ? "border-gray-200 dark:border-gray-700" : "border-gray-100 dark:border-gray-800 opacity-50"}`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={c.include}
                      onChange={(e) => updateChapter(i, { include: e.target.checked })}
                    />
                    <Input
                      value={c.title}
                      onChange={(e) => updateChapter(i, { title: e.target.value })}
                    />
                  </div>
                  <div className="mt-1 flex items-center gap-2 pl-6 text-xs text-gray-400 dark:text-gray-500">
                    <Badge>{analysis.files[c.file_index]?.name}</Badge>
                    {c.points.length > 0 && <span>小节：{c.points.join(" / ")}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <Button
            className="w-full"
            disabled={included === 0 || !title.trim() || confirm.isPending}
            onClick={() => confirm.mutate()}
          >
            {confirm.isPending ? (
              <>
                <Spinner className="border-white/40" /> 导入中（含知识点提取，请稍候）…
              </>
            ) : (
              `导入 ${included} 个章节`
            )}
          </Button>
          {confirm.isError && <p className="text-center text-sm text-red-600 dark:text-red-400">{confirm.error.message}</p>}
        </div>
      )}
    </div>
  );
}
