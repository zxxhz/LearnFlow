// 下载源测速与智能路由配置卡片：为应用更新与环境下载测速择优，支持添加与管理自定义镜像源
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Badge, Button, ErrorText, Input, Modal, Spinner } from "../../components/ui";
import type { DownloadMirrorItem } from "../../lib/types";

export default function DownloadMirrorsSection() {
  const queryClient = useQueryClient();
  const [testingMsg, setTestingMsg] = useState("");

  // 添加/修改自定义镜像源弹窗表单状态
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingMirror, setEditingMirror] = useState<DownloadMirrorItem | null>(null);
  const [customName, setCustomName] = useState("");
  const [customPrefix, setCustomPrefix] = useState("");
  const [customDesc, setCustomDesc] = useState("");
  const [formError, setFormError] = useState("");

  const { data: status, isLoading } = useQuery({
    queryKey: ["settings-mirrors"],
    queryFn: api.settings.mirrors.getStatus,
  });

  const testMutation = useMutation({
    mutationFn: api.settings.mirrors.speedTest,
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
      setTestingMsg(`测速完成！最优源为「${data.active_mirror.name}」`);
      setTimeout(() => setTestingMsg(""), 3500);
    },
    onError: (err) => {
      setTestingMsg(`测速失败: ${(err as Error).message}`);
      setTimeout(() => setTestingMsg(""), 3500);
    },
  });

  const selectMutation = useMutation({
    mutationFn: (args: { mode: "auto" | "manual"; selected_id: string }) =>
      api.settings.mirrors.select(args),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
    },
  });

  const addCustomMutation = useMutation({
    mutationFn: api.settings.mirrors.addCustom,
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
      setIsModalOpen(false);
      setCustomName("");
      setCustomPrefix("");
      setCustomDesc("");
      setFormError("");
      setTestingMsg("已成功添加自定义镜像源！");
      setTimeout(() => setTestingMsg(""), 3500);
    },
    onError: (err) => {
      setFormError((err as Error).message);
    },
  });

  const updateCustomMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { name: string; prefix: string; desc?: string } }) =>
      api.settings.mirrors.updateCustom(id, body),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
      setIsModalOpen(false);
      setEditingMirror(null);
      setCustomName("");
      setCustomPrefix("");
      setCustomDesc("");
      setFormError("");
      setTestingMsg("已成功更新自定义镜像源！");
      setTimeout(() => setTestingMsg(""), 3500);
    },
    onError: (err) => {
      setFormError((err as Error).message);
    },
  });

  const deleteCustomMutation = useMutation({
    mutationFn: api.settings.mirrors.deleteCustom,
    onSuccess: (data) => {
      queryClient.setQueryData(["settings-mirrors"], data);
      setTestingMsg("已移除该自定义镜像源。");
      setTimeout(() => setTestingMsg(""), 3500);
    },
    onError: (err) => {
      setTestingMsg(`删除失败: ${(err as Error).message}`);
      setTimeout(() => setTestingMsg(""), 3500);
    },
  });

  const handleModeChange = (mode: "auto" | "manual") => {
    const manualId =
      status?.selected_id && status.selected_id !== "auto"
        ? status.selected_id
        : status?.fastest_id || "official";

    selectMutation.mutate({
      mode,
      selected_id: mode === "manual" ? manualId : "auto",
    });
  };

  const handleSelectMirror = (item: DownloadMirrorItem) => {
    selectMutation.mutate({
      mode: "manual",
      selected_id: item.id,
    });
  };

  const handleOpenAdd = () => {
    setEditingMirror(null);
    setCustomName("");
    setCustomPrefix("");
    setCustomDesc("");
    setFormError("");
    setIsModalOpen(true);
  };

  const handleOpenEdit = (e: React.MouseEvent, item: DownloadMirrorItem) => {
    e.stopPropagation();
    setEditingMirror(item);
    setCustomName(item.name);
    setCustomPrefix(item.prefix);
    setCustomDesc(item.desc || "");
    setFormError("");
    setIsModalOpen(true);
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    const name = customName.trim();
    let prefix = customPrefix.trim();
    if (!name) {
      setFormError("请输入镜像源名称");
      return;
    }
    if (!prefix) {
      setFormError("请输入镜像加速前缀 URL");
      return;
    }
    if (!prefix.startsWith("http://") && !prefix.startsWith("https://")) {
      setFormError("镜像地址必须以 http:// 或 https:// 开头");
      return;
    }
    if (!prefix.endsWith("/")) {
      prefix += "/";
    }

    if (editingMirror) {
      updateCustomMutation.mutate({
        id: editingMirror.id,
        body: {
          name,
          prefix,
          desc: customDesc.trim() || undefined,
        },
      });
    } else {
      addCustomMutation.mutate({
        name,
        prefix,
        desc: customDesc.trim() || undefined,
      });
    }
  };

  const handleDeleteCustom = (e: React.MouseEvent, item: DownloadMirrorItem) => {
    e.stopPropagation();
    if (window.confirm(`确定要删除自定义镜像「${item.name}」吗？`)) {
      deleteCustomMutation.mutate(item.id);
    }
  };

  if (isLoading) {
    return (
      <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Spinner className="h-4 w-4" /> 正在加载下载源配置…
        </div>
      </section>
    );
  }

  const isAuto = (status?.mode ?? "auto") === "auto";
  const activeId = status?.active_mirror?.id;

  return (
    <section className="mt-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              下载源测速与智能路由
            </h2>
            <Badge color={isAuto ? "blue" : "amber"} className="text-[11px]">
              {isAuto ? "🤖 自动择优中" : "✋ 手动锁定中"}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            用于应用更新安装包、MinGW 编译器及 Python 便携运行时的极速下载。支持并发测速、添加私有加速源并自动切换至最优源。
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            variant="secondary"
            onClick={handleOpenAdd}
            className="text-xs"
          >
            ➕ 添加自定义源
          </Button>

          <Button
            variant="secondary"
            disabled={testMutation.isPending}
            onClick={() => testMutation.mutate()}
            className="text-xs"
          >
            {testMutation.isPending ? (
              <>
                <Spinner className="h-3.5 w-3.5" /> 测速中…
              </>
            ) : (
              "⚡ 立即测速"
            )}
          </Button>
        </div>
      </div>

      {testingMsg && (
        <div className="mt-3 rounded-lg bg-brand-50 dark:bg-brand-950/40 border border-brand-200 dark:border-brand-800/50 px-3 py-1.5 text-xs text-brand-700 dark:text-brand-300">
          {testingMsg}
        </div>
      )}

      {/* 模式选择 */}
      <div className="mt-4 flex items-center gap-4 text-xs text-gray-700 dark:text-gray-300">
        <span className="font-medium text-gray-500 dark:text-gray-400">选择策略：</span>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="mirror-mode"
            checked={isAuto}
            onChange={() => handleModeChange("auto")}
            className="text-brand-600 focus:ring-brand-500"
          />
          <span>🤖 自动选用最快源（推荐）</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="mirror-mode"
            checked={!isAuto}
            onChange={() => handleModeChange("manual")}
            className="text-brand-600 focus:ring-brand-500"
          />
          <span>✋ 手动指定源</span>
        </label>
      </div>

      {/* 镜像列表卡片 */}
      <div className="mt-3.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {status?.results?.map((item) => {
          const isActive = item.id === activeId;
          const isFastest = item.id === status?.fastest_id && item.ok;
          const isCustom = Boolean(item.is_custom);

          return (
            <div
              key={item.id}
              onClick={() => handleSelectMirror(item)}
              className={`relative flex flex-col justify-between rounded-lg border p-3 transition-all cursor-pointer ${
                isActive
                  ? "border-brand-500 bg-brand-50/40 dark:bg-brand-950/20 shadow-xs"
                  : "border-gray-200 dark:border-gray-700/80 bg-gray-50/60 dark:bg-gray-800/40 hover:border-gray-300 dark:hover:border-gray-600"
              }`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                    {item.name}
                    {isCustom && (
                      <span className="rounded bg-purple-100 dark:bg-purple-900/50 px-1 py-0.2 text-[10px] font-normal text-purple-700 dark:text-purple-300">
                        自定义
                      </span>
                    )}
                    {isActive && (
                      <span className="h-2 w-2 rounded-full bg-brand-600 dark:bg-brand-400 animate-pulse" />
                    )}
                  </span>
                  <div className="flex items-center gap-1">
                    {isFastest && (
                      <span className="rounded bg-amber-100 dark:bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300">
                        ⚡ 最快
                      </span>
                    )}
                    {isActive && (
                      <span className="rounded bg-brand-100 dark:bg-brand-900/50 px-1.5 py-0.5 text-[10px] font-medium text-brand-700 dark:text-brand-300">
                        {isAuto ? "使用中" : "已锁定"}
                      </span>
                    )}
                    {isCustom && (
                      <div className="flex items-center gap-0.5">
                        <button
                          type="button"
                          onClick={(e) => handleOpenEdit(e, item)}
                          className="ml-1 text-gray-400 hover:text-brand-600 dark:hover:text-brand-400 p-0.5 transition"
                          title="修改此自定义镜像源"
                        >
                          ✏️
                        </button>
                        <button
                          type="button"
                          onClick={(e) => handleDeleteCustom(e, item)}
                          className="text-gray-400 hover:text-red-600 dark:hover:text-red-400 p-0.5 transition"
                          title="删除此自定义镜像源"
                        >
                          🗑️
                        </button>
                      </div>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400 line-clamp-1">
                  {item.desc}
                </p>
                {item.prefix && (
                  <p className="mt-0.5 font-mono text-[10px] text-gray-400 dark:text-gray-500 truncate" title={item.prefix}>
                    {item.prefix}
                  </p>
                )}
              </div>

              <div className="mt-3 flex items-center justify-between text-[11px] border-t border-gray-100 dark:border-gray-700/50 pt-2">
                <span className="text-gray-400 dark:text-gray-500">
                  {item.latency_ms !== null ? (
                    item.ok ? (
                      <span
                        className={
                          item.latency_ms < 600
                            ? "text-green-600 dark:text-green-400 font-medium"
                            : item.latency_ms < 1500
                            ? "text-amber-600 dark:text-amber-400 font-medium"
                            : "text-red-500 dark:text-red-400"
                        }
                      >
                        ● {item.latency_ms} ms
                      </span>
                    ) : (
                      <span className="text-red-500 dark:text-red-400" title={item.error || ""}>
                        ✕ {item.error || "不可达"}
                      </span>
                    )
                  ) : (
                    "未测速"
                  )}
                </span>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSelectMirror(item);
                  }}
                  className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                    isActive
                      ? "bg-brand-600 text-white"
                      : "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-brand-100 dark:hover:bg-brand-900/60 hover:text-brand-700 dark:hover:text-brand-300"
                  }`}
                >
                  {isActive ? (isAuto ? "当前生效" : "已锁定") : "锁定此源"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* 添加/修改自定义镜像源弹窗 */}
      <Modal
        open={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={editingMirror ? "修改自定义镜像源" : "添加自定义下载镜像源"}
      >
        <form onSubmit={handleFormSubmit} className="space-y-4">
          <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
            支持添加或修改个人搭建的 GitHub 加速节点或国内自建反向代理（如 Cloudflare Workers、Nginx 反代等）。
          </p>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              镜像名称 <span className="text-red-500">*</span>
            </label>
            <Input
              type="text"
              placeholder="例如：我的香港加速节点、FastGH"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              加速前缀 URL <span className="text-red-500">*</span>
            </label>
            <Input
              type="text"
              placeholder="例如：https://ghproxy.net/ 或 https://hub.fastgit.xyz/"
              value={customPrefix}
              onChange={(e) => setCustomPrefix(e.target.value)}
              required
            />
            <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">
              前缀将拼接在 GitHub 原始下载链接前（如 <code>前缀 + https://github.com/...</code>）。
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              描述说明（可选）
            </label>
            <Input
              type="text"
              placeholder="例如：个人自建节点，低延迟高带宽"
              value={customDesc}
              onChange={(e) => setCustomDesc(e.target.value)}
            />
          </div>

          {formError && <ErrorText>{formError}</ErrorText>}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="secondary"
              type="button"
              onClick={() => setIsModalOpen(false)}
            >
              取消
            </Button>
            <Button
              variant="primary"
              type="submit"
              disabled={addCustomMutation.isPending || updateCustomMutation.isPending}
            >
              {addCustomMutation.isPending || updateCustomMutation.isPending ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : null}
              {editingMirror ? "保存修改" : "确认添加"}
            </Button>
          </div>
        </form>
      </Modal>
    </section>
  );
}
