// 全课程问答：章节摘要 + 全文检索命中的原文拼接上下文，LLM 流式回答（不落对话记录）
import { useRef, useState } from "react";
import { api } from "../../lib/api";
import { Button, Spinner } from "../../components/ui";
import MarkdownLite from "../../components/MarkdownLite";

interface Turn {
  role: "user" | "assistant";
  text: string;
}

export default function CourseAskPanel({ courseId }: { courseId: string }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);

  const ask = () => {
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    setTurns((t) => [...t, { role: "user", text: q }, { role: "assistant", text: "" }]);
    setBusy(true);
    const append = (delta: string) =>
      setTurns((t) => {
        const copy = [...t];
        copy[copy.length - 1] = { ...copy[copy.length - 1], text: copy[copy.length - 1].text + delta };
        return copy;
      });
    const finish = (err?: string) => {
      setBusy(false);
      if (err) {
        setTurns((t) => {
          const copy = [...t];
          copy[copy.length - 1] = { ...copy[copy.length - 1], text: copy[copy.length - 1].text || `⚠️ ${err}` };
          return copy;
        });
      }
    };
    abortRef.current = api.courses.ask(courseId, q, append, finish);
  };

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">💬 问整门课</h2>
      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">带着全课程结构与全文检索命中作答；课程没讲到的会明说。</p>
      {turns.length > 0 && (
        <div className="mt-3 max-h-96 space-y-3 overflow-auto">
          {turns.map((t, i) => (
            <div key={i} className={t.role === "user" ? "text-right" : ""}>
              <div
                className={`inline-block max-w-[90%] rounded-lg px-3 py-2 text-left text-sm ${
                  t.role === "user"
                    ? "bg-brand-600 text-white"
                    : "border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 text-gray-800 dark:text-gray-200 [&_p]:my-1"
                }`}
              >
                {t.role === "assistant" ? <MarkdownLite text={t.text || "…"} /> : t.text}
              </div>
            </div>
          ))}
        </div>
      )}
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          ask();
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="比如：这两章里指针和引用的区别是什么？"
          className="flex-1 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-800 dark:text-gray-200 focus:border-brand-500 dark:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        {busy ? (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              abortRef.current?.();
              setBusy(false);
            }}
          >
            <Spinner className="h-3.5 w-3.5" /> 停止
          </Button>
        ) : (
          <Button type="submit" disabled={!question.trim()}>
            提问
          </Button>
        )}
      </form>
    </div>
  );
}
