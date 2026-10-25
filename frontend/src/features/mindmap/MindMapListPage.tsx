// 思维导图列表管理页面：新建、导入、AI 生成及导图管理
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { MindMapSummary } from "../../lib/types";
import { Button, EmptyState, Modal, Spinner, Textarea } from "../../components/ui";

export default function MindMapListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [genOpen, setGenOpen] = useState(false);
  const [genPrompt, setGenPrompt] = useState("");
  const [genDepth, setGenDepth] = useState(3);
  const [genImportText, setGenImportText] = useState("");

  const [importOpen, setImportOpen] = useState(false);
  const [importTitle, setImportTitle] = useState("");
  const [importContent, setImportContent] = useState("");

  const [renamingMap, setRenamingMap] = useState<MindMapSummary | null>(null);
  const [renameTitle, setRenameTitle] = useState("");

  const { data: mindmaps, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["mindmaps"],
    queryFn: api.mindmaps.list,
  });

  const createBlank = useMutation({
    mutationFn: () => api.mindmaps.create({ title: "新建思维导图", topic: "通用概念" }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
      navigate(`/mindmap/${res.id}`);
    },
    onError: (e) => alert((e as Error).message),
  });

  const generateMap = useMutation({
    mutationFn: () =>
      api.mindmaps.generate({
        prompt: genPrompt.trim(),
        depth: genDepth,
        import_content: genImportText.trim(),
      }),
    onSuccess: (res) => {
      setGenOpen(false);
      setGenPrompt("");
      setGenImportText("");
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
      navigate(`/mindmap/${res.id}`);
    },
    onError: (e) => alert((e as Error).message),
  });

  const importMap = useMutation({
    mutationFn: () =>
      api.mindmaps.import({
        title: importTitle.trim(),
        content: importContent.trim(),
      }),
    onSuccess: (res) => {
      setImportOpen(false);
      setImportTitle("");
      setImportContent("");
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
      navigate(`/mindmap/${res.id}`);
    },
    onError: (e) => alert((e as Error).message),
  });

  const renameMutation = useMutation({
    mutationFn: () => {
      if (!renamingMap) throw new Error("未选中导图");
      return api.mindmaps.update(renamingMap.id, { title: renameTitle.trim() });
    },
    onSuccess: () => {
      setRenamingMap(null);
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.mindmaps.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
    },
    onError: (e) => alert((e as Error).message),
  });

  const handleExport = async (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation();
    try {
      const res = await api.mindmaps.exportMarkdown(id);
      const blob = new Blob([res.markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title || "思维导图"}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`导出失败: ${(err as Error).message}`);
    }
  };

  const filtered = (mindmaps ?? []).filter((m) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      m.title.toLowerCase().includes(q) ||
      (m.topic && m.topic.toLowerCase().includes(q))
    );
  });

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = String(evt.target?.result || "");
      setImportContent(text);
      if (!importTitle) {
        setImportTitle(file.name.replace(/\.[^/.]+$/, ""));
      }
    };
    reader.readAsText(file);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = String(evt.target?.result || "");
      setImportContent(text);
      if (!importTitle) {
        setImportTitle(file.name.replace(/\.[^/.]+$/, ""));
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="mx-auto max-w-6xl p-6 md:p-8">
      {/* 顶部标题栏与快捷操作 */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-gray-100 dark:border-gray-800 pb-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🧠</span>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">思维导图</h1>
            <span className="rounded-full bg-brand-50 dark:bg-brand-950/40 border border-brand-200 dark:border-brand-800/60 px-2 py-0.5 text-xs text-brand-700 dark:text-brand-300 font-medium">
              伴学 Agent
            </span>
          </div>
          <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
            结构化概念图谱与专属 Agent 协同工作台，支持任意深度多级延展、Markdown 大纲导入与因材施教深度剖析。
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            className="flex items-center gap-1.5 shadow-sm"
            onClick={() => setGenOpen(true)}
          >
            <span>✨</span>
            <span>AI 一键生成</span>
          </Button>
          <Button
            variant="secondary"
            className="flex items-center gap-1.5"
            onClick={() => setImportOpen(true)}
          >
            <span>📥</span>
            <span>导入文件</span>
          </Button>
          <Button
            variant="secondary"
            className="flex items-center gap-1.5"
            disabled={createBlank.isPending}
            onClick={() => createBlank.mutate()}
          >
            <span>＋</span>
            <span>新建空白导图</span>
          </Button>
        </div>
      </div>

      {/* 搜索与过滤栏 */}
      <div className="mt-6 flex items-center justify-between gap-3">
        <div className="relative w-72">
          <span className="absolute left-3 top-2.5 text-xs text-gray-400">🔍</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索导图标题或领域主题…"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 pl-8 pr-3 py-1.5 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
          />
        </div>
        <span className="text-xs text-gray-400 dark:text-gray-500">
          共 {mindmaps?.length ?? 0} 张导图
        </span>
      </div>

      {/* 导图列表网格 */}
      {isLoading ? (
        <div className="py-20 flex justify-center">
          <Spinner />
        </div>
      ) : isError ? (
        <EmptyState
          icon="⚠️"
          title="导图列表加载失败"
          hint={(error as Error)?.message ?? "服务暂时不可用，请稍后重试"}
          action={
            <Button className="mt-3" variant="secondary" onClick={() => refetch()}>
              重试
            </Button>
          }
        />
      ) : filtered.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-dashed border-gray-200 dark:border-gray-800 p-12 text-center bg-white/40 dark:bg-gray-800/20">
          <div className="text-4xl mb-3">🌿</div>
          <h3 className="text-base font-semibold text-gray-800 dark:text-gray-200">
            {search ? "没有匹配的思维导图" : "还没有创建任何思维导图"}
          </h3>
          <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500 max-w-md mx-auto">
            你可以使用 AI 伴学 Agent 输入任意技术主题一键生成全景思维导图，或者从已有 Markdown 笔记快速导入。
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Button onClick={() => setGenOpen(true)}>✨ AI 一键生成</Button>
            <Button variant="secondary" onClick={() => setImportOpen(true)}>📥 导入 Markdown / JSON</Button>
          </div>
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((m) => (
            <div
              key={m.id}
              onClick={() => navigate(`/mindmap/${m.id}`)}
              className="group relative flex flex-col justify-between rounded-xl border border-gray-200 dark:border-gray-700/80 bg-white dark:bg-gray-800/60 p-4 shadow-xs hover:border-brand-500 dark:hover:border-brand-400 hover:shadow-md transition-all cursor-pointer"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <span className="truncate text-base font-semibold text-gray-900 dark:text-gray-100 group-hover:text-brand-600 dark:group-hover:text-brand-400 transition-colors">
                    {m.title}
                  </span>
                  <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRenamingMap(m);
                        setRenameTitle(m.title);
                      }}
                      className="p-1 rounded text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition"
                      title="重命名"
                    >
                      ✏️
                    </button>
                    <button
                      type="button"
                      onClick={(e) => handleExport(e, m.id, m.title)}
                      className="p-1 rounded text-xs text-gray-400 hover:text-brand-600 dark:hover:text-brand-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition"
                      title="导出 Markdown"
                    >
                      📤
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`确定删除思维导图「${m.title}」？此操作不可撤销。`)) {
                          deleteMutation.mutate(m.id);
                        }
                      }}
                      className="p-1 rounded text-xs text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition"
                      title="删除"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
                {m.topic && (
                  <p className="mt-1 text-xs text-gray-400 dark:text-gray-500 line-clamp-1">
                    领域：{m.topic}
                  </p>
                )}
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-gray-100 dark:border-gray-700/60 pt-3 text-[11px] text-gray-400 dark:text-gray-500">
                <span className="flex items-center gap-1 font-medium text-brand-600 dark:text-brand-400">
                  <span>🌿</span>
                  <span>{m.node_count} 个概念节点</span>
                </span>
                <span>
                  {new Date(m.updated_at).toLocaleDateString("zh-CN", {
                    month: "numeric",
                    day: "numeric",
                    hour: "numeric",
                    minute: "numeric",
                  })}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* AI 一键生成模态框 */}
      <Modal open={genOpen} onClose={() => setGenOpen(false)} title="✨ AI 生成思维导图">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              导图核心主题与领域 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={genPrompt}
              onChange={(e) => setGenPrompt(e.target.value)}
              placeholder="例如：计算机网络传输层与TCP三次握手、React 19 并发机制、微服务架构…"
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              分支层级深度
            </label>
            <div className="mt-1 flex items-center gap-3">
              {[2, 3, 4, 5].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setGenDepth(d)}
                  className={`rounded-lg border px-3 py-1 text-xs font-medium transition ${
                    genDepth === d
                      ? "border-brand-500 bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300"
                      : "border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300"
                  }`}
                >
                  {d} 层 {d === 3 ? "（推荐）" : d === 4 ? "（深入）" : d === 5 ? "（详尽）" : "（简明）"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              可选：参考材料或长文笔记文本（Agent 将基于该文本提取骨架）
            </label>
            <Textarea
              rows={4}
              value={genImportText}
              onChange={(e) => setGenImportText(e.target.value)}
              placeholder="粘贴相关的教材章节、会议纪要或文档内容…"
              className="mt-1 text-xs"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setGenOpen(false)}>
              取消
            </Button>
            <Button
              disabled={generateMap.isPending || !genPrompt.trim()}
              onClick={() => generateMap.mutate()}
            >
              {generateMap.isPending ? (
                <>
                  <Spinner className="mr-1.5 h-3.5 w-3.5" /> 正在构建导图…
                </>
              ) : (
                "立即生成"
              )}
            </Button>
          </div>
        </div>
      </Modal>

      {/* 导入思维导图模态框 */}
      <Modal open={importOpen} onClose={() => setImportOpen(false)} title="📥 导入思维导图">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              导图名称（选填，留空则自动从大纲首行识别）
            </label>
            <input
              type="text"
              value={importTitle}
              onChange={(e) => setImportTitle(e.target.value)}
              placeholder="例如：操作系统架构概览"
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
            />
          </div>

          {/* 拖拽或点击文件上传区域 */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleFileDrop}
            className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-800/40 p-4 text-center hover:border-brand-400 transition"
          >
            <div className="text-xl">📄</div>
            <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
              拖拽 Markdown（.md）或 JSON 文件到此处，或
              <label className="ml-1 text-brand-600 dark:text-brand-400 underline cursor-pointer">
                点击选择文件
                <input
                  type="file"
                  accept=".md,.markdown,.txt,.json"
                  onChange={handleFileInput}
                  className="hidden"
                />
              </label>
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              或者直接在此粘贴 Markdown 层次大纲 / JSON 数据
            </label>
            <Textarea
              rows={6}
              value={importContent}
              onChange={(e) => setImportContent(e.target.value)}
              placeholder={`支持使用 Markdown 标题或列表缩进：\n# 核心主题\n## 一级分支\n- 二级子分支\n  - 三级深入概念`}
              className="mt-1 font-mono text-xs"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setImportOpen(false)}>
              取消
            </Button>
            <Button
              disabled={importMap.isPending || !importContent.trim()}
              onClick={() => importMap.mutate()}
            >
              {importMap.isPending ? (
                <>
                  <Spinner className="mr-1.5 h-3.5 w-3.5" /> 正在解析导入…
                </>
              ) : (
                "确认导入"
              )}
            </Button>
          </div>
        </div>
      </Modal>

      {/* 重命名导图模态框 */}
      <Modal open={!!renamingMap} onClose={() => setRenamingMap(null)} title="✏️ 重命名导图">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              导图名称
            </label>
            <input
              type="text"
              value={renameTitle}
              onChange={(e) => setRenameTitle(e.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setRenamingMap(null)}>
              取消
            </Button>
            <Button
              disabled={renameMutation.isPending || !renameTitle.trim()}
              onClick={() => renameMutation.mutate()}
            >
              保存修改
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
