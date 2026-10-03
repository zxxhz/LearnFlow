// 题库列表：题库卡片 / 两步导入（预览→确认）/ 删除
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorText,
  Modal,
  Spinner,
} from "../../components/ui";
import type { Bank, BankAnalysis } from "../../lib/types";

const TYPE_LABEL: Record<string, string> = { single: "单选", multi: "多选", judge: "判断" };

export default function BankListPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["banks"], queryFn: api.banks.list });
  const [importOpen, setImportOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Bank | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => api.banks.remove(id),
    onSuccess: () => {
      setDeleteTarget(null);
      qc.invalidateQueries({ queryKey: ["banks"] });
    },
  });

  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">🎯 题库刷题</h1>
        <Button onClick={() => setImportOpen(true)}>📥 导入题库</Button>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        导入 .xls / .xlsx 题库表格（题型 / 题干 / 选项A-H / 正确答案 / 解析 / 难度），随机组轮作答，错题自动入池。
      </p>

      {isLoading ? (
        <div className="mt-10 flex justify-center">
          <Spinner />
        </div>
      ) : error ? (
        <ErrorText>{(error as Error).message}</ErrorText>
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon="🗂️"
          title="还没有题库"
          hint="把题库 Excel 拖进来即可开刷：支持 .xls / .xlsx，第一行为表头。"
          action={
            <Button className="mt-3" onClick={() => setImportOpen(true)}>
              📥 导入第一个题库
            </Button>
          }
        />
      ) : (
        <div className="mt-4 space-y-3">
          {data.map((b) => (
            <div
              key={b.id}
              className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 transition hover:border-brand-300 dark:hover:border-brand-700"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link
                    to={`/bank/${b.id}`}
                    className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100 hover:text-brand-600 dark:hover:text-brand-400"
                  >
                    {b.name}
                  </Link>
                  <p className="mt-0.5 truncate text-xs text-gray-400 dark:text-gray-500">
                    {b.source_file} · 导入于 {b.created_at.slice(0, 10)}
                  </p>
                </div>
                <Button variant="ghost" className="shrink-0 text-xs" onClick={() => setDeleteTarget(b)}>
                  删除
                </Button>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <Badge>{b.stats.question_count} 题</Badge>
                <Badge color={b.stats.answered > 0 ? "blue" : "gray"}>已答 {b.stats.answered}</Badge>
                {b.stats.attempts > 0 && <Badge color="green">正确率 {b.stats.accuracy}%</Badge>}
                {b.stats.wrong_count > 0 && (
                  <Badge color="red">错题 {b.stats.wrong_count}</Badge>
                )}
                <Link
                  to={`/bank/${b.id}`}
                  className="ml-auto text-brand-600 dark:text-brand-400 hover:underline"
                >
                  开始刷题 →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} />
      <ConfirmDialog
        open={!!deleteTarget}
        title="删除题库"
        message={`确定删除「${deleteTarget?.name}」？题目与全部作答记录将一并清除。`}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

function ImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<BankAnalysis | null>(null);
  const [error, setError] = useState("");

  const reset = () => {
    setFile(null);
    setAnalysis(null);
    setError("");
  };
  const close = () => {
    reset();
    onClose();
  };

  const analyze = useMutation({
    mutationFn: (f: File) => api.banks.analyze(f),
    onSuccess: (a) => {
      setAnalysis(a);
      setError("");
    },
    onError: (e) => setError((e as Error).message),
  });
  const importBank = useMutation({
    mutationFn: (f: File) => api.banks.import(f, analysis?.name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["banks"] });
      close();
    },
    onError: (e) => setError((e as Error).message),
  });

  function pick(f: File | undefined) {
    if (!f) return;
    reset();
    setFile(f);
    analyze.mutate(f);
  }

  return (
    <Modal open={open} onClose={close} title="📥 导入题库">
      <input
        ref={fileRef}
        type="file"
        accept=".xls,.xlsx"
        className="hidden"
        onChange={(e) => pick(e.target.files?.[0])}
      />

      {!file ? (
        <button
          onClick={() => fileRef.current?.click()}
          className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 py-10 text-gray-500 dark:text-gray-400 hover:border-brand-400 hover:text-brand-600 dark:hover:text-brand-400"
        >
          <span className="text-3xl">📄</span>
          <span className="text-sm">点击选择 .xls / .xlsx 题库文件</span>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            列布局：题型 / 题干 / 选项A-H / 正确答案 / … / 解析 / 难度
          </span>
        </button>
      ) : analyze.isPending ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500 dark:text-gray-400">
          <Spinner /> 正在解析「{file.name}」…
        </div>
      ) : analysis ? (
        <div>
          <div className="rounded-lg bg-gray-50 dark:bg-gray-800/60 p-3 text-sm">
            <div className="font-medium text-gray-900 dark:text-gray-100">{analysis.name}</div>
            <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              共 <span className="font-bold">{analysis.question_count}</span> 道题
              {analysis.skipped_total > 0 && (
                <>，跳过 {analysis.skipped_total} 行（空行/格式不符）</>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(analysis.by_type).map(([t, n]) => (
                <Badge key={t}>
                  {TYPE_LABEL[t] ?? t} {n}
                </Badge>
              ))}
            </div>
            <div className="mt-3 space-y-1.5 border-t border-gray-200 dark:border-gray-700 pt-2">
              {analysis.samples.map((s) => (
                <div key={s.seq} className="truncate text-xs text-gray-500 dark:text-gray-400">
                  <span className="text-gray-400 dark:text-gray-500">{s.seq}. </span>
                  {s.title}
                </div>
              ))}
            </div>
          </div>
          <ErrorText>{error}</ErrorText>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => { reset(); }}>
              重选文件
            </Button>
            <Button disabled={importBank.isPending} onClick={() => file && importBank.mutate(file)}>
              {importBank.isPending ? (
                <>
                  <Spinner className="h-3.5 w-3.5" /> 导入中…
                </>
              ) : (
                `导入 ${analysis.question_count} 题`
              )}
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <p className="text-sm text-gray-600 dark:text-gray-400">「{file.name}」解析失败</p>
          <ErrorText>{error}</ErrorText>
          <div className="mt-4 flex justify-end">
            <Button variant="secondary" onClick={() => fileRef.current?.click()}>
              重选文件
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
