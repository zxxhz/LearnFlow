// 思维导图树结构工具：画布页 / 节点详情抽屉共用的递归查找
import type { MindMapNode } from "./types";

/** 深度优先在树中查找指定 id 的节点（含根节点），未命中返回 null */
export function findNodeInTree(node: MindMapNode, targetId: string): MindMapNode | null {
  if (node.id === targetId) return node;
  for (const c of node.children || []) {
    const f = findNodeInTree(c, targetId);
    if (f) return f;
  }
  return null;
}
