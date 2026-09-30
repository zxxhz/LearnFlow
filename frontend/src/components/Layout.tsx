import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "首页", icon: "🏠" },
  { to: "/dashboard", label: "仪表盘", icon: "📊" },
  { to: "/review", label: "复习", icon: "🔁" },
  { to: "/feynman", label: "费曼讲解", icon: "🎤" },
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
                ? "bg-brand-50 font-medium text-brand-700"
                : "text-gray-600 hover:bg-gray-100"
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
    <div className="space-y-2 border-t border-gray-100 p-3">
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
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
      >
        📄 导入 Markdown
      </button>
    </div>
  );
}

export default function Layout() {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="flex h-screen bg-gray-50">
      {/* 桌面侧栏 */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-gray-200 bg-white md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-xl font-bold text-brand-600">LearnFlow</span>
        </div>
        <NavLinks />
        <NavActions />
      </aside>

      {/* 移动端抽屉 */}
      {navOpen && (
        <div className="fixed inset-0 z-50 md:hidden" onClick={() => setNavOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside
            className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-5">
              <span className="text-xl font-bold text-brand-600">LearnFlow</span>
              <button className="text-gray-400" onClick={() => setNavOpen(false)}>
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
        <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2.5 md:hidden">
          <button
            onClick={() => setNavOpen(true)}
            className="rounded-md p-1.5 text-gray-600 hover:bg-gray-100"
            aria-label="打开菜单"
          >
            ☰
          </button>
          <span className="text-base font-bold text-brand-600">LearnFlow</span>
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
