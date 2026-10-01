// 划线高亮四色的单一来源：设置页可自定义，标注卡/抽屉/正文 mark 全部从这里取色
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { AnnotationColor } from "../../lib/types";

export const HL_COLOR_KEYS: AnnotationColor[] = ["yellow", "green", "blue", "pink"];

export const HL_LABELS: Record<AnnotationColor, string> = {
  yellow: "黄",
  green: "绿",
  blue: "蓝",
  pink: "粉",
};

export const HL_DEFAULTS: Record<AnnotationColor, string> = {
  yellow: "#fde68a",
  green: "#bbf7d0",
  blue: "#bfdbfe",
  pink: "#fbcfe8",
};

/** 读取用户自定义高亮色（未加载/缺项回落默认）。 */
export function useHlColors(): Record<AnnotationColor, string> {
  const q = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
    staleTime: 60_000,
  });
  const saved = q.data?.preferences.highlight_colors ?? {};
  return {
    yellow: saved.yellow || HL_DEFAULTS.yellow,
    green: saved.green || HL_DEFAULTS.green,
    blue: saved.blue || HL_DEFAULTS.blue,
    pink: saved.pink || HL_DEFAULTS.pink,
  };
}

/** 转成 CSS 变量 style（挂在阅读器根容器，正文 mark 染色用）。 */
export function hlColorVars(colors: Record<AnnotationColor, string>): React.CSSProperties {
  return {
    "--hl-yellow": colors.yellow,
    "--hl-green": colors.green,
    "--hl-blue": colors.blue,
    "--hl-pink": colors.pink,
  } as React.CSSProperties;
}
