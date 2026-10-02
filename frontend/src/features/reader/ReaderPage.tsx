// 阅读器主页面：块渲染 + 划线提问 + 目录 + 标注管理 + 重生成（PRD §5.2/§5.3）
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { subscribeSSE } from "../../lib/sse";
import { alignSections, parseBlocks } from "../../lib/markdown";
import { anchorFromSelection, type AnchorRange } from "../../lib/anchor";
import type { Annotation, AnnotationColor, ProgressSSEEvent } from "../../lib/types";
import { Button, Modal, Spinner, Textarea } from "../../components/ui";
import BlockView from "./BlockView";
import SelectionToolbar from "./SelectionToolbar";
import AnnotationCard from "./AnnotationCard";
import TocSidebar, { buildToc } from "./TocSidebar";
import AnnotationsDrawer from "./AnnotationsDrawer";
import ExerciseDrawer from "./ExerciseDrawer";
import { hlColorVars, useHlColors } from "./colors";

export default function ReaderPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const hlColors = useHlColors();

  const contentQuery = useQuery({
    queryKey: ["doc", documentId],
    queryFn: () => api.documents.getContent(documentId!),
    enabled: !!documentId,
  });
  const annsQuery = useQuery({
    queryKey: ["doc-anns", documentId],
    queryFn: () => api.annotations.listForDoc(documentId!),
    enabled: !!documentId,
  });
  const kpsQuery = useQuery({
    queryKey: ["doc-kps", documentId],
    queryFn: () => api.knowledgePoints.forDoc(documentId!),
    enabled: !!documentId,
  });
  const courseId = contentQuery.data?.document.course_id;
  const courseQuery = useQuery({
    queryKey: ["course", courseId],
    queryFn: () => api.courses.get(courseId!),
    enabled: !!courseId,
  });
  const execsQuery = useQuery({
    queryKey: ["execs", documentId],
    queryFn: () => api.documents.executions(documentId!),
    enabled: !!documentId,
  });
  const exercisesQuery = useQuery({
    queryKey: ["exercises", documentId],
    queryFn: () => api.exercises.list(documentId!),
    enabled: !!documentId,
  });

  const content = contentQuery.data;
  const annotations = annsQuery.data ?? [];

  // 解析与块对齐（前后端同规则，PRD 实现备注 2）
  const parsed = useMemo(() => (content ? parseBlocks(content.markdown) : []), [content]);
  const sectionIdOf = useCallback(
    (i: number) => sectionMap.get(i),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [content]
  );
  const sectionMap = useMemo(
    () => (content ? alignSections(parsed, content.blocks) : new Map<number, string>()),
    [parsed, content]
  );
  const annsBySection = useMemo(() => {
    const m = new Map<string, Annotation[]>();
    for (const a of annotations) {
      const list = m.get(a.section_id) ?? [];
      list.push(a);
      m.set(a.section_id, list);
    }
    return m;
  }, [annotations]);
  const tocItems = useMemo(() => buildToc(parsed, sectionIdOf), [parsed, sectionIdOf]);

  // ===== UI 状态 =====
  const [selection, setSelection] = useState<{ anchor: AnchorRange; rect: DOMRect } | null>(null);
  const [toolbarColor, setToolbarColor] = useState<AnnotationColor>("yellow");
  const [creating, setCreating] = useState(false);
  const [activeAnn, setActiveAnn] = useState<Annotation | null>(null);
  const [convIdCache, setConvIdCache] = useState<Record<string, string>>({});
  const [convId, setConvId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [kpOpen, setKpOpen] = useState(false);
  const [exerciseOpen, setExerciseOpen] = useState(false);
  const [exerciseFocus, setExerciseFocus] = useState<string | null>(null);
  const [reAnchoring, setReAnchoring] = useState<Annotation | null>(null);
  const [flashSection, setFlashSection] = useState<string | null>(null);
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenInstruction, setRegenInstruction] = useState("");
  const [regenMsg, setRegenMsg] = useState("");
  const [runningSection, setRunningSection] = useState<string | null>(null);
  const [runError, setRunError] = useState("");
  const [tocOpen, setTocOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  const execBySection = useMemo(
    () => new Map((execsQuery.data ?? []).map((e) => [e.section_id, e])),
    [execsQuery.data]
  );

  // 运行代码块（PRD §5.8）：结果由后端持久化，查询刷新后回显
  const onRunCode = async (sectionId: string, lang: string, code: string) => {
    if (!documentId) return;
    setRunningSection(sectionId);
    setRunError("");
    try {
      await api.executions.run({
        document_id: documentId,
        section_id: sectionId,
        language: lang,
        code,
      });
      queryClient.invalidateQueries({ queryKey: ["execs", documentId] });
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setRunningSection(null);
    }
  };

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["doc-anns", documentId] });
  }, [queryClient, documentId]);

  // ===== 选区 → 工具条 =====
  const captureSelection = useCallback(() => {
    if (reAnchoring) return; // 重挂载模式有自己的处理
    const anchor = anchorFromSelection();
    if (!anchor) {
      setSelection(null);
      return;
    }
    const sel = window.getSelection();
    const rect = sel && sel.rangeCount > 0 ? sel.getRangeAt(0).getBoundingClientRect() : null;
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      setSelection(null);
      return;
    }
    setSelection({ anchor, rect });
  }, [reAnchoring]);

  useEffect(() => {
    const onMouseUp = () => setTimeout(captureSelection, 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSelection(null);
        setReAnchoring(null);
      }
    };
    // 触屏：长按选择后 touchend 捕获选区（PRD §5.9 平板适配）
    document.addEventListener("mouseup", onMouseUp);
    document.addEventListener("touchend", onMouseUp);
    document.addEventListener("keyup", onKey);
    return () => {
      document.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("touchend", onMouseUp);
      document.removeEventListener("keyup", onKey);
    };
  }, [captureSelection]);

  const createAnnotation = useMutation({
    mutationFn: async (openCard: boolean) => {
      if (!selection || !documentId) return null;
      const res = await api.annotations.create(documentId, {
        ...selection.anchor,
        color: toolbarColor,
      });
      return { res, openCard };
    },
    onSuccess: (data) => {
      if (!data) return;
      window.getSelection()?.removeAllRanges();
      setSelection(null);
      setConvIdCache((prev) => ({ ...prev, [data.res.annotation.id]: data.res.conversation_id }));
      invalidate();
      if (data.openCard) openAnnotation(data.res.annotation, data.res.conversation_id);
    },
    onError: (e) => alert((e as Error).message),
  });

  // ===== 卡片与定位 =====
  const openAnnotation = async (a: Annotation, knownConvId?: string) => {
    setActiveAnn(a);
    setKpOpen(false);
    const cached = knownConvId ?? convIdCache[a.id];
    if (cached) {
      setConvId(cached);
      return;
    }
    try {
      const r = await api.annotations.conversation(a.id);
      setConvIdCache((prev) => ({ ...prev, [a.id]: r.conversation_id }));
      setConvId(r.conversation_id);
    } catch {
      setConvId(null);
    }
  };

  const jumpTo = (sectionId: string, annId?: string) => {
    const el = document.querySelector(`[data-section-id="${sectionId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setFlashSection(sectionId);
      setTimeout(() => setFlashSection(null), 1600);
    }
    if (annId) {
      // 闪示高亮由 BlockView 的 activeAnnId 处理
      setActiveAnn((prev) => (prev && prev.id === annId ? prev : prev));
    }
  };

  // URL ?section= 定位（费曼漏洞跳转入口）
  useEffect(() => {
    const target = searchParams.get("section");
    if (!target || !content) return;
    const t = setTimeout(() => jumpTo(target), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, searchParams]);

  // ===== 重新挂载（orphan → 重新划选，PRD §9.3） =====
  useEffect(() => {
    if (!reAnchoring) return;
    const onMouseUp = () => {
      setTimeout(() => {
        const anchor = anchorFromSelection();
        if (!anchor) return;
        api.annotations
          .update(reAnchoring.id, { anchor })
          .then(() => {
            setReAnchoring(null);
            window.getSelection()?.removeAllRanges();
            invalidate();
          })
          .catch((e) => alert((e as Error).message));
      }, 0);
    };
    document.addEventListener("mouseup", onMouseUp);
    return () => document.removeEventListener("mouseup", onMouseUp);
  }, [reAnchoring, invalidate]);

  // ===== 阅读进度记忆 =====
  useEffect(() => {
    if (!documentId || !content) return;
    const saved = localStorage.getItem(`reading-progress-${documentId}`);
    if (saved) window.scrollTo(0, Number(saved));
    const onScroll = () => {
      const pct = window.scrollY;
      localStorage.setItem(`reading-progress-${documentId}`, String(pct));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [documentId, content]);

  // ===== 重新生成本章 =====
  const regenerate = useMutation({
    mutationFn: () => api.documents.regenerate(documentId!, regenInstruction.trim() || undefined),
    onSuccess: () => {
      setRegenOpen(false);
      setRegenMsg("重新生成中…");
      const ac = new AbortController();
      subscribeSSE(
        `/courses/${courseId}/progress`,
        (ev: ProgressSSEEvent) => {
          if (ev.type === "chapter_done") {
            setRegenMsg("");
            queryClient.invalidateQueries({ queryKey: ["doc", documentId] });
            invalidate();
            queryClient.invalidateQueries({ queryKey: ["doc-kps", documentId] });
            queryClient.invalidateQueries({ queryKey: ["exercises", documentId] });
          } else if (ev.type === "chapter_failed") {
            setRegenMsg(`重新生成失败：${ev.error ?? "未知错误"}`);
          }
        },
        ac.signal
      ).catch(() => setRegenMsg(""));
    },
    onError: (e) => alert((e as Error).message),
  });

  if (contentQuery.isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (contentQuery.error || !content) {
    return (
      <div className="p-10 text-center text-sm text-gray-500">
        {contentQuery.error ? contentQuery.error.message : "文档不存在"}
        <div className="mt-3">
          <Link to="/" className="text-brand-600 underline">
            返回首页
          </Link>
        </div>
      </div>
    );
  }

  const doc = content.document;
  const docs = courseQuery.data?.documents ?? [];
  const idx = docs.findIndex((d) => d.document_id === doc.id);
  const prevDoc = idx > 0 ? docs[idx - 1] : null;
  const nextDoc = idx >= 0 && idx < docs.length - 1 ? docs[idx + 1] : null;
  const activeKps = kpsQuery.data ?? [];
  const orphanCount = annotations.filter((a) => a.status === "orphan").length;

  return (
    <div className="flex min-h-screen bg-white">
      {/* 目录：桌面常驻侧栏；小屏收起，用浮动按钮打开 */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 overflow-auto border-r border-gray-100 bg-gray-50/50 py-5 lg:block">
        <div className="px-4 pb-3">
          <Link to={`/courses/${courseId}`} className="text-xs text-gray-400 hover:text-brand-600">
            ← {courseQuery.data?.title ?? "课程"}
          </Link>
          <div className="mt-1 truncate text-sm font-semibold text-gray-800">{doc.title}</div>
        </div>
        <TocSidebar items={tocItems} onJump={(sid) => jumpTo(sid)} />
      </aside>

      {/* 正文列 */}
      <div className="relative mx-auto w-full max-w-3xl px-4 py-8 md:px-10">
        {/* 页头 */}
        <div className="sticky top-0 z-20 -mx-4 mb-6 flex items-center justify-between gap-2 border-b border-gray-100 bg-white/90 px-4 py-3 backdrop-blur md:-mx-10 md:px-10">
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              className="text-xs lg:hidden"
              onClick={() => setTocOpen(true)}
            >
              ☰ 目录
            </Button>
            <Button
              variant="ghost"
              className="hidden text-xs sm:inline-flex"
              disabled={!prevDoc}
              onClick={() => prevDoc && navigate(`/read/${prevDoc.document_id}`)}
            >
              ← 上一章
            </Button>
            <Button
              variant="ghost"
              className="hidden text-xs sm:inline-flex"
              disabled={!nextDoc}
              onClick={() => nextDoc && navigate(`/read/${nextDoc.document_id}`)}
            >
              下一章 →
            </Button>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" className="text-xs" onClick={() => setKpOpen((v) => !v)}>
              💡 知识点 {activeKps.length > 0 && activeKps.length}
            </Button>
            <Button
              variant="ghost"
              className="text-xs"
              onClick={() => {
                setExerciseOpen((v) => !v);
                setExerciseFocus(null);
              }}
            >
              📝 练习 {(exercisesQuery.data?.length ?? 0) > 0 && exercisesQuery.data!.length}
            </Button>
            <Button variant="ghost" className="text-xs" onClick={() => setDrawerOpen((v) => !v)}>
              🖍 标注 {annotations.length > 0 && annotations.length}
            </Button>
            {doc.source === "imported" ? (
              <span className="rounded-full bg-blue-100 px-2.5 py-1 text-xs text-blue-700">
                导入文档 · 原文保留
              </span>
            ) : (
              <Button variant="ghost" className="text-xs" onClick={() => setRegenOpen(true)}>
                ♻️ 重新生成本章
              </Button>
            )}
          </div>
        </div>

        {regenMsg && (
          <div className="mb-4 flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-2 text-sm text-blue-700">
            {regenMsg.includes("失败") ? "❌" : <Spinner className="h-4 w-4" />} {regenMsg}
          </div>
        )}

        {/* 重新挂载模式提示条 */}
        {reAnchoring && (
          <div className="sticky top-14 z-20 mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
            正在重新挂载标注「{reAnchoring.exact.slice(0, 24)}…」，请在正文中重新划选该内容，
            <button className="ml-1 underline" onClick={() => setReAnchoring(null)}>
              取消（Esc）
            </button>
          </div>
        )}

        {/* 文档块 */}
        <div ref={contentRef} className="pb-24" style={hlColorVars(hlColors)}>
          {parsed.map((b, i) => {
            const sid = sectionIdOf(i);
            return (
              <BlockView
                key={`${i}-${sid ?? "none"}`}
                block={b}
                sectionId={sid}
                annotations={sid ? annsBySection.get(sid) ?? [] : []}
                activeAnnId={activeAnn?.id ?? null}
                onOpenAnnotation={(a) => openAnnotation(a)}
                flashSectionId={flashSection}
                execution={sid ? execBySection.get(sid) ?? null : null}
                running={runningSection === sid}
                runError={runningSection === sid ? runError : ""}
                onRun={onRunCode}
              />
            );
          })}
        </div>
      </div>

      {/* 小屏目录浮层 */}
      {tocOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setTocOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="absolute inset-y-0 left-0 w-72 overflow-auto bg-white p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="truncate text-sm font-semibold text-gray-800">{doc.title}</span>
              <button className="text-gray-400" onClick={() => setTocOpen(false)}>
                ✕
              </button>
            </div>
            <TocSidebar
              items={tocItems}
              onJump={(sid) => {
                jumpTo(sid);
                setTocOpen(false);
              }}
            />
          </div>
        </div>
      )}

      {/* 知识点浮层 */}
      {kpOpen && (
        <div className="fixed right-6 top-14 z-30 w-80 rounded-xl border border-gray-200 bg-white p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-900">本章知识点</span>
            <button className="text-gray-400 hover:text-gray-600" onClick={() => setKpOpen(false)}>
              ✕
            </button>
          </div>
          {activeKps.length === 0 ? (
            <p className="py-4 text-center text-xs text-gray-400">（暂无知识点）</p>
          ) : (
            <div className="max-h-[60vh] space-y-2 overflow-auto">
              {activeKps.map((kp) => (
                <div key={kp.id} className="rounded-lg border border-gray-100 p-2.5">
                  <div className="text-sm font-medium text-gray-800">{kp.title}</div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-gray-500">{kp.summary}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <Link
                      to={`/feynman?kp=${kp.id}`}
                      className="text-xs text-brand-600 underline"
                    >
                      🎤 费曼讲解
                    </Link>
                    <button
                      className="text-xs text-brand-600 underline"
                      onClick={() => {
                        setKpOpen(false);
                        setExerciseFocus(kp.id);
                        setExerciseOpen(true);
                      }}
                    >
                      📝 练习
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 练习抽屉 */}
      {exerciseOpen && (
        <ExerciseDrawer
          documentId={doc.id}
          kps={activeKps}
          exercises={exercisesQuery.data ?? []}
          focusKpId={exerciseFocus}
          onClose={() => {
            setExerciseOpen(false);
            setExerciseFocus(null);
          }}
        />
      )}

      {/* 划线工具条 */}
      {selection && !activeAnn && (
        <SelectionToolbar
          anchor={selection.anchor}
          rect={{ top: selection.rect.top, left: selection.rect.left, width: selection.rect.width }}
          color={toolbarColor}
          busy={creating || createAnnotation.isPending}
          onColorChange={setToolbarColor}
          onAsk={() => createAnnotation.mutate(true)}
          onHighlight={() => createAnnotation.mutate(false)}
        />
      )}

      {/* 标注抽屉 */}
      {drawerOpen && (
        <AnnotationsDrawer
          annotations={annotations}
          activeAnnId={activeAnn?.id ?? null}
          reAnchoring={reAnchoring}
          onOpen={(a) => {
            openAnnotation(a);
            jumpTo(a.section_id, a.id);
          }}
          onStartReAnchor={setReAnchoring}
          onDelete={(a) => {
            if (confirm("删除该标注及其对话？")) {
              api.annotations.remove(a.id).then(() => {
                invalidate();
                if (activeAnn?.id === a.id) {
                  setActiveAnn(null);
                  setConvId(null);
                }
              });
            }
          }}
        />
      )}

      {/* 提问卡片 */}
      {activeAnn && convId && (
        <AnnotationCard
          key={activeAnn.id}
          annotation={activeAnn}
          conversationId={convId}
          onClose={() => {
            setActiveAnn(null);
            setConvId(null);
          }}
          onJump={(a) => jumpTo(a.section_id, a.id)}
        />
      )}

      {/* 重新生成对话框 */}
      <Modal open={regenOpen} onClose={() => setRegenOpen(false)} title="重新生成本章">
        <p className="text-sm text-gray-600">
          将重新生成本章内容（当前版本会保留为历史快照，标注会尽力保留锚定）。
        </p>
        <Textarea
          className="mt-3"
          rows={3}
          value={regenInstruction}
          onChange={(e) => setRegenInstruction(e.target.value)}
          placeholder="可选：对重新生成的调整要求，如「推导再详细一点」「多举一个例子」"
        />
        {orphanCount > 0 && (
          <p className="mt-2 text-xs text-amber-600">
            注意：本章有 {orphanCount} 条 orphan 标注，重新生成后可在标注抽屉中重新挂载。
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRegenOpen(false)}>
            取消
          </Button>
          <Button disabled={regenerate.isPending} onClick={() => regenerate.mutate()}>
            {regenerate.isPending ? "提交中…" : "开始重新生成"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
