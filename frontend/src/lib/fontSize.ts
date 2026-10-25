// 字号调节管理与持久化（课程阅读与题库刷题独立控制）
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export type FontSizeTarget = "course" | "drill";

export const STORAGE_KEYS = {
  course: "learnflow-course-font-size",
  drill: "learnflow-drill-font-size",
} as const;

export const DEFAULT_FONT_SIZES = {
  course: 16,
  drill: 15,
} as const;

export const MIN_FONT_SIZE = 13;
export const MAX_FONT_SIZE = 24;

export const FONT_SIZE_PRESETS = [13, 14, 15, 16, 17, 18, 20, 22, 24];

function getStoredFontSize(target: FontSizeTarget): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS[target]);
    if (raw) {
      const parsed = parseInt(raw, 10);
      if (!isNaN(parsed) && parsed >= MIN_FONT_SIZE && parsed <= MAX_FONT_SIZE) {
        return parsed;
      }
    }
  } catch {
    // 忽略存储读取异常
  }
  return DEFAULT_FONT_SIZES[target];
}

export function useFontSize(target: FontSizeTarget) {
  const queryClient = useQueryClient();
  const [fontSize, setFontSizeState] = useState<number>(() => getStoredFontSize(target));

  const query = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
    staleTime: 60_000,
  });

  // 当服务端偏好载入后，如本地未曾明确覆盖或服务端有值则同步
  useEffect(() => {
    const serverVal =
      target === "course"
        ? query.data?.preferences?.course_font_size
        : query.data?.preferences?.drill_font_size;
    if (
      serverVal &&
      typeof serverVal === "number" &&
      serverVal >= MIN_FONT_SIZE &&
      serverVal <= MAX_FONT_SIZE
    ) {
      const localRaw = localStorage.getItem(STORAGE_KEYS[target]);
      if (!localRaw) {
        setFontSizeState(serverVal);
        localStorage.setItem(STORAGE_KEYS[target], String(serverVal));
      }
    }
  }, [query.data, target]);

  const mutation = useMutation({
    mutationFn: async (newSize: number) => {
      // 设置未加载完成时跳过服务端持久化，避免用 fallback 默认值覆盖 auto_highlight 等其他偏好
      const currentPrefs = query.data?.preferences;
      if (!currentPrefs) return null;
      return api.settings.update({
        preferences: {
          ...currentPrefs,
          [target === "course" ? "course_font_size" : "drill_font_size"]: newSize,
        },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  // 连续点击 A+/A- 时防抖合并服务端请求（本地 localStorage 即时生效）
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    };
  }, []);
  const persistDebounced = useCallback(
    (newSize: number) => {
      if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
      persistTimerRef.current = setTimeout(() => mutation.mutate(newSize), 600);
    },
    [mutation]
  );

  const fontSizeRef = useRef(fontSize);
  fontSizeRef.current = fontSize;

  const setFontSize = useCallback(
    (newSize: number | ((prev: number) => number)) => {
      // 副作用（localStorage / 服务端持久化）必须在 setState updater 之外执行：
      // React StrictMode 下 updater 会跑两次，导致重复 PUT 与重复写存储
      const next =
        typeof newSize === "function" ? newSize(fontSizeRef.current) : newSize;
      const clamped = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, next));
      setFontSizeState(clamped);
      try {
        localStorage.setItem(STORAGE_KEYS[target], String(clamped));
      } catch {
        // 忽略存储写入异常
      }
      persistDebounced(clamped);
    },
    [target, persistDebounced]
  );

  return {
    fontSize,
    setFontSize,
    min: MIN_FONT_SIZE,
    max: MAX_FONT_SIZE,
    defaultSize: DEFAULT_FONT_SIZES[target],
    isUpdating: mutation.isPending,
  };
}
