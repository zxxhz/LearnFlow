import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

const NAV_ITEMS = [
  { to: "/", label: "首页", icon: "🏠" },
  { to: "/dashboard", label: "仪表盘", icon: "📊" },
  { to: "/review", label: "复习", icon: "🔁" },
  { to: "/feynman", label: "费曼讲解", icon: "🎤" },
  { to: "/settings", label: "设置", icon: "⚙️" },
];

export default function Layout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="flex w-56 shrink-0 flex-col border-r border-gray-200 bg-white">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-xl font-bold text-brand-600">LearnFlow</span>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
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
        <div className="border-t border-gray-100 p-3">
          <button
            onClick={() => {
              navigate("/courses/new");
              queryClient.invalidateQueries();
            }}
            className="w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            ＋ 新建课程
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
