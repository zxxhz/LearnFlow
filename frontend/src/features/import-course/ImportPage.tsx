// 导入自有 Markdown：上传 → 智能识别章节结构 → 预览确认 → 原文入库（PRD 实现备注 12）
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { ImportAnalysis, ImportChapter } from "../../lib/types";
import { Badge, Button, Input, Spinner } from "../../components/ui";

interface EditableChapter extends ImportChapter {
  include: boolean;
}

export default function ImportPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[] | null>(null);
  const [analysis, setAnalysis] = useState<ImportAnalysis | null>(null);
  const [title, setTitle] = useState("");
  const [chapters, setChapters] = useState<EditableChapter[]>([]);
  const [analyzeErr, setAnalyzeErr] = useState("");

  const analyze = useMutation({
    mutationFn: (fs: File[]) => api.courses.importAnalyze(fs),
    onSuccess: (res) => {
      setAnalysis(res);
      setTitle(res.title);
      setChapters(res.chapters.map((c) => ({ ...c, include: true })));
    },
    onError: (e) => setAnalyzeErr(e.message),
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

  const pick = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    const fs = Array.from(list).sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
    setFiles(fs);
    setAnalysis(null);
    setChapters([]);
    setAnalyzeErr("");
    analyze.mutate(fs);
  };

  const updateChapter = (i: number, patch: Partial<EditableChapter>) =>
    setChapters((prev) => prev.map((c, k) => (k === i ? { ...c, ...patch } : c)));

  const included = chapters.filter((c) => c.include).length;

  return (
    <div className="mx-auto max-w-3xl p-8">
      <Link to="/" className="text-sm text-gray-500 hover:text-brand-600">
        ← 返回首页
      </Link>
      <h1 className="mt-4 text-2xl font-bold text-gray-900">导入 Markdown 课程</h1>
      <p className="mt-1 text-sm text-gray-500">
        选择你自己的 .md 文件，系统按标题结构自动识别章节；原文保留、不做改写，并提取知识点进入复习循环。
      </p>

      {/* 文件选择 */}
      <div
        className="mt-6 cursor-pointer rounded-xl border-2 border-dashed border-gray-300 bg-white p-8 text-center transition hover:border-brand-500"
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pick(e.dataTransfer.files);
        }}
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".md,.markdown,.mdown,.mkd"
          className="hidden"
          onChange={(e) => pick(e.target.files)}
        />
        <div className="text-3xl">📄</div>
        <p className="mt-2 text-sm text-gray-600">
          点击选择或拖入 Markdown 文件（可多选，单文件 ≤ 5MB，最多 20 个）
        </p>
        {files && (
          <p className="mt-1 text-xs text-gray-400">
            已选择 {files.length} 个：{files.map((f) => f.name).join("、")}
          </p>
        )}
      </div>

      {analyze.isPending && (
        <div className="mt-4 flex items-center gap-2 text-sm text-gray-600">
          <Spinner /> 正在识别章节结构…
        </div>
      )}
      {analyzeErr && <p className="mt-3 text-sm text-red-600">{analyzeErr}</p>}

      {/* 识别结果预览 */}
      {analysis && (
        <div className="mt-6 space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <label className="mb-1 block text-sm font-medium text-gray-700">课程标题</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            {analysis.title_from_llm && (
              <p className="mt-1 text-xs text-gray-400">✨ 由 AI 根据章节内容拟定，可修改</p>
            )}
            {!analysis.llm_available && (
              <p className="mt-1 text-amber-600">
                未配置 LLM：将跳过知识点提取（文档本身正常导入），可稍后在设置页配置后重新导入。
              </p>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-gray-900">
                识别到 {chapters.length} 个章节（勾选要导入的部分，标题可改）
              </span>
              <Button variant="ghost" className="text-xs" onClick={() => fileRef.current?.click()}>
                重选文件
              </Button>
            </div>
            <div className="space-y-2">
              {chapters.map((c, i) => (
                <div
                  key={`${c.file_index}-${c.start_line}`}
                  className={`rounded-lg border p-3 ${c.include ? "border-gray-200" : "border-gray-100 opacity-50"}`}
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
                  <div className="mt-1 flex items-center gap-2 pl-6 text-xs text-gray-400">
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
          {confirm.isError && <p className="text-center text-sm text-red-600">{confirm.error.message}</p>}
        </div>
      )}
    </div>
  );
}
