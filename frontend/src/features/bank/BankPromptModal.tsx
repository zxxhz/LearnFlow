// 题库 AI 答疑提示词设置弹窗：支持自由编辑、填入系统默认提示词、AI 一键润色并直接就地替换
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Button, Modal, Spinner, Textarea } from "../../components/ui";
import type { Bank } from "../../lib/types";

interface Props {
  open: boolean;
  bank: Bank | null;
  onClose: () => void;
  onSaved?: (updated: Bank) => void;
}

export default function BankPromptModal({ open, bank, onClose, onSaved }: Props) {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const { data: defaultData } = useQuery({
    queryKey: ["bank-default-prompt"],
    queryFn: api.banks.getDefaultPrompt,
    staleTime: Infinity,
  });
  const defaultPrompt = defaultData?.default_prompt || "";

  useEffect(() => {
    if (bank) {
      setPrompt(bank.ai_prompt || "");
      setNotice("");
      setError("");
    }
  }, [bank, open]);

  // AI 润色提示词
  const polish = useMutation({
    mutationFn: async () => {
      if (!bank) return "";
      const base = prompt.trim() || defaultPrompt;
      const res = await api.banks.polishPrompt(base, bank.name);
      return res.polished_prompt;
    },
    onSuccess: (polished) => {
      if (polished) {
        // 在同一个页面把原本的内容就地替换掉，不需要重新打开！
        setPrompt(polished);
        setNotice("✨ AI 润色完成！已在当前页面自动替换原有内容，您可以直接保存或继续微调。");
        setError("");
      }
    },
    onError: (e) => {
      setError(`润色失败：${(e as Error).message}`);
    },
  });

  // 保存设置
  const save = useMutation({
    mutationFn: async () => {
      if (!bank) return;
      return api.banks.update(bank.id, { ai_prompt: prompt.trim() });
    },
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["banks"] });
      if (updated && onSaved) onSaved(updated);
      onClose();
    },
    onError: (e) => {
      setError(`保存失败：${(e as Error).message}`);
    },
  });

  if (!bank) return null;

  const isUsingDefault = !prompt.trim();

  return (
    <Modal open={open} onClose={onClose} title={`⚙️ ${bank.name} · AI 答疑提示词设置`}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-gray-500 dark:text-gray-400">生效规则：</span>
            {isUsingDefault ? (
              <span className="rounded-full bg-blue-50 dark:bg-blue-950/40 px-2 py-0.5 font-medium text-blue-700 dark:text-blue-300">
                当前使用系统默认提示词
              </span>
            ) : (
              <span className="rounded-full bg-amber-50 dark:bg-amber-950/40 px-2 py-0.5 font-medium text-amber-700 dark:text-amber-300">
                已自定义专属提示词
              </span>
            )}
          </div>

          <div className="flex items-center gap-1">
            <Button
              variant="secondary"
              className="text-xs !py-1"
              disabled={polish.isPending}
              onClick={() => polish.mutate()}
              title="利用大模型对提示词进行角色定位、结构化与规范深度优化，并在当前页面自动替换"
            >
              {polish.isPending ? (
                <>
                  <Spinner className="h-3 w-3" /> 润色中…
                </>
              ) : (
                "✨ AI 润色提示词"
              )}
            </Button>
            <Button
              variant="ghost"
              className="text-xs !py-1 text-gray-500 dark:text-gray-400"
              onClick={() => {
                setPrompt(defaultPrompt);
                setNotice("已填入系统默认提示词，您可以基于此进行个性化修改。");
              }}
            >
              📋 填入默认
            </Button>
            {prompt.trim() && (
              <Button
                variant="ghost"
                className="text-xs !py-1 text-gray-400 dark:text-gray-500 hover:text-red-500"
                onClick={() => {
                  setPrompt("");
                  setNotice("已清空，保存后将恢复使用系统默认提示词。");
                }}
              >
                清空为默认
              </Button>
            )}
          </div>
        </div>

        {notice && (
          <div className="rounded-lg bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800 p-2.5 text-xs text-green-700 dark:text-green-300 leading-relaxed transition-all">
            {notice}
          </div>
        )}

        {error && (
          <div className="rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 p-2.5 text-xs text-red-600 dark:text-red-400 leading-relaxed">
            {error}
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
            错题解答 System Prompt（提示词）
          </label>
          <Textarea
            rows={10}
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value);
              setNotice("");
            }}
            placeholder={
              defaultPrompt
                ? `留空将默认使用：\n${defaultPrompt}`
                : "设置该题库回答错误时 AI 解答的指导原则、名师角色定位及解析结构规范…"
            }
            className="font-mono text-xs leading-relaxed"
          />
          <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">
            💡 提示：留空将自动使用系统默认的启发式名师提示词；点击上方「✨ AI 润色提示词」可一键将内容结构化升级并直接替换。
          </p>
        </div>

        <div className="mt-4 flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button disabled={save.isPending || polish.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "保存中…" : "保存设置"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
