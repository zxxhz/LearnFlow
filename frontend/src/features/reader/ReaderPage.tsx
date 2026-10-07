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
import { useTheme } from "../../lib/theme";
import { useAdhdMode } from "./adhd";
import { useFontSize } from "../../lib/fontSize";
import { FontSizeControl } from "../../components/FontSizeControl";

export default function ReaderPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const hlColors = useHlColors();
  const { theme, toggle: toggleTheme } = useTheme();
  const { adhdMode, setAdhdMode } = useAdhdMode();
  const { fontSize: courseFontSize, setFontSize: setCourseFontSize } = useFontSize("course");


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

  // 阅读时长心跳：页面可见时每 30s 上报一次（后端按本地日聚合，PRD §5.6 延伸）
  useEffect(() => {
    if (!documentId) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") {
        api.study.ping(30).catch(() => {});
      }
    }, 30_000);
    return () => clearInterval(timer);
  }, [documentId]);

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
  const paragraphIndices = useMemo(() => {
    let count = 0;
    return parsed.map((b) => (b.type !== "heading" && b.type !== "code" ? count++ : -1));
  }, [parsed]);


  // ===== UI 状态 =====
  const [selection, setSelection] = useState<{ anchor: AnchorRange; rect: DOMRect } | null>(null);
  const [toolbarColor, setToolbarColor] = useState<AnnotationColor>("yellow");
  const [creating, setCreating] = useState(false);
  const [activeAnn, setActiveAnn] = useState<Annotation | null>(null);
  const [isClosingCard, setIsClosingCard] = useState(false);
  const currentActiveAnn = useMemo(() => {
    if (!activeAnn) return null;
    return annotations.find((a) => a.id === activeAnn.id) ?? activeAnn;
  }, [activeAnn, annotations]);
  const [convIdCache, setConvIdCache] = useState<Record<string, string>>({});
  const [convId, setConvId] = useState<string | null>(null);
  const isCardOpen = !!(currentActiveAnn && convId) && !isClosingCard;
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isClosingDrawer, setIsClosingDrawer] = useState(false);
  const [kpOpen, setKpOpen] = useState(false);
  const [isClosingKp, setIsClosingKp] = useState(false);
  const [exerciseOpen, setExerciseOpen] = useState(false);
  const [isClosingExercise, setIsClosingExercise] = useState(false);
  const [exerciseFocus, setExerciseFocus] = useState<string | null>(null);
  const [reAnchoring, setReAnchoring] = useState<Annotation | null>(null);
  const [flashSection, setFlashSection] = useState<string | null>(null);
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenInstruction, setRegenInstruction] = useState("");
  const [regenAutoHighlight, setRegenAutoHighlight] = useState(true);
  const [regenMsg, setRegenMsg] = useState("");
  const [runningSection, setRunningSection] = useState<string | null>(null);
  const [runError, setRunError] = useState("");
  const [tocOpen, setTocOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    const saved = localStorage.getItem("learnflow-reader-sidebar-open");
    return saved !== null ? saved === "true" : true;
  });

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => {
      const next = !prev;
      localStorage.setItem("learnflow-reader-sidebar-open", String(next));
      return next;
    });
  }, []);
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

  // ===== 右侧面板平滑关闭与调度 =====
  const closeAnnotation = useCallback(() => {
    setIsClosingCard(true);
    setTimeout(() => {
      setActiveAnn(null);
      setConvId(null);
      setIsClosingCard(false);
    }, 300);
  }, []);

  const closeDrawer = useCallback(() => {
    setIsClosingDrawer(true);
    setTimeout(() => {
      setDrawerOpen(false);
      setIsClosingDrawer(false);
    }, 300);
  }, []);

  const closeExercise = useCallback(() => {
    setIsClosingExercise(true);
    setTimeout(() => {
      setExerciseOpen(false);
      setExerciseFocus(null);
      setIsClosingExercise(false);
    }, 300);
  }, []);

  const closeKp = useCallback(() => {
    setIsClosingKp(true);
    setTimeout(() => {
      setKpOpen(false);
      setIsClosingKp(false);
    }, 300);
  }, []);

  // 互斥打开
  const openDrawer = useCallback(() => {
    if (activeAnn) closeAnnotation();
    if (exerciseOpen) closeExercise();
    if (kpOpen) closeKp();
    setIsClosingDrawer(false);
    setDrawerOpen(true);
  }, [activeAnn, exerciseOpen, kpOpen, closeAnnotation, closeExercise, closeKp]);

  const openExercise = useCallback(
    (focusId?: string | null) => {
      if (activeAnn) closeAnnotation();
      if (drawerOpen) closeDrawer();
      if (kpOpen) closeKp();
      setIsClosingExercise(false);
      setExerciseOpen(true);
      setExerciseFocus(focusId ?? null);
    },
    [activeAnn, drawerOpen, kpOpen, closeAnnotation, closeDrawer, closeKp]
  );

  const openKp = useCallback(() => {
    if (activeAnn) closeAnnotation();
    if (drawerOpen) closeDrawer();
    if (exerciseOpen) closeExercise();
    setIsClosingKp(false);
    setKpOpen(true);
  }, [activeAnn, drawerOpen, exerciseOpen, closeAnnotation, closeDrawer, closeExercise]);

  const isRightPanelOpen = Boolean(
    isCardOpen ||
      (drawerOpen && !isClosingDrawer) ||
      (exerciseOpen && !isClosingExercise) ||
      (kpOpen && !isClosingKp)
  );

  useEffect(() => {
    const onMouseUp = () => setTimeout(captureSelection, 0);
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleSidebar();
        return;
      }
      if (e.key === "Escape") {
        setSelection(null);
        setReAnchoring(null);
        if (activeAnn) closeAnnotation();
        if (drawerOpen) closeDrawer();
        if (exerciseOpen) closeExercise();
        if (kpOpen) closeKp();
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
  }, [
    captureSelection,
    activeAnn,
    drawerOpen,
    exerciseOpen,
    kpOpen,
    closeAnnotation,
    closeDrawer,
    closeExercise,
    closeKp,
    toggleSidebar,
  ]);

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
    if (drawerOpen) closeDrawer();
    if (exerciseOpen) closeExercise();
    if (kpOpen) closeKp();
    setIsClosingCard(false);
    setActiveAnn(a);
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

  // URL ?section= 定位（知识点浮层跳转入口）
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
    mutationFn: () =>
      api.documents.regenerate(
        documentId!,
        regenInstruction.trim() || undefined,
        regenAutoHighlight
      ),
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
      <div className="p-10 text-center text-sm text-gray-500 dark:text-gray-400">
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
    <div className="flex h-full w-full bg-white dark:bg-gray-900 overflow-hidden">
      {/* 目录：桌面左侧栏；固定不随文章滑动，支持丝滑折叠展开 */}
      <aside
        className={`hidden h-full w-72 shrink-0 flex-col border-r border-gray-100 dark:border-gray-800 bg-gray-50/80 dark:bg-gray-800/40 md:flex transition-all duration-300 ease-in-out ${
          sidebarOpen ? "ml-0 opacity-100 pointer-events-auto" : "-ml-72 opacity-0 pointer-events-none border-r-0"
        }`}
      >
        {/* 顶部：返回首页、课程名、折叠按钮 */}
        <div className="border-b border-gray-200/60 dark:border-gray-700/60 p-4">
          <div className="mb-2 flex items-center justify-between">
            <Link
              to="/"
              className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-brand-600 dark:text-gray-400 dark:hover:text-brand-400 transition"
              title="返回应用首页"
            >
              <span>←</span>
              <span>返回首页</span>
            </Link>
            <div className="flex items-center gap-1.5">
              {courseId && (
                <Link
                  to={`/courses/${courseId}`}
                  className="text-xs text-gray-400 hover:text-brand-600 dark:hover:text-brand-400 transition mr-1"
                  title="课程详情与设置"
                >
                  课程详情
                </Link>
              )}
              <button
                type="button"
                onClick={toggleSidebar}
                className="flex h-6 w-6 items-center justify-center rounded text-xs text-gray-400 hover:bg-gray-200/60 dark:hover:bg-gray-700/60 hover:text-gray-600 dark:hover:text-gray-200 transition"
                title="折叠目录 (Ctrl+B)"
                aria-label="折叠目录"
              >
                ◀
              </button>
            </div>
          </div>
          <div className="truncate text-sm font-bold text-gray-900 dark:text-gray-100" title={courseQuery.data?.title}>
            {courseQuery.data?.title ?? "课程"}
          </div>
        </div>

        {/* 目录树：全课程章节 + 当前章小节（独立上下滚动） */}
        <div className="flex-1 overflow-y-auto px-2 py-3">
          <TocSidebar
            items={tocItems}
            chapters={docs}
            currentDocId={doc.id}
            onJump={(sid) => jumpTo(sid)}
            onSelectChapter={(docId) => navigate(`/read/${docId}`)}
          />
        </div>

        {/* 底部：进度与深浅色模式切换 */}
        <div className="border-t border-gray-200/60 dark:border-gray-700/60 p-3">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>
              {docs.length > 0 ? `第 ${idx + 1} / ${docs.length} 章` : ""}
            </span>
            <button
              onClick={toggleTheme}
              className="flex items-center gap-1 rounded-md px-2 py-1 hover:bg-gray-200/60 dark:hover:bg-gray-700/60 transition"
              title="切换深浅色主题"
            >
              <span>{theme === "dark" ? "☀️" : "🌙"}</span>
              <span>{theme === "dark" ? "浅色" : "深色"}</span>
            </button>
          </div>
        </div>
      </aside>

      {/* 正文主区域：独立纵向滚动，右侧面板打开时平滑向左避让，关闭时丝滑复原 */}
      <main
        className={`flex-1 h-full overflow-y-auto min-w-0 transition-all duration-300 ease-out ${
          isRightPanelOpen ? "md:mr-[420px]" : "mr-0"
        }`}
      >
        <div className="relative mx-auto w-full max-w-3xl px-4 py-8 md:px-10">
        {/* 页头 */}
        <div className="sticky top-0 z-20 -mx-4 mb-6 flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900/90 px-4 py-3 backdrop-blur md:-mx-10 md:px-10">
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              className="text-xs md:hidden"
              onClick={() => setTocOpen(true)}
            >
              ☰ 目录
            </Button>
            <Button
              variant="ghost"
              className="hidden text-xs md:inline-flex items-center gap-1"
              onClick={toggleSidebar}
              title={sidebarOpen ? "折叠目录 (Ctrl+B)" : "展开目录 (Ctrl+B)"}
            >
              <span>{sidebarOpen ? "◀" : "▶"}</span>
              <span>{sidebarOpen ? "折叠目录" : "展开目录"}</span>
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
            <Button
              variant="ghost"
              className={`text-xs transition-colors ${
                kpOpen && !isClosingKp
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300 font-semibold"
                  : ""
              }`}
              onClick={() => (kpOpen ? closeKp() : openKp())}
            >
              💡 知识点 {activeKps.length > 0 && activeKps.length}
            </Button>
            <Button
              variant="ghost"
              className={`text-xs transition-colors ${
                exerciseOpen && !isClosingExercise
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300 font-semibold"
                  : ""
              }`}
              onClick={() => (exerciseOpen ? closeExercise() : openExercise(null))}
            >
              🎮 闯关 {(exercisesQuery.data?.length ?? 0) > 0 && exercisesQuery.data!.length}
            </Button>
            <Button
              variant="ghost"
              className={`text-xs transition-colors ${
                drawerOpen && !isClosingDrawer
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300 font-semibold"
                  : ""
              }`}
              onClick={() => (drawerOpen ? closeDrawer() : openDrawer())}
            >
              🖍 标注 {annotations.length > 0 && annotations.length}
            </Button>
            {/* ADHD 辅助阅读模式快捷切换按钮 */}
            <button
              type="button"
              onClick={() => {
                const next = adhdMode === "off" ? "a" : adhdMode === "a" ? "b" : "off";
                setAdhdMode(next);
              }}
              className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
                adhdMode === "a"
                  ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
                  : adhdMode === "b"
                  ? "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"
                  : "border-gray-200 dark:border-gray-700 bg-transparent text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              }`}
              title={`当前 ADHD 模式：${adhdMode === "off" ? "关闭" : adhdMode === "a" ? "A（交替底色）" : "B（悬停高亮）"}，点击快捷切换`}
            >
              <span>🧠 ADHD:</span>
              <span className="font-bold">
                {adhdMode === "off" ? "关" : adhdMode === "a" ? "A" : "B"}
              </span>
            </button>
            {/* 字号调节组件 */}
            <FontSizeControl
              value={courseFontSize}
              onChange={setCourseFontSize}
              defaultValue={16}
              label="字号"
            />
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
          <div className="sticky top-14 z-20 mb-4 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-900/30 px-4 py-2 text-sm text-amber-800 dark:text-amber-300">
            正在重新挂载标注「{reAnchoring.exact.slice(0, 24)}…」，请在正文中重新划选该内容，
            <button className="ml-1 underline" onClick={() => setReAnchoring(null)}>
              取消（Esc）
            </button>
          </div>
        )}

        {/* 文档块 */}
        <div
          ref={contentRef}
          className="pb-24 reader-content-root"
          style={{
            ...hlColorVars(hlColors),
            "--course-font-size": `${courseFontSize}px`,
          } as React.CSSProperties}
        >
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
                adhdMode={adhdMode}
                pIndex={paragraphIndices[i]}
              />
            );
          })}
        </div>

      </div>
      </main>

      {/* 小屏目录浮层 */}
      {tocOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setTocOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="absolute inset-y-0 left-0 flex w-72 flex-col bg-white dark:bg-gray-900 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 p-4">
              <span className="truncate text-sm font-bold text-gray-900 dark:text-gray-100">
                {courseQuery.data?.title ?? doc.title}
              </span>
              <button className="text-gray-400 dark:text-gray-500" onClick={() => setTocOpen(false)}>
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              <TocSidebar
                items={tocItems}
                chapters={docs}
                currentDocId={doc.id}
                onJump={(sid) => {
                  jumpTo(sid);
                  setTocOpen(false);
                }}
                onSelectChapter={(docId) => {
                  navigate(`/read/${docId}`);
                  setTocOpen(false);
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* 知识点抽屉：统一右侧 420px 滑入动效与正文平移避让 */}
      {kpOpen && (
        <div
          className={`fixed right-0 top-0 z-40 flex h-full w-full flex-col border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-2xl sm:w-[420px] transition-transform duration-300 ease-out transform ${
            !isClosingKp ? "translate-x-0" : "translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">💡 本章知识点</span>
              <span className="rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-0.5 text-xs text-gray-500 dark:text-gray-400">
                {activeKps.length}
              </span>
            </div>
            <button
              className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
              onClick={closeKp}
              title="关闭"
            >
              ✕
            </button>
          </div>
          {activeKps.length === 0 ? (
            <p className="py-12 text-center text-xs text-gray-400 dark:text-gray-500">（本章暂无拆解出的知识点）</p>
          ) : (
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {activeKps.map((kp) => (
                <div
                  key={kp.id}
                  className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800/40 p-3.5 shadow-sm hover:border-gray-300 dark:hover:border-gray-600 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-gray-800 dark:text-gray-200">{kp.title}</div>
                    <Button
                      variant="ghost"
                      className="text-xs text-brand-600 dark:text-brand-400 hover:text-brand-700"
                      onClick={() => {
                        closeKp();
                        openExercise(kp.id);
                      }}
                    >
                      🎮 关联闯关
                    </Button>
                  </div>
                  <p className="mt-1.5 text-xs text-gray-600 dark:text-gray-400 leading-relaxed">{kp.summary}</p>
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
          closing={isClosingExercise}
          onClose={closeExercise}
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
          closing={isClosingDrawer}
          onOpen={(a) => {
            closeDrawer();
            openAnnotation(a);
            jumpTo(a.section_id, a.id);
          }}
          onStartReAnchor={setReAnchoring}
          onDelete={(a) => {
            if (confirm("删除该标注及其对话？")) {
              api.annotations.remove(a.id).then(() => {
                invalidate();
                if (activeAnn?.id === a.id) {
                  closeAnnotation();
                }
              });
            }
          }}
          onClose={closeDrawer}
        />
      )}

      {/* 提问卡片 */}
      {currentActiveAnn && convId && (
        <AnnotationCard
          key={currentActiveAnn.id}
          annotation={currentActiveAnn}
          conversationId={convId}
          closing={isClosingCard}
          onClose={closeAnnotation}
          onJump={(a) => jumpTo(a.section_id, a.id)}
        />
      )}

      {/* 重新生成对话框 */}
      <Modal open={regenOpen} onClose={() => setRegenOpen(false)} title="重新生成本章">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          将重新生成本章内容（当前版本会保留为历史快照，标注会尽力保留锚定）。
        </p>
        <Textarea
          className="mt-3"
          rows={3}
          value={regenInstruction}
          onChange={(e) => setRegenInstruction(e.target.value)}
          placeholder="可选：对重新生成的调整要求，如「推导再详细一点」「多举一个例子」"
        />
        <label className="mt-3 flex items-center gap-2 text-xs text-gray-700 dark:text-gray-300 select-none cursor-pointer">
          <input
            type="checkbox"
            checked={regenAutoHighlight}
            onChange={(e) => setRegenAutoHighlight(e.target.checked)}
            className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
          />
          <span>🖍 重新生成时自动划重点</span>
        </label>
        {orphanCount > 0 && (
          <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
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
