// 深色模式：class 策略（tailwind darkMode:"class"），偏好持久化 localStorage
import { useState } from "react";

export type Theme = "light" | "dark";
const KEY = "learnflow-theme";

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
  const setTheme = (t: Theme) => {
    applyTheme(t);
    setThemeState(t);
  };
  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");
  return { theme, setTheme, toggle };
}
