// 思维导图核心画布工作台：原生 React + SVG 贝塞尔曲线层级树引擎、节点拖拽缩放视口、增删改查交互与伴学 Agent
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { MindMapDetail, MindMapNode } from "../../lib/types";
import { Button, Modal, Spinner, Textarea } from "../../components/ui";
import FontSizeControl from "../../components/FontSizeControl";
import { useFontSize } from "../../lib/fontSize";
import NodeDetailDrawer from "./NodeDetailDrawer";
import MindMapAgentPanel from "./MindMapAgentPanel";

// 布局常量
const NODE_WIDTH = 195;
const NODE_HEIGHT = 46;
const HORIZONTAL_GAP = 85;
const VERTICAL_GAP = 20;

// 一级分支调色板（循环用于区分不同主干领域）
const BRANCH_COLORS = [
  { border: "border-blue-500", bg: "bg-blue-50/70 dark:bg-blue-950/40", text: "text-blue-700 dark:text-blue-300", line: "#3b82f6" },
  { border: "border-emerald-500", bg: "bg-emerald-50/70 dark:bg-emerald-950/40", text: "text-emerald-700 dark:text-emerald-300", line: "#10b981" },
  { border: "border-amber-500", bg: "bg-amber-50/70 dark:bg-amber-950/40", text: "text-amber-700 dark:text-amber-300", line: "#f59e0b" },
  { border: "border-purple-500", bg: "bg-purple-50/70 dark:bg-purple-950/40", text: "text-purple-700 dark:text-purple-300", line: "#8b5cf6" },
  { border: "border-rose-500", bg: "bg-rose-50/70 dark:bg-rose-950/40", text: "text-rose-700 dark:text-rose-300", line: "#f43f5e" },
  { border: "border-cyan-500", bg: "bg-cyan-50/70 dark:bg-cyan-950/40", text: "text-cyan-700 dark:text-cyan-300", line: "#06b6d4" },
  { border: "border-indigo-500", bg: "bg-indigo-50/70 dark:bg-indigo-950/40", text: "text-indigo-700 dark:text-indigo-300", line: "#6366f1" },
];

interface PositionedNode {
  node: MindMapNode;
  x: number;
  y: number;
  width: number;
  height: number;
  depth: number;
  branchIndex: number;
  hasChildren: boolean;
  collapsed: boolean;
}

interface TreeConnection {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color?: string;
}

function countAllSubNodes(node: MindMapNode): number {
  let count = 0;
  for (const c of node.children || []) {
    count += 1 + countAllSubNodes(c);
  }
  return count;
}

export default function MindMapCanvasPage() {
  const { mapId } = useParams<{ mapId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { fontSize, setFontSize } = useFontSize("course");

  const [pan, setPan] = useState({ x: 80, y: 160 });
  const [zoom, setZoom] = useState(1);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [isClosingDetail, setIsClosingDetail] = useState(false);
  const [agentPanelOpen, setAgentPanelOpen] = useState(false);
  const [isClosingAgent, setIsClosingAgent] = useState(false);

  // 本地树状态缓存，支持秒级即时操作与防抖保存
  const [treeData, setTreeData] = useState<MindMapNode | null>(null);
  const [saveStatus, setSaveStatus] = useState<"saved" | "saving" | "unsaved">("saved");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveStatusRef = useRef<"saved" | "saving" | "unsaved">("saved");

  // 快捷重命名或新增节点模态框
  const [editingNode, setEditingNode] = useState<{ id: string; title: string } | null>(null);
  const [addChildTargetId, setAddChildTargetId] = useState<string | null>(null);
  const [newChildTitle, setNewChildTitle] = useState("");

  const containerRef = useRef<HTMLDivElement>(null);

  const { data: mapDetail, isLoading, error } = useQuery({
    queryKey: ["mindmap", mapId],
    queryFn: () => api.mindmaps.get(mapId!),
    enabled: !!mapId,
  });

  useEffect(() => {
    if (mapDetail?.root) {
      setTreeData((prev) => {
        // 本地存在未保存的编辑时不覆盖，防止保存回包/缓存刷新打断正在输入的内容
        if (prev && saveStatusRef.current !== "saved") return prev;
        return mapDetail.root;
      });
    }
  }, [mapDetail?.id, mapDetail?.updated_at]);

  // 防抖异步自动保存树数据
  const saveTreeDebounced = useCallback(
    (newTree: MindMapNode) => {
      setSaveStatus("saving");
      saveStatusRef.current = "saving";
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        if (!mapId) return;
        try {
          await api.mindmaps.update(mapId, { root: newTree });
          setSaveStatus("saved");
          saveStatusRef.current = "saved";
          queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
          // 同步详情缓存，防止 15s staleTime 内重进页面读到旧树覆盖刚保存的内容
          queryClient.setQueryData<MindMapDetail>(["mindmap", mapId], (old) =>
            old ? { ...old, root: newTree } : old
          );
        } catch (e) {
          setSaveStatus("unsaved");
          saveStatusRef.current = "unsaved";
        }
      }, 800);
    },
    [mapId, queryClient]
  );

  // 卸载时若有待保存的防抖任务立即落库，防止快速返回列表页丢失最后一次编辑
  const treeDataRef = useRef<MindMapNode | null>(null);
  useEffect(() => {
    treeDataRef.current = treeData;
  }, [treeData]);
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
        if (mapId && treeDataRef.current && saveStatusRef.current !== "saved") {
          api.mindmaps.update(mapId, { root: treeDataRef.current }).catch(() => {});
        }
      }
    };
  }, [mapId]);

  // 节点更新调度
  const updateTreeNode = useCallback(
    (nodeId: string, updates: Partial<MindMapNode>) => {
      setTreeData((prev) => {
        if (!prev) return prev;
        const updateRecursive = (cur: MindMapNode): MindMapNode => {
          if (cur.id === nodeId) {
            return { ...cur, ...updates };
          }
          if (cur.children) {
            return { ...cur, children: cur.children.map(updateRecursive) };
          }
          return cur;
        };
        const next = updateRecursive(prev);
        saveTreeDebounced(next);
        return next;
      });
    },
    [saveTreeDebounced]
  );

  // 新增子节点
  const handleAddChildNode = useCallback(
    (parentId: string, childTitle: string) => {
      const cleanTitle = childTitle.trim() || "新概念分支";
      setTreeData((prev) => {
        if (!prev) return prev;
        const addRecursive = (cur: MindMapNode): MindMapNode => {
          if (cur.id === parentId) {
            const newNode: MindMapNode = {
              id: `node_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
              title: cleanTitle,
              summary: "",
              detail: "",
              children: [],
              collapsed: false,
            };
            return {
              ...cur,
              collapsed: false,
              children: [...(cur.children || []), newNode],
            };
          }
          if (cur.children) {
            return { ...cur, children: cur.children.map(addRecursive) };
          }
          return cur;
        };
        const next = addRecursive(prev);
        saveTreeDebounced(next);
        return next;
      });
      setAddChildTargetId(null);
      setNewChildTitle("");
    },
    [saveTreeDebounced]
  );

  // 删除节点及其子分支
  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      if (!treeData || treeData.id === nodeId) {
        alert("根节点不可删除");
        return;
      }
      if (!confirm("确定删除该分支及其下属的所有子概念？")) return;

      setTreeData((prev) => {
        if (!prev) return prev;
        const deleteRecursive = (cur: MindMapNode): MindMapNode => {
          if (!cur.children) return cur;
          return {
            ...cur,
            children: cur.children
              .filter((c) => c.id !== nodeId)
              .map(deleteRecursive),
          };
        };
        const next = deleteRecursive(prev);
        saveTreeDebounced(next);
        return next;
      });

      if (selectedNodeId === nodeId) {
        setSelectedNodeId(null);
        setDetailDrawerOpen(false);
      }
    },
    [treeData, selectedNodeId, saveTreeDebounced]
  );

  // 折叠 / 展开分支
  const handleToggleCollapse = useCallback(
    (e: React.MouseEvent, nodeId: string) => {
      e.stopPropagation();
      setTreeData((prev) => {
        if (!prev) return prev;
        const toggleRecursive = (cur: MindMapNode): MindMapNode => {
          if (cur.id === nodeId) {
            return { ...cur, collapsed: !cur.collapsed };
          }
          if (cur.children) {
            return { ...cur, children: cur.children.map(toggleRecursive) };
          }
          return cur;
        };
        const next = toggleRecursive(prev);
        saveTreeDebounced(next);
        return next;
      });
    },
    [saveTreeDebounced]
  );

  // 节点详情抽屉与 Agent 面板的平滑开启/关闭控制
  const closeTimerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const clearCloseTimer = (key: string) => {
    const t = closeTimerRef.current[key];
    if (t) {
      clearTimeout(t);
      delete closeTimerRef.current[key];
    }
  };
  useEffect(() => {
    const timers = closeTimerRef.current;
    return () => {
      for (const key of Object.keys(timers)) clearTimeout(timers[key]);
    };
  }, []);

  const closeDetailDrawer = useCallback(() => {
    setIsClosingDetail(true);
    clearCloseTimer("detail");
    closeTimerRef.current.detail = setTimeout(() => {
      setDetailDrawerOpen(false);
      setIsClosingDetail(false);
    }, 300);
  }, []);

  const openDetailDrawer = useCallback(
    (nodeId: string) => {
      if (agentPanelOpen && !isClosingAgent) {
        clearCloseTimer("agent");
        setIsClosingAgent(true);
        closeTimerRef.current.agent = setTimeout(() => {
          setAgentPanelOpen(false);
          setIsClosingAgent(false);
        }, 300);
      }
      setSelectedNodeId(nodeId);
      clearCloseTimer("detail");
      setIsClosingDetail(false);
      setDetailDrawerOpen(true);
    },
    [agentPanelOpen, isClosingAgent]
  );

  const openAgent = useCallback(() => {
    if (detailDrawerOpen && !isClosingDetail) {
      clearCloseTimer("detail");
      setIsClosingDetail(true);
      closeTimerRef.current.detail = setTimeout(() => {
        setDetailDrawerOpen(false);
        setIsClosingDetail(false);
      }, 300);
    }
    clearCloseTimer("agent");
    setIsClosingAgent(false);
    setAgentPanelOpen(true);
  }, [detailDrawerOpen, isClosingDetail]);

  const closeAgent = useCallback(() => {
    setIsClosingAgent(true);
    clearCloseTimer("agent");
    closeTimerRef.current.agent = setTimeout(() => {
      setAgentPanelOpen(false);
      setIsClosingAgent(false);
    }, 300);
  }, []);

  // Esc 键优先退出抽屉或 Agent 面板
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (agentPanelOpen && !isClosingAgent) {
          closeAgent();
        } else if (detailDrawerOpen && !isClosingDetail) {
          closeDetailDrawer();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [agentPanelOpen, isClosingAgent, detailDrawerOpen, isClosingDetail, closeAgent, closeDetailDrawer]);

  // 当右侧 Agent 面板或详情抽屉展开时，思维导图整体同步平移向左偏移以留出右侧空间
  const sideShift =
    agentPanelOpen && !isClosingAgent
      ? -190
      : detailDrawerOpen && !isClosingDetail
      ? -210
      : 0;

  // ============================================================================
  // 原生自左向右 (Left-to-Right) 层级树布局计算
  // ============================================================================
  const { positionedNodes, connections, bounds } = useMemo(() => {
    if (!treeData) return { positionedNodes: [], connections: [], bounds: { minX: 0, maxX: 0, minY: 0, maxY: 0 } };

    // 1. 递归计算各子树占用总高度
    function computeSubtreeHeight(node: MindMapNode): number {
      if (!node.children || node.children.length === 0 || node.collapsed) {
        return NODE_HEIGHT;
      }
      let total = 0;
      for (let i = 0; i < node.children.length; i++) {
        total += computeSubtreeHeight(node.children[i]);
      }
      total += (node.children.length - 1) * VERTICAL_GAP;
      return Math.max(NODE_HEIGHT, total);
    }

    const nodesList: PositionedNode[] = [];
    const connsList: TreeConnection[] = [];

    // 2. 递归赋予坐标
    function placeSubtree(
      node: MindMapNode,
      x: number,
      startY: number,
      depth: number,
      branchIndex: number
    ) {
      const subtreeH = computeSubtreeHeight(node);
      const y = startY + (subtreeH - NODE_HEIGHT) / 2;

      const pNode: PositionedNode = {
        node,
        x,
        y,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        depth,
        branchIndex,
        hasChildren: !!(node.children && node.children.length > 0),
        collapsed: !!node.collapsed,
      };
      nodesList.push(pNode);

      // 若未折叠且有子节点，递归放置各子节点并连接贝塞尔曲线
      if (node.children && node.children.length > 0 && !node.collapsed) {
        let childY = startY;
        const childX = x + NODE_WIDTH + HORIZONTAL_GAP;

        for (let i = 0; i < node.children.length; i++) {
          const child = node.children[i];
          const childH = computeSubtreeHeight(child);
          const childBranchIdx = depth === 0 ? i % BRANCH_COLORS.length : branchIndex;

          const childMidY = childY + (childH - NODE_HEIGHT) / 2 + NODE_HEIGHT / 2;
          const parentMidY = y + NODE_HEIGHT / 2;

          connsList.push({
            id: `${node.id}-${child.id}`,
            x1: x + NODE_WIDTH,
            y1: parentMidY,
            x2: childX,
            y2: childMidY,
            color: BRANCH_COLORS[childBranchIdx]?.line || "#94a3b8",
          });

          placeSubtree(child, childX, childY, depth + 1, childBranchIdx);
          childY += childH + VERTICAL_GAP;
        }
      }
    }

    placeSubtree(treeData, 0, 0, 0, 0);

    let minX = 0, maxX = 0, minY = 0, maxY = 0;
    for (const n of nodesList) {
      if (n.x < minX) minX = n.x;
      if (n.x + n.width > maxX) maxX = n.x + n.width;
      if (n.y < minY) minY = n.y;
      if (n.y + n.height > maxY) maxY = n.y + n.height;
    }

    return { positionedNodes: nodesList, connections: connsList, bounds: { minX, maxX, minY, maxY } };
  }, [treeData]);

  // 视口平移与缩放手势
  const handleMouseDown = (e: React.MouseEvent) => {
    // 仅在画布背景点击时触发视口拖动
    if ((e.target as HTMLElement).closest(".mindmap-node-card")) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPan({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y,
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  // 触屏手势状态（单指移动与双指缩放）
  const touchPinchRef = useRef<{
    isPinching: boolean;
    initialDist: number;
    initialZoom: number;
    initialPan: { x: number; y: number };
    midX: number;
    midY: number;
  } | null>(null);

  const handleTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      if ((e.target as HTMLElement).closest(".mindmap-node-card")) return;
      const t = e.touches[0];
      setIsDragging(true);
      setDragStart({ x: t.clientX - pan.x, y: t.clientY - pan.y });
      touchPinchRef.current = null;
    } else if (e.touches.length === 2) {
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const rect = containerRef.current?.getBoundingClientRect();
      const midX = (t1.clientX + t2.clientX) / 2 - (rect?.left || 0);
      const midY = (t1.clientY + t2.clientY) / 2 - (rect?.top || 0);

      setIsDragging(true);
      touchPinchRef.current = {
        isPinching: true,
        initialDist: dist,
        initialZoom: zoom,
        initialPan: { ...pan },
        midX,
        midY,
      };
    }
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length === 1 && !touchPinchRef.current?.isPinching && isDragging) {
      const t = e.touches[0];
      setPan({
        x: t.clientX - dragStart.x,
        y: t.clientY - dragStart.y,
      });
    } else if (e.touches.length === 2 && touchPinchRef.current?.isPinching) {
      const t1 = e.touches[0];
      const t2 = e.touches[1];
      const dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
      const { initialDist, initialZoom, initialPan, midX, midY } = touchPinchRef.current;
      if (initialDist > 0) {
        const factor = dist / initialDist;
        const newZoom = Math.min(2.5, Math.max(0.3, initialZoom * factor));

        const currentX = initialPan.x + sideShift;
        const newCurrentX = midX - (midX - currentX) * (newZoom / initialZoom);
        const newY = midY - (midY - initialPan.y) * (newZoom / initialZoom);

        setZoom(newZoom);
        setPan({
          x: newCurrentX - sideShift,
          y: newY,
        });
      }
    }
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (e.touches.length === 0) {
      setIsDragging(false);
      touchPinchRef.current = null;
    } else if (e.touches.length === 1) {
      const t = e.touches[0];
      touchPinchRef.current = null;
      setDragStart({ x: t.clientX - pan.x, y: t.clientY - pan.y });
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
    const newZoom = Math.min(2.5, Math.max(0.3, zoom * zoomFactor));

    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      // 以鼠标光标为锚点平滑缩放（包含当前侧边同步偏移）
      const currentX = pan.x + sideShift;
      const newCurrentX = mouseX - (mouseX - currentX) * (newZoom / zoom);
      setPan({
        x: newCurrentX - sideShift,
        y: mouseY - (mouseY - pan.y) * (newZoom / zoom),
      });
      setZoom(newZoom);
    }
  };

  // 视口控制
  const handleZoomIn = () => setZoom((z) => Math.min(2.5, z * 1.15));
  const handleZoomOut = () => setZoom((z) => Math.max(0.3, z * 0.85));
  const handleResetZoom = () => {
    setZoom(1);
    setPan({ x: 80, y: 160 });
  };
  const handleFitScreen = () => {
    if (!containerRef.current || positionedNodes.length === 0) return;
    const cw = containerRef.current.clientWidth - 100;
    const ch = containerRef.current.clientHeight - 100;
    const treeW = bounds.maxX - bounds.minX || 500;
    const treeH = bounds.maxY - bounds.minY || 400;

    const scale = Math.min(1.5, Math.max(0.4, Math.min(cw / treeW, ch / treeH)));
    setZoom(scale);
    setPan({
      x: 60 - bounds.minX * scale,
      y: (ch - treeH * scale) / 2 + 50 - bounds.minY * scale,
    });
  };

  const selectedNode = useMemo(() => {
    if (!treeData || !selectedNodeId) return null;
    return positionedNodes.find((p) => p.node.id === selectedNodeId)?.node || null;
  }, [treeData, selectedNodeId, positionedNodes]);

  if (isLoading) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-gray-50 dark:bg-gray-900">
        <Spinner className="h-8 w-8 text-brand-600" />
      </div>
    );
  }

  if (error || !mapDetail || !treeData) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-gray-50 dark:bg-gray-900 p-8 text-center">
        <p className="text-sm text-red-600 dark:text-red-400">导图不存在或加载失败</p>
        <Link to="/mindmap" className="text-xs text-brand-600 underline">
          返回思维导图列表
        </Link>
      </div>
    );
  }

  return (
    <div className="relative flex h-full w-full select-none overflow-hidden bg-gray-50/60 dark:bg-gray-950">
      {/* 画布主工作区：当右侧 Agent 面板或详情抽屉滑出时平滑向左避让，关闭时丝滑复原 */}
      <div
        className={`relative flex-1 h-full min-w-0 overflow-hidden flex flex-col transition-all duration-300 ease-out ${
          agentPanelOpen && !isClosingAgent
            ? "mr-0 md:mr-[420px]"
            : detailDrawerOpen && !isClosingDetail
            ? "mr-0 md:mr-[500px]"
            : "mr-0"
        }`}
      >
        {/* 顶部悬浮控制条 */}
        <header className="z-20 flex items-center justify-between border-b border-gray-200/80 dark:border-gray-800 bg-white/90 dark:bg-gray-900/90 px-4 py-2.5 backdrop-blur shadow-2xs shrink-0">
          <div className="flex items-center gap-3">
            <Link
              to="/mindmap"
              className="flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-brand-600 dark:text-gray-400 dark:hover:text-brand-400 transition"
              title="返回导图列表"
            >
              <span>←</span>
              <span>导图列表</span>
            </Link>
            <span className="text-gray-300 dark:text-gray-700">|</span>
            <div className="flex items-center gap-2">
              <span className="text-base">🧠</span>
              <h1 className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate max-w-xs sm:max-w-md">
                {treeData.title}
              </h1>
              <span
                className={`text-[10px] rounded px-1.5 py-0.5 font-medium transition ${
                  saveStatus === "saving"
                    ? "bg-amber-50 text-amber-600 dark:bg-amber-950/40"
                    : saveStatus === "unsaved"
                    ? "bg-red-50 text-red-600 dark:bg-red-950/40"
                    : "bg-green-50 text-green-600 dark:bg-green-950/40"
                }`}
              >
                {saveStatus === "saving" ? "自动保存中…" : saveStatus === "unsaved" ? "未保存" : "已保存"}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <FontSizeControl
              value={fontSize}
              onChange={setFontSize}
              defaultValue={16}
              label="字号"
            />

            {/* 伴学 Agent 开关按钮 */}
            <button
              type="button"
              onClick={() => {
                if (agentPanelOpen && !isClosingAgent) {
                  closeAgent();
                } else {
                  openAgent();
                }
              }}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold shadow-2xs transition ${
                agentPanelOpen && !isClosingAgent
                  ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300"
                  : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:border-brand-400"
              }`}
            >
              <span>🧠</span>
              <span className="hidden sm:inline">伴学 Agent</span>
            </button>
          </div>
        </header>

        {/* 原生 SVG + HTML 视口容器 */}
        <div
          ref={containerRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onWheel={handleWheel}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          onTouchCancel={handleTouchEnd}
          className={`relative flex-1 h-full w-full overflow-hidden ${
            isDragging ? "cursor-grabbing" : "cursor-grab"
          }`}
          style={{
            touchAction: "none",
            backgroundImage: "radial-gradient(circle, rgba(148, 163, 184, 0.15) 1px, transparent 1px)",
            backgroundSize: "24px 24px",
          }}
        >
          {/* 画布缩放与平移变换根：拖拽时无延迟 instant，Agent 打开/收起与重置时 300ms 丝滑过渡 */}
          <div
            className={`absolute origin-top-left ${
              isDragging ? "transition-none" : "transition-transform duration-300 ease-out"
            }`}
            style={{
              transform: `translate(${pan.x + sideShift}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: "0 0",
            }}
          >
            {/* 1. SVG 贝塞尔曲线连接线层 */}
            <svg
              className="absolute left-0 top-0 overflow-visible pointer-events-none"
              style={{ width: "1px", height: "1px" }}
            >
              {connections.map((c) => {
                const dx = Math.max(35, (c.x2 - c.x1) * 0.5);
                const pathData = `M ${c.x1} ${c.y1} C ${c.x1 + dx} ${c.y1}, ${c.x2 - dx} ${c.y2}, ${c.x2} ${c.y2}`;
                return (
                  <path
                    key={c.id}
                    d={pathData}
                    fill="none"
                    stroke={c.color || "#94a3b8"}
                    strokeWidth="2"
                    strokeOpacity="0.75"
                    strokeLinecap="round"
                    className="transition-colors duration-200"
                  />
                );
              })}
            </svg>

            {/* 2. HTML 交互式节点卡片层 */}
            {positionedNodes.map((p) => {
              const isRoot = p.depth === 0;
              const isBranch = p.depth === 1;
              const isSelected = selectedNodeId === p.node.id;
              const branchStyle = BRANCH_COLORS[p.branchIndex] || BRANCH_COLORS[0];
              const totalChildren = countAllSubNodes(p.node);

              return (
                <div
                  key={p.node.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    openDetailDrawer(p.node.id);
                  }}
                  className={`mindmap-node-card group absolute flex items-center justify-between rounded-xl transition-all select-none cursor-pointer ${
                    isRoot
                      ? "bg-gradient-to-r from-brand-600 to-indigo-600 text-white font-bold shadow-md px-4 py-2.5"
                      : isBranch
                      ? `border-2 ${branchStyle.border} ${branchStyle.bg} ${branchStyle.text} font-semibold shadow-xs hover:shadow-md px-3.5 py-2`
                      : "border border-gray-200 dark:border-gray-700/80 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 shadow-2xs hover:border-brand-400 hover:shadow-xs px-3 py-1.5"
                  } ${
                    isSelected
                      ? "ring-2 ring-brand-500 ring-offset-2 dark:ring-offset-gray-900 scale-102 z-10"
                      : "z-1"
                  }`}
                  style={{
                    left: `${p.x}px`,
                    top: `${p.y}px`,
                    width: `${p.width}px`,
                    height: `${p.height}px`,
                  }}
                >
                  {/* 节点标题 */}
                  <div className="flex-1 min-w-0 pr-1.5">
                    <span
                      className={`block truncate text-xs leading-snug ${
                        isRoot ? "text-sm text-white" : ""
                      }`}
                      title={p.node.title}
                    >
                      {p.node.title}
                    </span>
                    {p.node.summary && !isRoot && (
                      <span className="block truncate text-[10px] text-gray-400 dark:text-gray-500">
                        {p.node.summary}
                      </span>
                    )}
                  </div>

                  {/* 右侧折叠按钮（含子节点时） */}
                  {p.hasChildren && (
                    <button
                      type="button"
                      onClick={(e) => handleToggleCollapse(e, p.node.id)}
                      className={`flex items-center justify-center rounded-full text-[10px] font-bold h-4.5 px-1.5 transition-transform shrink-0 ${
                        p.collapsed
                          ? "bg-brand-500 text-white hover:bg-brand-600 scale-105"
                          : isRoot
                          ? "bg-white/20 text-white hover:bg-white/30"
                          : "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"
                      }`}
                      title={p.collapsed ? `展开子分支（包含 ${totalChildren} 个子概念）` : "折叠子分支"}
                    >
                      {p.collapsed ? `+${p.node.children?.length}` : "−"}
                    </button>
                  )}

                  {/* 鼠标悬浮快捷工具栏 */}
                  <div className="absolute -top-7 right-0 hidden group-hover:flex items-center gap-1 rounded-md bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-0.5 shadow-md z-30">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setAddChildTargetId(p.node.id);
                        setNewChildTitle("");
                      }}
                      className="p-1 rounded text-xs text-gray-500 hover:text-brand-600 hover:bg-gray-100 dark:hover:bg-gray-700"
                      title="添加子分支"
                    >
                      ＋
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingNode({ id: p.node.id, title: p.node.title });
                      }}
                      className="p-1 rounded text-xs text-gray-500 hover:text-brand-600 hover:bg-gray-100 dark:hover:bg-gray-700"
                      title="修改名称"
                    >
                      ✏️
                    </button>
                    {!isRoot && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteNode(p.node.id);
                        }}
                        className="p-1 rounded text-xs text-gray-500 hover:text-red-600 hover:bg-gray-100 dark:hover:bg-gray-700"
                        title="删除该分支"
                      >
                        🗑️
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 底部浮动视口控制器 */}
        <div className="absolute bottom-5 left-5 z-20 flex items-center gap-1.5 rounded-xl border border-gray-200 dark:border-gray-800 bg-white/90 dark:bg-gray-900/90 px-3 py-1.5 backdrop-blur shadow-md text-xs text-gray-600 dark:text-gray-300">
          <button
            type="button"
            onClick={handleZoomOut}
            className="p-1 hover:text-brand-600"
            title="缩小"
          >
            －
          </button>
          <span className="font-mono text-[11px] w-10 text-center">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={handleZoomIn}
            className="p-1 hover:text-brand-600"
            title="放大"
          >
            ＋
          </button>
          <span className="text-gray-300 dark:text-gray-700">|</span>
          <button
            type="button"
            onClick={handleFitScreen}
            className="p-1 hover:text-brand-600"
            title="自适应全屏"
          >
            ⊡ 全屏居中
          </button>
          <button
            type="button"
            onClick={handleResetZoom}
            className="p-1 hover:text-brand-600"
            title="恢复 100%"
          >
            重置
          </button>
        </div>
      </div>

      {/* 右侧节点详情抽屉 */}
      {detailDrawerOpen && selectedNode && (
        <NodeDetailDrawer
          mindmapId={mapDetail.id}
          rootNode={treeData}
          nodeId={selectedNode.id}
          closing={isClosingDetail}
          onClose={closeDetailDrawer}
          onNodeUpdate={updateTreeNode}
        />
      )}

      {/* 右侧导图伴学 Agent 面板 */}
      {agentPanelOpen && (
        <MindMapAgentPanel
          mindmapId={mapDetail.id}
          selectedNode={selectedNode}
          closing={isClosingAgent}
          onTreeUpdate={(newTree) => {
            // Agent 服务端已落库，这里仅同步本地树与详情缓存，不再重复 PUT
            setTreeData(newTree);
            setSaveStatus("saved");
            saveStatusRef.current = "saved";
            if (saveTimerRef.current) {
              clearTimeout(saveTimerRef.current);
              saveTimerRef.current = null;
            }
            if (mapId) {
              queryClient.setQueryData<MindMapDetail>(["mindmap", mapId], (old) =>
                old ? { ...old, root: newTree } : old
              );
              queryClient.invalidateQueries({ queryKey: ["mindmaps"] });
            }
          }}
          onClose={closeAgent}
        />
      )}

      {/* 快捷添加子分支模态框 */}
      <Modal
        open={!!addChildTargetId}
        onClose={() => setAddChildTargetId(null)}
        title="➕ 添加子分支"
      >
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              新分支概念名称
            </label>
            <input
              type="text"
              autoFocus
              value={newChildTitle}
              onChange={(e) => setNewChildTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newChildTitle.trim() && addChildTargetId) {
                  handleAddChildNode(addChildTargetId, newChildTitle);
                }
              }}
              placeholder="例如：并发控制机制、核心生命周期…"
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setAddChildTargetId(null)}>
              取消
            </Button>
            <Button
              disabled={!newChildTitle.trim() || !addChildTargetId}
              onClick={() => addChildTargetId && handleAddChildNode(addChildTargetId, newChildTitle)}
            >
              确认添加
            </Button>
          </div>
        </div>
      </Modal>

      {/* 原地编辑节点标题模态框 */}
      <Modal
        open={!!editingNode}
        onClose={() => setEditingNode(null)}
        title="✏️ 修改概念名称"
      >
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300">
              概念名称
            </label>
            <input
              type="text"
              autoFocus
              value={editingNode?.title || ""}
              onChange={(e) => setEditingNode((prev) => prev ? { ...prev, title: e.target.value } : null)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && editingNode && editingNode.title.trim()) {
                  updateTreeNode(editingNode.id, { title: editingNode.title.trim() });
                  setEditingNode(null);
                }
              }}
              className="mt-1 w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2 text-xs text-gray-800 dark:text-gray-200 focus:outline-none focus:border-brand-500"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setEditingNode(null)}>
              取消
            </Button>
            <Button
              disabled={!editingNode || !editingNode.title.trim()}
              onClick={() => {
                if (editingNode && editingNode.title.trim()) {
                  updateTreeNode(editingNode.id, { title: editingNode.title.trim() });
                  setEditingNode(null);
                }
              }}
            >
              保存修改
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
