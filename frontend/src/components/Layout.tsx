import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, getRelayConfig, getServerSystemVersion } from "../lib/api";
import type { UpdateCheckResult, ServerSystemVersion } from "../lib/types";
import { useTheme } from "../lib/theme";
import { safeSessionStorage, safeStorage } from "../lib/safeStorage";
import { isTauri, openExternalUrl } from "../lib/updater";
import UpdateDialog from "./UpdateDialog";
import ServerUpdateDialog from "./ServerUpdateDialog";
import AssistantPanel from "./AssistantPanel";
import { Toast, isModalOpen } from "./ui";
import type { ToastPayload } from "../lib/toast";
import RelayStatusBadge from "./RelayStatusBadge";

const NAV_ITEMS = [
  { to: "/", label: "首页", icon: "🏠" },
  { to: "/mindmap", label: "思维导图", icon: "🧠" },
  { to: "/dashboard", label: "仪表盘", icon: "📊" },
  { to: "/wrongbook", label: "错题本", icon: "📕" },
  { to: "/bank", label: "题库刷题", icon: "🎯" },
  { to: "/search", label: "搜索", icon: "🔍" },
  { to: "/settings", label: "设置", icon: "⚙️" },
];

function NavLinks({ onNavigate, onOpenAssistant }: { onNavigate?: () => void; onOpenAssistant?: () => void }) {
  const { pathname } = useLocation();

  return (
    <nav className="flex-1 space-y-1 px-3">
      {/* 全局 AI 助教入口（非路由按钮，Ctrl+J 同效） */}
      {onOpenAssistant && (
        <button
          type="button"
          onClick={() => {
            onOpenAssistant();
            onNavigate?.();
          }}
          className="mb-2 flex w-full items-center gap-2 rounded-lg border border-brand-200 bg-brand-50/70 px-3 py-2 text-sm font-medium text-brand-700 transition hover:bg-brand-100 dark:border-brand-800 dark:bg-brand-950/40 dark:text-brand-300 dark:hover:bg-brand-900/50"
          title="唤起 AI 助教 (Ctrl+J)"
        >
          <span>🤖</span>
          <span className="flex-1 text-left">AI 助教</span>
          <kbd className="rounded bg-white/70 px-1 text-[10px] text-gray-400 dark:bg-gray-800/80">Ctrl J</kbd>
        </button>
      )}
      {NAV_ITEMS.map((item) => {
        // 首页统辖课程树（课程详情 / 章节阅读 / 新建课程 / 导入课程）均视为首页处于激活态
        const isActive =
          item.to === "/"
            ? pathname === "/" ||
              pathname.startsWith("/courses") ||
              pathname.startsWith("/read") ||
              pathname.startsWith("/import")
            : pathname === item.to || pathname.startsWith(item.to + "/");

        return (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            aria-current={isActive ? "page" : undefined}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${
              isActive
                ? "bg-brand-50 dark:bg-brand-900/40 font-medium text-brand-700 dark:text-brand-300"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`}
          >
            <span>{item.icon}</span>
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
}

function NavActions({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate();
  return (
    <div className="space-y-2 border-t border-gray-100 dark:border-gray-800 p-3">
      <button
        onClick={() => {
          navigate("/courses/new");
          onNavigate?.();
        }}
        className="w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
      >
        ＋ 新建课程
      </button>
      <button
        onClick={() => {
          navigate("/import");
          onNavigate?.();
        }}
        className="w-full rounded-lg border border-gray-300 dark:border-gray-600 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800/50"
      >
        📥 导入课程
      </button>
    </div>
  );
}

/** 移动端导航抽屉：蒙层淡入 + 抽屉从左滑入/滑出（与阅读页抽屉一致的 20ms 挂载 + 过渡 + 延迟卸载模式） */
function MobileNavDrawer({
  open,
  onClose,
  onOpenAssistant,
}: {
  open: boolean;
  onClose: () => void;
  onOpenAssistant: () => void;
}) {
  const [render, setRender] = useState(open);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (open) {
      setRender(true);
      const t = setTimeout(() => setShown(true), 20);
      return () => clearTimeout(t);
    }
    setShown(false);
    const t = setTimeout(() => setRender(false), 200);
    return () => clearTimeout(t);
  }, [open]);

  // 打开期间 Esc 关闭（v0.5.2 体检 P2：移动端抽屉此前无键盘出口）
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!render) return null;
  return (
    <div className="fixed inset-0 z-50 md:hidden" onClick={onClose}>
      <div
        className={`absolute inset-0 bg-black/40 transition-opacity duration-200 ease-out ${
          shown ? "opacity-100" : "opacity-0"
        }`}
      />
      <aside
        className={`absolute inset-y-0 left-0 flex w-64 flex-col bg-white dark:bg-gray-900 shadow-xl transition-transform duration-200 ease-out ${
          shown ? "translate-x-0" : "-translate-x-full"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-5">
          <span className="text-xl font-bold text-brand-600">LearnFlow</span>
          <button
            className="text-gray-400 dark:text-gray-500"
            onClick={onClose}
            aria-label="关闭菜单"
          >
            ✕
          </button>
        </div>
        <NavLinks onNavigate={onClose} onOpenAssistant={onOpenAssistant} />
        <NavActions onNavigate={onClose} />
        <div className="p-3 border-t border-gray-100 dark:border-gray-800">
          <RelayStatusBadge />
        </div>
      </aside>
    </div>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  const isReader = pathname.startsWith("/read/");
  const isMindMapCanvas = pathname.startsWith("/mindmap/") && pathname !== "/mindmap";
  const isImmersive = isReader || isMindMapCanvas;
  const [navOpen, setNavOpen] = useState(false);
  // 导航折叠状态（局域网平板/大屏设备自由折叠侧栏，最大化学习与刷题主界面宽度）
  const [navCollapsed, setNavCollapsed] = useState(() => {
    const saved = safeStorage.get("learnflow-nav-collapsed");
    if (saved !== null) return saved === "true";
    // 局域网平板/小屏设备智能默认：宽度小于 1024px（如 iPad 竖屏 768px）时默认折叠侧栏，避免挤占内容区；大屏默认展开
    return typeof window !== "undefined" && window.innerWidth < 1024;
  });

  const expandNavBtnRef = useRef<HTMLButtonElement | null>(null);
  const prevCollapsedRef = useRef(navCollapsed);
  useEffect(() => {
    // 折叠发生且焦点原本在侧栏内时，把焦点交给顶栏「展开导航」按钮，
    // 键盘用户 Ctrl+B 折叠后不再丢失位置（v0.5.3 体检 P3）
    if (!prevCollapsedRef.current && navCollapsed && expandNavBtnRef.current) {
      const ae = document.activeElement;
      const sidebar = document.querySelector("aside");
      if (ae instanceof HTMLElement && sidebar?.contains(ae)) {
        expandNavBtnRef.current.focus();
      }
    }
    prevCollapsedRef.current = navCollapsed;
  }, [navCollapsed]);
  const toggleNavCollapsed = () => {
    setNavCollapsed((prev) => !prev);
  };

  // 折叠状态持久化（updater 保持纯函数，副作用统一放 effect）
  useEffect(() => {
    safeStorage.set("learnflow-nav-collapsed", String(navCollapsed));
  }, [navCollapsed]);

  // 全局快捷键 Ctrl+B / Cmd+B 切换左侧导航折叠（与阅读页快捷键心智统一）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isImmersive) return;
      if (e.repeat) return; // 长按连发会高频抖动侧栏与 localStorage
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        if (isModalOpen()) return; // 模态打开时不折叠背景侧栏（v0.5.2 体检 P3）
        const target = e.target as HTMLElement | null;
        if (
          target &&
          (target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.tagName === "SELECT" ||
            target.isContentEditable)
        ) {
          return;
        }
        e.preventDefault();
        toggleNavCollapsed();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isImmersive]);

  // 与阅读页共享同一主题订阅，阅读页内切换后侧栏按钮状态保持同步
  const { theme, toggle: toggleTheme } = useTheme();
  const [dialogUpdate, setDialogUpdate] = useState<UpdateCheckResult | null>(null);
  const [dialogServerUpdate, setDialogServerUpdate] = useState<ServerSystemVersion | null>(null);

  // 获取中转配置以区分云端 Web 服务端 vs 本地桌面客户端
  const { data: relayConfig } = useQuery({
    queryKey: ["relay-config"],
    queryFn: getRelayConfig,
    staleTime: 60_000,
    retry: 1,
  });

  const isRelayServer = Boolean(
    relayConfig?.is_relay_server || relayConfig?.service === "LearnFlow-Relay-Server"
  );

  // 1. 桌面端应用内检查更新（仅在本地桌面客户端启用；云端 Web 服务端模式下彻底禁用，避免提示下载 exe）
  const { data: update } = useQuery<UpdateCheckResult>({
    queryKey: ["update-check"],
    queryFn: () => api.update.check(false),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    enabled: !isRelayServer,
  });

  useEffect(() => {
    if (!isRelayServer && update?.has_update && update.latest && safeSessionStorage.get("update-dismissed") !== update.latest) {
      setDialogUpdate(update);
    }
  }, [isRelayServer, update]);

  // 2. 云端服务端在线更新检查（仅在直接访问云端服务端 Web 模式下启用）
  const { data: serverUpdate } = useQuery<ServerSystemVersion>({
    queryKey: ["server-system-version"],
    queryFn: getServerSystemVersion,
    enabled: isRelayServer,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (
      isRelayServer &&
      serverUpdate?.has_update &&
      serverUpdate.latest_version &&
      safeSessionStorage.get("server-update-dismissed") !== serverUpdate.latest_version
    ) {
      setDialogServerUpdate(serverUpdate);
    }
  }, [isRelayServer, serverUpdate]);

  // 设置页「检查更新」发现新版本 → 强制弹窗（无视本会话已忽略）
  useEffect(() => {
    const onFound = (e: Event) => setDialogUpdate((e as CustomEvent<UpdateCheckResult>).detail);
    window.addEventListener("learnflow:update-found", onFound);
    return () => window.removeEventListener("learnflow:update-found", onFound);
  }, []);

  // 设置页或外部触发服务端版本更新弹窗
  useEffect(() => {
    const onServerFound = (e: Event) =>
      setDialogServerUpdate((e as CustomEvent<ServerSystemVersion>).detail);
    window.addEventListener("learnflow:server-update-found", onServerFound);
    return () => window.removeEventListener("learnflow:server-update-found", onServerFound);
  }, []);

  // 全局轻量 Toast 反馈（导出完成、系统提示等）
  const [globalToast, setGlobalToast] = useState<ToastPayload | null>(null);
  const toastSeqRef = useRef(0);
  useEffect(() => {
    const onToast = (e: Event) => {
      const detail = (e as CustomEvent<ToastPayload>).detail;
      if (detail && detail.message) {
        // 递增 seq：连续相同文案时 key 变化强制重挂载，第二条独立计时（v0.5.2 体检 P3）
        toastSeqRef.current += 1;
        setGlobalToast({ ...detail, seq: toastSeqRef.current });
      }
    };
    window.addEventListener("learnflow:toast", onToast);
    return () => window.removeEventListener("learnflow:toast", onToast);
  }, []);

  // v0.5.0 全局 AI 助教：任意页面 Ctrl+J 唤起 / Esc 关闭（global 会话，跨课程提问与学情咨询）
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantClosing, setAssistantClosing] = useState(false);
  // 关闭动画定时器须可取消：关后 300ms 内重开时，陈旧回调会把刚滑入的面板再次关掉（v0.5.1 体检 P2）
  const assistantCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const openGlobalAssistant = () => {
    if (assistantCloseTimerRef.current) {
      clearTimeout(assistantCloseTimerRef.current);
      assistantCloseTimerRef.current = null;
    }
    setAssistantClosing(false);
    setAssistantOpen(true);
  };
  const closeGlobalAssistant = () => {
    setAssistantClosing(true);
    if (assistantCloseTimerRef.current) clearTimeout(assistantCloseTimerRef.current);
    assistantCloseTimerRef.current = setTimeout(() => {
      assistantCloseTimerRef.current = null;
      setAssistantOpen(false);
      setAssistantClosing(false);
    }, 300);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        if (e.repeat) return;
        if (isModalOpen()) return; // 模态打开时唤起的助手面板会被 z-50 弹窗盖住，直接不响应
        const target = e.target as HTMLElement | null;
        if (
          target &&
          (target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.tagName === "SELECT" ||
            target.isContentEditable)
        ) {
          return;
        }
        e.preventDefault();
        openGlobalAssistant();
      } else if (e.key === "Escape" && assistantOpen) {
        closeGlobalAssistant();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assistantOpen]);

  // 桌面壳模式下全局拦截 target="_blank" 外部链接，唤起系统默认浏览器
  useEffect(() => {
    if (!isTauri()) return;
    const onDocClick = (e: MouseEvent) => {
      if (e.defaultPrevented) return;
      const anchor = (e.target as HTMLElement | null)?.closest?.("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (href && (href.startsWith("http://") || href.startsWith("https://")) && anchor.target === "_blank") {
        e.preventDefault();
        openExternalUrl(href);
      }
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const closeUpdateDialog = () => {
    if (dialogUpdate?.latest) safeSessionStorage.set("update-dismissed", dialogUpdate.latest);
    setDialogUpdate(null);
  };

  const closeServerUpdateDialog = () => {
    if (dialogServerUpdate?.latest_version) {
      safeSessionStorage.set("server-update-dismissed", dialogServerUpdate.latest_version);
    }
    setDialogServerUpdate(null);
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      {/* 桌面/平板侧栏：进入课程阅读或思维导图画布后隐藏，释放全宽给沉浸式工作台；支持自由折叠 */}
      {!isImmersive && (
        <aside
          className={`hidden shrink-0 flex-col border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 md:flex transition-all duration-300 ease-in-out overflow-hidden ${
            // invisible（visibility:hidden）使子树同时退出 Tab 序与无障碍树：
            // 仅 opacity+pointer-events 会让 11 个隐形按钮仍可被键盘聚焦，与 aria-hidden 矛盾
            navCollapsed ? "invisible w-0 border-r-0 opacity-0 pointer-events-none" : "visible w-56 opacity-100"
          }`}
          aria-hidden={navCollapsed}
        >
          <div className="flex h-full w-56 flex-col shrink-0">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-800/60">
              <span className="text-xl font-bold text-brand-600">LearnFlow</span>
              <button
                type="button"
                onClick={toggleNavCollapsed}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-200 transition"
                title="折叠导航 (Ctrl+B)"
                aria-label="折叠导航"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <line x1="9" y1="3" x2="9" y2="21" />
                  <path d="M15 9l-3 3 3 3" />
                </svg>
              </button>
            </div>
            <NavLinks onOpenAssistant={openGlobalAssistant} />
            <NavActions />
            <div className="flex flex-col gap-2 border-t border-gray-100 dark:border-gray-800 p-3">
              <div className="flex items-center justify-between">
                <button
                  onClick={toggleTheme}
                  className="flex flex-1 items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
                  title="切换深色 / 浅色"
                >
                  <span>{theme === "dark" ? "☀️" : "🌙"}</span>
                  <span className="truncate">{theme === "dark" ? "浅色" : "深色"}</span>
                </button>
              </div>
              <div className="px-1">
                <RelayStatusBadge />
              </div>
            </div>
          </div>
        </aside>
      )}

      {/* 移动端抽屉（带进出场动画） */}
      {!isImmersive && (
        <MobileNavDrawer
          open={navOpen}
          onClose={() => setNavOpen(false)}
          onOpenAssistant={openGlobalAssistant}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 顶栏：移动端常驻；平板/桌面端在左侧导航折叠后出现展开按钮 */}
        {!isImmersive && (
          <header
            className={`items-center gap-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-2.5 transition-all ${
              navCollapsed ? "flex" : "flex md:hidden"
            }`}
          >
            {/* 移动端汉堡按钮（< md 打开抽屉） */}
            <button
              onClick={() => setNavOpen(true)}
              className="rounded-md p-1.5 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 md:hidden"
              aria-label="打开菜单"
            >
              ☰
            </button>

            {/* 平板/桌面端折叠后提供的展开导航按钮（>= md 显示） */}
            {navCollapsed && (
              <button
                type="button"
                ref={expandNavBtnRef}
                onClick={toggleNavCollapsed}
                className="hidden md:inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-2.5 py-1 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-brand-600 dark:hover:text-brand-400 transition"
                title="展开左侧导航 (Ctrl+B)"
                aria-label="展开左侧导航"
              >
                <svg className="w-3.5 h-3.5 text-brand-600 dark:text-brand-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <line x1="9" y1="3" x2="9" y2="21" />
                  <path d="M13 9l3 3-3 3" />
                </svg>
                <span>展开导航</span>
              </button>
            )}

            <span className="text-base font-bold text-brand-600">LearnFlow</span>

            <div className="ml-auto flex items-center gap-2">
              <RelayStatusBadge />
              <button
                onClick={toggleTheme}
                className="rounded-md p-1.5 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
                aria-label="切换深色 / 浅色"
                title="切换深色 / 浅色"
              >
                {theme === "dark" ? "☀️" : "🌙"}
              </button>
            </div>
          </header>
        )}
        {/* scrollbar-gutter: 滚动条出现/消失不再让居中内容横移（各页面标题位置保持一致） */}
        <main className={`min-h-0 flex-1 ${isImmersive ? "overflow-hidden" : "overflow-auto [scrollbar-gutter:stable]"}`}>
          <Outlet />
        </main>
      </div>
      {!isRelayServer && <UpdateDialog update={dialogUpdate} onClose={closeUpdateDialog} />}
      {isRelayServer && (
        <ServerUpdateDialog
          update={dialogServerUpdate}
          onClose={closeServerUpdateDialog}
        />
      )}
      {/* 全局 AI 助教抽屉（Ctrl+J / 侧栏入口）：global 会话 */}
      {(assistantOpen || assistantClosing) && (
        <AssistantPanel
          open={assistantOpen}
          closing={assistantClosing}
          contextType="global"
          contextId="global"
          contextLabel="🧭 全局提问"
          scene={null}
          onClose={closeGlobalAssistant}
        />
      )}
      {globalToast && (
        <Toast
          key={globalToast.seq}
          message={globalToast.message}
          duration={globalToast.duration ?? 4500}
          action={globalToast.action}
          onDone={() => setGlobalToast(null)}
        />
      )}
    </div>
  );
}
