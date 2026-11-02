// 拍照解题：拍一道题 → AI 流式给出答案与分步解析（独立快捷工具，不建课）
// 局域网手机经 <input capture> 拉起相机（HTTP 非安全上下文 getUserMedia 不可用）
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type { SolveSSEEvent } from "../../lib/types";
import { Button, ErrorText, Input, Spinner } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";
import { createStreamFlusher } from "../../lib/streamFlusher";

const MAX_PHOTOS = 3;
const MAX_PHOTO_MB = 10;

export default function SnapSolvePage() {
  const cameraRef = useRef<HTMLInputElement>(null);
  const albumRef = useRef<HTMLInputElement>(null);
  const [photos, setPhotos] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [hint, setHint] = useState("");
  const [answer, setAnswer] = useState("");
  const [thinking, setThinking] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const answerBoxRef = useRef<HTMLDivElement>(null);
  // 预览 URL 单一路径管理：每个 File 只 create 一次，revoke 只走 revokeAllPreviews
  const previewsRef = useRef<string[]>([]);

  const revokeAllPreviews = () => {
    previewsRef.current.forEach((u) => URL.revokeObjectURL(u));
    previewsRef.current = [];
  };

  // 卸载时中断进行中的流并释放预览（经 ref 取最新值，避免 stale closure 漏 revoke）
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      revokeAllPreviews();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 数学公式渲染：流式期间 deferMath 关闭，结束后整体渲染一次
  useEffect(() => {
    if (!streaming && answerBoxRef.current) {
      try {
        // MarkdownLite 内部已渲染 KaTeX（deferMath 翻转后触发重渲染）
        answerBoxRef.current.setAttribute("data-rendered", "1");
      } catch {
        /* ignore */
      }
    }
  }, [streaming, answer]);

  const addPhotos = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    setError("");
    const incoming: File[] = [];
    for (const f of Array.from(list)) {
      if (!f.type.startsWith("image/")) {
        setError(`「${f.name}」不是图片文件`);
        return;
      }
      if (f.size > MAX_PHOTO_MB * 1024 * 1024) {
        setError(`「${f.name}」超过 ${MAX_PHOTO_MB}MB 上限`);
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
      setError(`一次最多 ${MAX_PHOTOS} 张图片，多余的已忽略`);
    }
  };

  const removePhoto = (i: number) => {
    // 只 revoke 被删项，其余 URL 保持不变（避免重建造成引用丢失）
    URL.revokeObjectURL(previews[i]);
    previewsRef.current = previewsRef.current.filter((_, k) => k !== i);
    setPhotos(photos.filter((_, k) => k !== i));
    setPreviews(previews.filter((_, k) => k !== i));
  };

  const clearAll = () => {
    abortRef.current?.abort();
    revokeAllPreviews();
    setPhotos([]);
    setPreviews([]);
    setAnswer("");
    setError("");
    setThinking(false);
    setStreaming(false);
    if (cameraRef.current) cameraRef.current.value = "";
    if (albumRef.current) albumRef.current.value = "";
  };

  const solve = () => {
    if (photos.length === 0 || thinking) return;
    setError("");
    setAnswer("");
    setThinking(true);
    setStreaming(true);

    // 流式增量缓冲：delta 进 flusher，120ms 批量刷新，避免逐 token 全量重渲染
    const flusher = createStreamFlusher((text) => setAnswer(text));
    let acc = "";
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    api.solve
      .photoSSE(
        photos,
        hint,
        (ev: SolveSSEEvent) => {
          if (ev.type === "delta" && ev.text) {
            setThinking(false);
            acc += ev.text;
            flusher.push(acc);
          } else if (ev.type === "done") {
            flusher.flushNow();
            setThinking(false);
            setStreaming(false);
          } else if (ev.type === "error") {
            flusher.flushNow();
            setThinking(false);
            setStreaming(false);
            setError(ev.detail || "AI 解答遇到异常，请稍后重试");
          }
        },
        ctrl.signal
      )
      .catch((e) => {
        flusher.flushNow();
        if ((e as Error).name !== "AbortError") {
          setThinking(false);
          setStreaming(false);
          setError(`网络或服务异常：${(e as Error).message}`);
        }
      })
      .finally(() => {
        // 服务端干净关流但没发 done/error 事件时不能永久卡在思考/流式态
        setThinking(false);
        setStreaming(false);
      });
  };

  return (
    <div className="mx-auto max-w-3xl p-8">
      <Link to="/" className="text-sm text-gray-500 dark:text-gray-400 hover:text-brand-600">
        ← 返回首页
      </Link>
      <h1 className="mt-4 text-2xl font-bold text-gray-900 dark:text-gray-100">📸 拍照解题</h1>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        拍下题目照片（教材例题、试卷习题、手写题均可），AI 直接给出答案与分步解析。手机点「拍照」即可拉起相机。
      </p>

      {/* 拍照 / 相册入口 */}
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
            onChange={(e) => {
              addPhotos(e.target.files);
              if (cameraRef.current) cameraRef.current.value = "";
            }}
          />
          <span className="text-2xl">📸</span>
          <span className="text-sm font-semibold">拍照</span>
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
            onChange={(e) => {
              addPhotos(e.target.files);
              if (albumRef.current) albumRef.current.value = "";
            }}
          />
          <span className="text-2xl">🖼️</span>
          <span className="text-sm font-semibold">从相册选择</span>
        </button>
      </div>

      {/* 缩略图 */}
      {photos.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>
              已选 {photos.length}/{MAX_PHOTOS} 张
            </span>
            <button type="button" className="text-brand-600 dark:text-brand-400 hover:underline" onClick={clearAll}>
              清空重来
            </button>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {photos.map((p, i) => (
              <div key={i} className="group relative">
                <img
                  src={previews[i]}
                  alt={`题目图片 ${i + 1}`}
                  className="h-28 w-full rounded-lg border border-gray-200 dark:border-gray-700 object-cover"
                />
                <button
                  type="button"
                  onClick={() => removePhoto(i)}
                  className="absolute right-1 top-1 rounded-full bg-black/60 px-1.5 text-xs text-white opacity-0 transition group-hover:opacity-100"
                  title="移除"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 追加说明 */}
      <div className="mt-4">
        <Input
          value={hint}
          onChange={(e) => setHint(e.target.value)}
          placeholder="补充说明（可选）：如「只要第 2 题」「重点讲第二问的思路」"
          className="text-xs"
        />
      </div>

      <Button
        className="mt-4 w-full"
        disabled={photos.length === 0 || thinking || streaming}
        onClick={solve}
      >
        {thinking || streaming ? (
          <>
            <Spinner className="border-white/40" /> AI 解答中（照片越清晰越准）…
          </>
        ) : (
          `🤖 开始解答${photos.length ? `（${photos.length} 张图片）` : ""}`
        )}
      </Button>

      {error && <div className="mt-3"><ErrorText>{error}</ErrorText></div>}

      {/* 解答流式输出 */}
      {(answer || thinking) && (
        <div
          ref={answerBoxRef}
          className="mt-4 rounded-xl border border-brand-200 dark:border-brand-800 bg-brand-50/40 dark:bg-brand-950/20 p-4"
        >
          <div className="mb-2 flex items-center justify-between border-b border-brand-100 dark:border-brand-900/60 pb-2">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-brand-800 dark:text-brand-300">
              🤖 AI 解答
              {streaming && <span className="inline-block h-2 w-2 rounded-full bg-brand-500 animate-ping" />}
            </span>
            {answer && !streaming && (
              <Button variant="ghost" className="text-xs" onClick={clearAll} title="清空，重新拍照提问">
                ↻ 再拍一题
              </Button>
            )}
          </div>
          {thinking && !answer && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-500 dark:text-gray-400">
              <div className="flex space-x-1">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-brand-500 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
              <span>正在识别题目并组织解答…</span>
            </div>
          )}
          {answer && (
            <MarkdownLite
              text={answer}
              deferMath={streaming}
              className="prose prose-sm dark:prose-invert max-w-none leading-relaxed"
            />
          )}
          {streaming && (
            <span className="inline-block h-3.5 w-1.5 ml-0.5 align-middle bg-brand-500 animate-pulse rounded-sm" />
          )}
        </div>
      )}
    </div>
  );
}
