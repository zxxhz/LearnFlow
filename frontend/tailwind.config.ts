import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          // 深色模式页面/卡片底色（ReaderPage、抽屉、Agent 面板等大量使用）
          950: "#1e1b4b",
        },
        // 深色模式设置卡片底色（SettingsPage、LearnerProfileSection 使用）
        gray: {
          850: "#1b1f2a",
        },
      },
      // Tailwind v3 默认无 xs/2xs 阴影档，项目内多处组件引用
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "2xs": "0 1px 1px 0 rgb(0 0 0 / 0.04)",
      },
      scale: {
        102: "1.02",
      },
      spacing: {
        4.5: "1.125rem",
        0.2: "0.05rem",
      },
    },
  },
  plugins: [],
} satisfies Config;
