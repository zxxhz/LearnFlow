// 深色模式：class 策略（tailwind darkMode:"class"），偏好持久化 localStorage
// 多组件（Layout 侧栏与阅读页顶栏）同时使用 useTheme：通过订阅同步，避免各自 state 不同步
import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "learnflow-theme";

const listeners = new Set<() => void>();

export function getTheme(): Theme {
  // 受限 WebView / 隐私模式下 localStorage 访问可能抛错（否则会在 main.tsx 启动时白屏）
  let saved: string | null = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch {
    /* fallthrough */
  }
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(t: Theme): void {
  document.documentElement.classList.toggle("dark", t === "dark");
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* 存储不可用时仅影响记忆，不影响本次会话 */
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getTheme);

  useEffect(() => {
    const listener = () => setThemeState(getTheme());
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const setTheme = useCallback((t: Theme) => {
    applyTheme(t);
    listeners.forEach((l) => l());
  }, []);

  const toggle = useCallback(() => {
    setTheme(getTheme() === "dark" ? "light" : "dark");
  }, [setTheme]);

  return { theme, setTheme, toggle };
}
