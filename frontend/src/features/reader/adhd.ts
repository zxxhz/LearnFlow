// ADHD 阅读辅助模式管理与工具函数
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { AdhdMode } from "../../lib/types";

export const ADHD_MODE_OPTIONS: { value: AdhdMode; label: string; desc: string }[] = [
  { value: "off", label: "关闭", desc: "原生 Markdown 排版风格" },
  { value: "a", label: "A 模式（段落交替底色 + 圆角）", desc: "各段落使用 6 色循环柔和护眼底色与圆角卡片，防止阅读串行" },
  { value: "b", label: "B 模式（鼠标移入聚焦高亮）", desc: "鼠标移至段落时流畅点亮聚焦底色，平滑缓动切换视线焦点" },
];

export function useAdhdMode() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
    staleTime: 60_000,
  });

  const adhdMode: AdhdMode = query.data?.preferences?.adhd_mode ?? "off";

  const mutation = useMutation({
    mutationFn: async (mode: AdhdMode) => {
      const currentPrefs = query.data?.preferences ?? {
        chapter_length: 3000,
        exercises_per_kp: 3,
        highlight_colors: {},
      };
      return api.settings.update({
        preferences: {
          ...currentPrefs,
          adhd_mode: mode,
        },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  return {
    adhdMode,
    setAdhdMode: mutation.mutate,
    isUpdating: mutation.isPending,
  };
}
