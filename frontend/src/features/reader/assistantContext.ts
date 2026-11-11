// 阅读页统一助教的调用上下文：练习卡片等子组件经此唤起右侧 AssistantPanel，
// 免去逐层透传回调；同一章节内讲义/练习共用 document 会话由 ReaderPage 统一持有。
import { createContext, useContext } from "react";
import type { AssistantSceneContext } from "../../lib/types";

export interface ReaderAssistantApi {
  /** 打开统一助教面板：scene 决定本轮挂载的现场上下文与场景护栏 */
  openAssistant: (scene: AssistantSceneContext, label: string) => void;
}

export const ReaderAssistantContext = createContext<ReaderAssistantApi | null>(null);

export function useReaderAssistant(): ReaderAssistantApi | null {
  return useContext(ReaderAssistantContext);
}
