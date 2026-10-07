// 字号调节管理与持久化（课程阅读与题库刷题独立控制）
import { useCallback, useEffect, useState } from "react";
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
      const currentPrefs = query.data?.preferences ?? {
        chapter_length: 3000,
        exercises_per_kp: 3,
        highlight_colors: {},
      };
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

  const setFontSize = useCallback(
    (newSize: number | ((prev: number) => number)) => {
      setFontSizeState((prev) => {
        const next = typeof newSize === "function" ? newSize(prev) : newSize;
        const clamped = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, next));
        try {
          localStorage.setItem(STORAGE_KEYS[target], String(clamped));
        } catch {
          // 忽略存储写入异常
        }
        mutation.mutate(clamped);
        return clamped;
      });
    },
    [target, mutation]
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
