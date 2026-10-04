import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UpdateCheckResult } from "../lib/types";
import { getTheme, applyTheme, type Theme } from "../lib/theme";
import { isTauri, openExternalUrl } from "../lib/updater";
import UpdateDialog from "./UpdateDialog";

const NAV_ITEMS = [
  { to: "/", label: "首页", icon: "🏠" },
  { to: "/dashboard", label: "仪表盘", icon: "📊" },
  { to: "/wrongbook", label: "错题本", icon: "📕" },
  { to: "/bank", label: "题库刷题", icon: "🎯" },
  { to: "/search", label: "搜索", icon: "🔍" },
  { to: "/settings", label: "设置", icon: "⚙️" },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-1 px-3">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${
              isActive
                ? "bg-brand-50 dark:bg-brand-900/40 font-medium text-brand-700"
                : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`
          }
        >
          <span>{item.icon}</span>
          {item.label}
        </NavLink>
      ))}
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
        📄 导入 Markdown
      </button>
    </div>
  );
}

export default function Layout() {
  const [navOpen, setNavOpen] = useState(false);
  const [theme, setThemeState] = useState<Theme>(() => getTheme());
  const [dialogUpdate, setDialogUpdate] = useState<UpdateCheckResult | null>(null);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setThemeState(next);
  };

  // 打开应用时静默检查新版本（后端节流 1h；失败静默）→ 发现更新弹窗；
  // 同一会话内点过「稍后」的版本不再自动弹（PRD 实现备注 15）
  const { data: update } = useQuery<UpdateCheckResult>({
    queryKey: ["update-check"],
    queryFn: () => api.update.check(false),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (update?.has_update && update.latest && sessionStorage.getItem("update-dismissed") !== update.latest) {
      setDialogUpdate(update);
    }
  }, [update]);

  // 设置页「检查更新」发现新版本 → 强制弹窗（无视本会话已忽略）
  useEffect(() => {
    const onFound = (e: Event) => setDialogUpdate((e as CustomEvent<UpdateCheckResult>).detail);
    window.addEventListener("learnflow:update-found", onFound);
    return () => window.removeEventListener("learnflow:update-found", onFound);
  }, []);

  // 桌面壳模式下全局拦截 target="_blank" 外部链接，唤起系统默认浏览器
  useEffect(() => {
    if (!isTauri()) return;
    const onDocClick = (e: MouseEvent) => {
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
    if (dialogUpdate?.latest) sessionStorage.setItem("update-dismissed", dialogUpdate.latest);
    setDialogUpdate(null);
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      {/* 桌面侧栏 */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-xl font-bold text-brand-600">LearnFlow</span>
        </div>
        <NavLinks />
        <NavActions />
        <div className="border-t border-gray-100 dark:border-gray-800 p-3">
          <button
            onClick={toggleTheme}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            title="切换深色 / 浅色"
          >
            <span>{theme === "dark" ? "☀️" : "🌙"}</span>
            {theme === "dark" ? "浅色模式" : "深色模式"}
          </button>
        </div>
      </aside>

      {/* 移动端抽屉 */}
      {navOpen && (
        <div className="fixed inset-0 z-50 md:hidden" onClick={() => setNavOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside
            className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white dark:bg-gray-900 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-5">
              <span className="text-xl font-bold text-brand-600">LearnFlow</span>
              <button className="text-gray-400 dark:text-gray-500" onClick={() => setNavOpen(false)}>
                ✕
              </button>
            </div>
            <NavLinks onNavigate={() => setNavOpen(false)} />
            <NavActions onNavigate={() => setNavOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 移动端顶栏 */}
        <header className="flex items-center gap-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-2.5 md:hidden">
          <button
            onClick={() => setNavOpen(true)}
            className="rounded-md p-1.5 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="打开菜单"
          >
            ☰
          </button>
          <span className="text-base font-bold text-brand-600">LearnFlow</span>
          <button
            onClick={toggleTheme}
            className="ml-auto rounded-md p-1.5 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="切换深色 / 浅色"
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </header>
        {/* scrollbar-gutter: 滚动条出现/消失不再让居中内容横移（各页面标题位置保持一致） */}
        <main className="min-h-0 flex-1 overflow-auto [scrollbar-gutter:stable]">
          <Outlet />
        </main>
      </div>
      <UpdateDialog update={dialogUpdate} onClose={closeUpdateDialog} />
    </div>
  );
}
