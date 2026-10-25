// 深色模式：class 策略（tailwind darkMode:"class"），偏好持久化 localStorage
// 多组件（Layout 侧栏与阅读页顶栏）同时使用 useTheme：通过订阅同步，避免各自 state 不同步
import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "learnflow-theme";

const listeners = new Set<() => void>();

export function getTheme(): Theme {
  const saved = localStorage.getItem(KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(t: Theme): void {
  document.documentElement.classList.toggle("dark", t === "dark");
  localStorage.setItem(KEY, t);
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
