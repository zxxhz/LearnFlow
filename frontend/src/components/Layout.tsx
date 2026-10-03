import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UpdateCheckResult } from "../lib/types";
import { notify } from "../lib/notify";
import { isTauri, tauriSelfUpdate, relaunchApp } from "../lib/updater";
import { getTheme, applyTheme, type Theme } from "../lib/theme";

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

// 应用内自动更新：桌面壳内下载新安装包（带进度）→ 静默安装 → 自动重启；
// 浏览器/局域网模式不渲染（isTauri 为 false），横幅回退「查看发布页」链接（PRD 实现备注 19）
function AutoUpdateButton() {
  const [phase, setPhase] = useState<"idle" | "downloading" | "installing">("idle");
  const [pct, setPct] = useState<number | null>(null);

  if (!isTauri()) return null;

  const run = async () => {
    setPhase("downloading");
    setPct(null);
    try {
      await tauriSelfUpdate((done, total) => {
        setPct(total ? Math.min(100, Math.round((done / total) * 100)) : null);
      });
      setPhase("installing");
      await relaunchApp();
    } catch {
      setPhase("idle");
      notify("更新失败", "自动更新出错，请到发布页手动下载安装包。");
    }
  };

  return (
    <button
      disabled={phase !== "idle"}
      onClick={run}
      className="rounded-md bg-green-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-800 disabled:opacity-70"
    >
      {phase === "idle" && "⬇ 一键更新"}
      {phase === "downloading" && (pct !== null ? `下载中 ${pct}%` : "下载中…")}
      {phase === "installing" && "安装中，即将重启…"}
    </button>
  );
}

export default function Layout() {
  const [navOpen, setNavOpen] = useState(false);
  const [theme, setThemeState] = useState<Theme>(() => getTheme());
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem("update-dismissed") ?? ""
  );

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setThemeState(next);
  };

  // 打开应用时静默检查新版本（后端节流 1h；失败静默）（PRD 实现备注 15）
  const { data: update } = useQuery<UpdateCheckResult>({
    queryKey: ["update-check"],
    queryFn: () => api.update.check(false),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const showBanner =
    update?.has_update && update.latest && dismissed !== update.latest;

  const dismiss = () => {
    if (update?.latest) {
      sessionStorage.setItem("update-dismissed", update.latest);
      setDismissed(update.latest);
    } else {
      setDismissed("*");
    }
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
        {/* 更新提示横幅 */}
        {showBanner && (
          <div className="flex items-center justify-between gap-3 border-b border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/30 px-4 py-2 text-sm text-green-800">
            <span>
              🎉 新版本 <strong>{update!.latest}</strong> 已发布（当前{" "}
              {update!.current}）
            </span>
            <div className="flex items-center gap-2">
              <AutoUpdateButton />
              {update!.url && (
                <a
                  href={update!.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-green-700 dark:text-green-400 underline"
                >
                  查看发布页
                </a>
              )}
              <button
                className="text-xs text-green-700 dark:text-green-400 underline"
                onClick={dismiss}
              >
                本次忽略
              </button>
            </div>
          </div>
        )}
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
        <main className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
