"""思维导图业务逻辑与伴学 Agent 服务：
支持 Markdown/JSON 大纲互转、LLM 纯净概念树生成、Agent 对话式增删改导图、节点深度剖析与学习画像因材施教。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mindmap import MindMap
from app.schemas.mindmap import (
    MindMapCreate,
    MindMapDetail,
    MindMapSummary,
    MindMapUpdate,
)
from app.services.llm import create_adapter_from_settings, extract_json
from app.services.prompt import render_prompt
from app.services.profile import format_profile_for_prompt

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. 节点树辅助函数 (递归计算、查找、修改、去冒号格式化)
# ==============================================================================

def new_node_id() -> str:
    return f"node_{uuid.uuid4().hex[:10]}"


def clean_title(title: str) -> str:
    """清理节点标题：坚决杜绝 'xxx：xxxx' 或 'xxx: xxxx' 等键值对格式，提取精炼概念名。

    只剥除「列表序号」前缀（如 "1. " "1.1 " "1、" "1) " "- " "* "），
    不伤及 "0-1 背包" "2-3-4 树" "3D 渲染" "5G 通信" "8086 架构" "std::vector" 等合法术语。
    """
    t = title.strip()
    # 仅剥除带点号/顿号/括号的层级序号与列表符；裸数字+空格（如 "8086 架构"）不是序号
    t = re.sub(r"^(?:\d+(?:\.\d+)+\s*|\d+[.、)．]\s*|[-*+•]\s+)+", "", t)
    t = re.sub(r"^[.、\s]+", "", t).strip()
    # 中文冒号总是键值对分隔符："核心机制：页面置换" -> "页面置换"
    if "：" in t:
        parts = t.split("：", 1)
        t = parts[1].strip() if len(parts[1].strip()) >= 2 else parts[0].strip()
    else:
        # 英文冒号：跳过 C++ 命名空间（::）与 URL；单冒号且前段像引导语时取后段
        m = re.match(r"^([^:：]{2,14})\s*:\s+(.{2,})$", t)
        if m and "::" not in t and not t.startswith(("http", "https")):
            t = m.group(2).strip()
    return t or "未命名概念"


def count_nodes(node: dict[str, Any] | None) -> int:
    """递归计算思维导图节点总数。"""
    if not node or not isinstance(node, dict):
        return 0
    count = 1
    children = node.get("children") or []
    for c in children:
        count += count_nodes(c)
    return count


def normalize_node(node: dict[str, Any], default_title: str = "中心主题") -> dict[str, Any]:
    """递归标准化节点字典，确保 id、title、children、collapsed 字段完整规范。"""
    if not isinstance(node, dict):
        return {"id": new_node_id(), "title": default_title, "summary": "", "detail": "", "children": [], "collapsed": False}

    nid = str(node.get("id") or "").strip() or new_node_id()
    raw_title = str(node.get("title") or "").strip() or default_title
    title = clean_title(raw_title)
    summary = str(node.get("summary") or "").strip()
    detail = str(node.get("detail") or "").strip()
    collapsed = bool(node.get("collapsed", False))

    raw_children = node.get("children")
    children: list[dict[str, Any]] = []
    if isinstance(raw_children, list):
        for c in raw_children:
            if isinstance(c, dict):
                children.append(normalize_node(c, "分支主题"))

    return {
        "id": nid,
        "title": title,
        "summary": summary,
        "detail": detail,
        "children": children,
        "collapsed": collapsed,
    }


def find_node(root: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    """递归根据 ID 查找节点。"""
    if not root or not isinstance(root, dict):
        return None
    if root.get("id") == node_id:
        return root
    for c in root.get("children") or []:
        found = find_node(c, node_id)
        if found:
            return found
    return None


def get_node_path(root: dict[str, Any], target_id: str, path: list[str] | None = None) -> list[str] | None:
    """获取根节点到目标节点的面包屑路径列表。"""
    if path is None:
        path = []
    current_path = path + [root.get("title", "")]
    if root.get("id") == target_id:
        return current_path
    for c in root.get("children") or []:
        p = get_node_path(c, target_id, current_path)
        if p:
            return p
    return None


def delete_node_from_tree(root: dict[str, Any], target_id: str) -> bool:
    """从树中递归剔除指定 ID 的节点及其子分支（根节点不可删除）。"""
    if not root or root.get("id") == target_id:
        return False
    children = root.get("children") or []
    for i, c in enumerate(children):
        if c.get("id") == target_id:
            children.pop(i)
            return True
        if delete_node_from_tree(c, target_id):
            return True
    return False


def add_nodes_to_parent(root: dict[str, Any], parent_id: str, new_nodes: list[dict[str, Any]]) -> bool:
    """向指定父节点追加子节点列表。"""
    parent = find_node(root, parent_id)
    if not parent:
        return False
    if "children" not in parent or not isinstance(parent["children"], list):
        parent["children"] = []
    for n in new_nodes:
        normalized = normalize_node(n, "新分支")
        parent["children"].append(normalized)
    return True


def create_default_tree(title: str = "思维导图") -> dict[str, Any]:
    """生成一个结构精美的默认三层思维导图树。"""
    root_title = clean_title(title)
    return {
        "id": "node_root",
        "title": root_title,
        "summary": "核心知识全景概览",
        "detail": f"# {root_title}\n\n点击右上角「💡 AI Agent 深入生成/解析」即可结合学习画像生成本节点的深度阐述。",
        "collapsed": False,
        "children": [
            {
                "id": new_node_id(),
                "title": "核心概念与定义",
                "summary": "基础概念与核心基石",
                "detail": "",
                "collapsed": False,
                "children": [
                    {"id": new_node_id(), "title": "基本定义", "summary": "", "detail": "", "children": []},
                    {"id": new_node_id(), "title": "核心特征", "summary": "", "detail": "", "children": []},
                ],
            },
            {
                "id": new_node_id(),
                "title": "关键原理与机制",
                "summary": "底层运行机制与工作流",
                "detail": "",
                "collapsed": False,
                "children": [
                    {"id": new_node_id(), "title": "运行机制", "summary": "", "detail": "", "children": []},
                    {"id": new_node_id(), "title": "关键流程", "summary": "", "detail": "", "children": []},
                ],
            },
            {
                "id": new_node_id(),
                "title": "应用场景与实战",
                "summary": "典型业务落地与工程实践",
                "detail": "",
                "collapsed": False,
                "children": [
                    {"id": new_node_id(), "title": "典型场景", "summary": "", "detail": "", "children": []},
                    {"id": new_node_id(), "title": "最佳实践", "summary": "", "detail": "", "children": []},
                ],
            },
        ],
    }


# ==============================================================================
# 2. Markdown / JSON 大纲互转解析器
# ==============================================================================

def parse_markdown_to_tree(text: str, default_title: str = "") -> dict[str, Any]:
    """
    将 Markdown 标题层次（# ## ###）或列表缩进（- * +）解析为递归 MindMapNode 树。
    杜绝标题中的冒号键值对，保证节点概念精炼清晰。
    """
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return create_default_tree(default_title or "空白思维导图")

    # 构建层级项列表: [(level, title, summary)]
    items: list[tuple[int, str, str]] = []

    for line in lines:
        stripped = line.strip()
        # 跳过代码块标记与注释
        if stripped.startswith("```") or stripped.startswith("<!--"):
            continue

        level = 0
        title = ""
        summary = ""

        # 匹配 Markdown 标题：# 一级标题, ## 二级标题
        h_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h_match:
            level = len(h_match.group(1))
            raw_content = h_match.group(2).strip()
        else:
            # 匹配缩进列表: - 或 * 或 + 或 1.
            # 计算缩进空格数（2 空格或 1 个 tab 算一级）
            leading_spaces = len(line) - len(line.lstrip(" "))
            indent_level = max(1, leading_spaces // 2 + 1)

            list_match = re.match(r"^[\-\*\+\d\.]+\s+(.*)$", stripped)
            if list_match:
                level = indent_level + 1
                raw_content = list_match.group(1).strip()
            else:
                level = indent_level + 1
                raw_content = stripped

        # 尝试分离标题与补充描述（例如包含括号注释）
        if "（" in raw_content and raw_content.endswith("）"):
            p1, p2 = raw_content[:-1].split("（", 1)
            title = clean_title(p1)
            summary = p2.strip()
        elif "(" in raw_content and raw_content.endswith(")"):
            p1, p2 = raw_content[:-1].split("(", 1)
            title = clean_title(p1)
            summary = p2.strip()
        else:
            title = clean_title(raw_content)

        if title:
            items.append((level, title, summary))

    if not items:
        return create_default_tree(default_title or "导入导图")

    # 规范化：首个元素作为根节点
    root_title = items[0][1] or default_title or "导入思维导图"
    root: dict[str, Any] = {
        "id": "node_root",
        "title": root_title,
        "summary": items[0][2],
        "detail": "",
        "children": [],
        "collapsed": False,
    }

    # 栈结构组装多级树：[(level, node_dict)]
    stack: list[tuple[int, dict[str, Any]]] = [(items[0][0], root)]

    for level, title, summary in items[1:]:
        new_node = {
            "id": new_node_id(),
            "title": title,
            "summary": summary,
            "detail": "",
            "children": [],
            "collapsed": False,
        }
        # 找到比当前 level 小的最近祖先
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()

        parent_node = stack[-1][1]
        parent_node["children"].append(new_node)
        stack.append((level, new_node))

    return normalize_node(root)


def export_tree_to_markdown(node: dict[str, Any], level: int = 0) -> str:
    """将思维导图树递归导出为层次鲜明的 Markdown 文本。"""
    indent = "  " * level
    title = node.get("title", "")
    summary = node.get("summary", "")
    line = f"{indent}- {title}"
    if summary:
        line += f" ({summary})"
    lines = [line]
    for child in node.get("children") or []:
        lines.append(export_tree_to_markdown(child, level + 1))
    return "\n".join(lines)


# ==============================================================================
# 3. 数据库 CRUD 服务
# ==============================================================================

async def list_mindmaps(db: AsyncSession) -> list[MindMapSummary]:
    """列表页只需要元数据：node_count 用 SQLite json_tree 直接在库内统计，不把整棵树拉进 Python。

    json_tree 对每一行统计 key='title' 的节点数（normalize_node 保证每个节点恰有一个 title）。
    不支持 json_tree 的老 SQLite 回退为整树加载后内存计数。
    """
    sql = text(
        "SELECT id, title, topic, created_at, updated_at, "
        "(SELECT COUNT(*) FROM json_tree(mind_maps.root, '$') jt "
        " WHERE jt.key = 'title' AND jt.type = 'text') AS node_count "
        "FROM mind_maps ORDER BY updated_at DESC"
    )
    try:
        rows = (await db.execute(sql)).all()
    except Exception as e:
        # 老版本 SQLite 无 json1 扩展：记日志并回退为整树加载
        logger.warning("json_tree 快速计数不可用，回退整树加载: %s", e)
        # 老版本 SQLite 无 json_tree：回退为整树加载
        records = (await db.scalars(select(MindMap).order_by(desc(MindMap.updated_at)))).all()
        return [
            MindMapSummary(
                id=m.id,
                title=m.title,
                topic=m.topic,
                node_count=count_nodes(m.root),
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in records
        ]
    return [
        MindMapSummary(
            id=r.id,
            title=r.title,
            topic=r.topic,
            node_count=int(r.node_count or 0),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


async def create_mindmap(db: AsyncSession, data: MindMapCreate) -> MindMap:
    initial_root = (
        normalize_node(data.root if isinstance(data.root, dict) else data.root.model_dump(), data.title)
        if data.root
        else create_default_tree(data.title)
    )
    mm = MindMap(
        title=data.title or "新建思维导图",
        topic=data.topic,
        root=initial_root,
        settings=data.settings or {"layout": "lr", "zoom": 1},
    )
    db.add(mm)
    await db.commit()
    await db.refresh(mm)
    return mm


async def get_mindmap(db: AsyncSession, mindmap_id: str) -> MindMap | None:
    return await db.get(MindMap, mindmap_id)


async def update_mindmap(db: AsyncSession, mindmap_id: str, data: MindMapUpdate) -> MindMap | None:
    mm = await db.get(MindMap, mindmap_id)
    if not mm:
        return None
    if data.title is not None:
        mm.title = data.title.strip() or mm.title
    if data.topic is not None:
        mm.topic = data.topic.strip()
    if data.root is not None:
        mm.root = normalize_node(
            data.root if isinstance(data.root, dict) else data.root.model_dump(),
            mm.title
        )
    if data.settings is not None:
        mm.settings = {**(mm.settings or {}), **data.settings}
    await db.commit()
    await db.refresh(mm)
    return mm


async def delete_mindmap(db: AsyncSession, mindmap_id: str) -> bool:
    mm = await db.get(MindMap, mindmap_id)
    if not mm:
        return False
    await db.delete(mm)
    await db.commit()
    return True


# ==============================================================================
# 4. LLM Agent 一键生成思维导图树 (严格去冒号化，多分支深层展开，接入用户画像)
# ==============================================================================




async def generate_mindmap_tree(
    prompt: str,
    depth: int,
    import_content: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """结合用户画像与深度要求，生成多层级纯净思维导图。"""
    adapter = await create_adapter_from_settings(db, scene="generation")
    profile_snippet = await format_profile_for_prompt(db)
    system_prompt = render_prompt("mindmap_gen", LEARNER_PROFILE=profile_snippet)

    user_content = f"请围绕以下主题与材料，构建层级深度为 {depth} 层的思维导图：\n\n【核心主题】\n{prompt.strip()}"
    if import_content.strip():
        user_content += f"\n\n【参考材料与长文背景】\n{import_content.strip()[:4000]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    raw = await adapter.chat(messages, stream=False, json_mode=True)
    parsed = extract_json(raw)

    title = prompt.strip()[:50]
    if isinstance(parsed, dict):
        if parsed.get("title"):
            title = str(parsed["title"]).strip()
        root_data = parsed.get("root") if isinstance(parsed.get("root"), dict) else parsed
        root = normalize_node(root_data, title)
    else:
        root = create_default_tree(title)

    return {"title": title, "root": root}


# ==============================================================================
# 5. 导图伴学 Agent 对话服务 (自然语言指令驱动节点增删改)
# ==============================================================================

MINDMAP_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_nodes",
            "description": "向思维导图中指定父节点追加一个或多个子分支概念节点",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_id": {"type": "string", "description": "目标父节点的 ID"},
                    "nodes": {
                        "type": "array",
                        "description": "要添加的子节点列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "精炼概念标题（绝不包含冒号）"},
                                "summary": {"type": "string", "description": "概念简明要点说明"}
                            },
                            "required": ["title"]
                        }
                    }
                },
                "required": ["parent_id", "nodes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_nodes",
            "description": "从思维导图中删除指定的一个或多个分支节点及其全部子孙节点",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要删除的节点 ID 列表"
                    }
                },
                "required": ["node_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "重命名或更新某个节点的标题或要点说明",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "要修改的节点 ID"},
                    "title": {"type": "string", "description": "修改后的概念标题（绝不包含冒号）"},
                    "summary": {"type": "string", "description": "修改后的要点说明"}
                },
                "required": ["node_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "expand_branch",
            "description": "对某个节点进行深度多级扩展，补充丰富的下级子概念与实现细节",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "需要深度展开的节点 ID"},
                    "sub_branches": {
                        "type": "array",
                        "description": "多级子分支列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "概念名"},
                                "summary": {"type": "string", "description": "说明"},
                                "children": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                    "description": "更深层孙分支"
                                }
                            },
                            "required": ["title"]
                        }
                    }
                },
                "required": ["node_id", "sub_branches"]
            }
        }
    }
]


def _format_tree_outline_for_agent(node: dict[str, Any], level: int = 0) -> str:
    """为 Agent 提示词生成紧凑的树大纲带 ID 映射。"""
    indent = "  " * level
    nid = node.get("id", "")
    title = node.get("title", "")
    summary = f" - {node['summary']}" if node.get("summary") else ""
    lines = [f"{indent}* [{nid}] {title}{summary}"]
    for c in node.get("children") or []:
        lines.append(_format_tree_outline_for_agent(c, level + 1))
    return "\n".join(lines)


async def stream_mindmap_agent(
    mindmap: MindMap,
    user_message: str,
    selected_node_id: str | None,
    history: list[dict[str, str | None]] | None = None,
    *,
    db: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """
    思维导图伴学 Agent：
    支持多轮连续上下文对话，解析用户自然语言意图，调用工具对导图进行动态增删改查修剪，并流式反馈解释。
    """
    adapter = await create_adapter_from_settings(db, scene="chat")
    profile_snippet = await format_profile_for_prompt(db)
    outline = _format_tree_outline_for_agent(mindmap.root)

    focus_hint = ""
    if selected_node_id:
        target = find_node(mindmap.root, selected_node_id)
        if target:
            focus_hint = f"\n当前用户在画布上选中的焦点节点为：[{selected_node_id}] {target.get('title')}"

    system_prompt = render_prompt(
        "mindmap_agent",
        MAP_TITLE=mindmap.title,
        OUTLINE=outline,
        FOCUS_HINT=focus_hint,
        LEARNER_PROFILE=profile_snippet,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # 装配历史对话上下文：从最新往前最多保留 10 轮（20 条），且限制总字符预算，
    # 超出预算的更早轮次直接丢弃，防止超长对话撑爆模型上下文
    if history:
        budget = 8000
        picked: list[dict[str, str]] = []
        for h in reversed(history):
            if len(picked) >= 20 or budget <= 0:
                break
            role = h.get("role")
            content = h.get("content")
            if role not in ("user", "assistant") or not content:
                continue
            text = content.strip()
            if not text:
                continue
            if len(text) > budget:
                text = text[:budget]
            budget -= len(text)
            picked.append({"role": role, "content": text})
        picked.reverse()
        messages.extend(picked)

    messages.append({"role": "user", "content": user_message})

    # 1. 尝试函数调用
    tree_changed = False
    raw_msg = None
    try:
        raw_msg = await adapter.chat_raw(messages, tools=MINDMAP_AGENT_TOOLS)
        tool_calls = getattr(raw_msg, "tool_calls", None) or []
    except Exception as e:
        logger.warning(f"MindMap agent tool call error, falling back to direct chat: {e}")
        tool_calls = []

    if tool_calls:
        # 执行工具调用：先在请求树上演算效果（判定成功/失败并给前端预览），
        # 记录操作序列；持久化阶段用短会话重读最新树重放操作，避免旧树整列覆盖并发编辑
        def _apply_op(root: dict[str, Any], fname: str, fargs: dict[str, Any]) -> tuple[bool, str]:
            """在指定树上执行单个 Agent 工具操作，返回 (是否改变树, 失败说明)。"""
            if fname == "add_nodes":
                pid = fargs.get("parent_id") or selected_node_id or root.get("id")
                nodes = fargs.get("nodes") or []
                if not nodes:
                    return False, "nodes 列表为空"
                if add_nodes_to_parent(root, pid, nodes):
                    return True, ""
                return False, f"未找到父节点 {pid}"
            if fname == "delete_nodes":
                nids = fargs.get("node_ids") or []
                deleted = [nid for nid in nids if delete_node_from_tree(root, nid)]
                if deleted:
                    return True, ""
                return False, f"未找到待删节点：{nids}"
            if fname == "update_node":
                nid = fargs.get("node_id")
                target = find_node(root, nid)
                if target:
                    if fargs.get("title"):
                        target["title"] = clean_title(fargs["title"])
                    if "summary" in fargs:
                        target["summary"] = fargs["summary"]
                    return True, ""
                return False, f"未找到节点 {nid}"
            if fname == "expand_branch":
                nid = fargs.get("node_id") or selected_node_id
                sub_branches = fargs.get("sub_branches") or []
                if not sub_branches:
                    return False, "sub_branches 列表为空"
                if add_nodes_to_parent(root, nid, sub_branches):
                    return True, ""
                return False, f"未找到节点 {nid}"
            return False, f"未注册的工具：{fname}"

        ops: list[dict[str, Any]] = []
        tool_outcomes: list[dict] = []
        for tc in tool_calls:
            fname = tc.function.name
            try:
                fargs = json.loads(tc.function.arguments)
            except Exception:
                fargs = {}

            yield {"type": "tool_call", "name": fname, "args": fargs}
            op_ok, op_detail = _apply_op(mindmap.root, fname, fargs)
            if op_ok:
                tree_changed = True
                ops.append({"name": fname, "args": fargs})
            outcome: dict[str, Any] = {"name": fname, "success": op_ok}
            if op_detail:
                outcome["detail"] = op_detail
            tool_outcomes.append(outcome)
            yield {"type": "tool_result", **outcome}

        if tree_changed:
            from app.core.db import async_session_factory

            try:
                async with async_session_factory() as fresh_db:
                    fresh = await fresh_db.get(MindMap, mindmap.id)
                    if fresh is not None:
                        for op in ops:
                            _apply_op(fresh.root, op["name"], op["args"])
                        fresh.root = normalize_node(fresh.root, fresh.title)
                        await fresh_db.commit()
                        mindmap.root = fresh.root
            except Exception:
                logger.exception("Agent 树修改持久化失败: mindmap=%s", mindmap.id)
            yield {"type": "tree_update", "tree": mindmap.root}

        # 组织后续解释消息
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in tool_calls
            ]
        })
        for tc, outcome in zip(tool_calls, tool_outcomes):
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(outcome, ensure_ascii=False),
            })
    else:
        # 模型未调用工具且已生成完整回答文本时，直接分块流式下发，消除二次调用与额外延迟
        final_text = getattr(raw_msg, "content", None)
        if final_text:
            chunk_size = 12
            for i in range(0, len(final_text), chunk_size):
                yield {"type": "delta", "text": final_text[i:i + chunk_size]}
                if len(final_text) > chunk_size:
                    await asyncio.sleep(0.01)
            yield {"type": "done", "tree": None}
            return

    # 2. 流式返回 Agent 的伴学解释文本
    stream = await adapter.chat(messages, stream=True)
    async for chunk in stream:
        if chunk:
            yield {"type": "delta", "text": chunk}

    yield {"type": "done", "tree": mindmap.root if tree_changed else None}


# ==============================================================================
# 6. 节点深度剖析生成与节点专属问答 (接入画像)
# ==============================================================================

async def stream_node_detail(
    mindmap: MindMap,
    node_id: str,
    instruction: str,
    db: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """为特定节点结合其上下文路径与学习者画像，生成详尽深入的 Markdown 知识拆解。"""
    node = find_node(mindmap.root, node_id)
    if not node:
        yield {"type": "error", "detail": "节点不存在"}
        return

    path = get_node_path(mindmap.root, node_id) or [node.get("title", "")]
    path_str = " > ".join(path)
    adapter = await create_adapter_from_settings(db, scene="generation")
    profile_snippet = await format_profile_for_prompt(db)

    instruction_line = f"- 特别要求：{instruction.strip()}" if instruction.strip() else ""
    prompt = render_prompt(
        "mindmap_node_detail",
        NODE_TITLE=node.get("title", ""),
        NODE_PATH=path_str,
        NODE_SUMMARY=node.get("summary") or "（暂无）",
        EXTRA_INSTRUCTION=instruction_line,
        LEARNER_PROFILE=profile_snippet,
    )

    messages = [
        {"role": "system", "content": "你是一个善于深入剖析概念本质的高级伴学导师。"},
        {"role": "user", "content": prompt},
    ]

    full_text = ""
    stream = await adapter.chat(messages, stream=True)
    async for chunk in stream:
        if chunk:
            full_text += chunk
            yield {"type": "delta", "text": chunk}

    # 结果持久化：流式生成可能持续数十秒，期间画布编辑/Agent 指令可能已更新库中树。
    # 用全新短会话重新加载最新树，仅改写目标节点的 detail 字段，避免旧内存树整列覆盖造成丢更新。
    from app.core.db import async_session_factory

    persisted = False
    try:
        async with async_session_factory() as fresh_db:
            fresh = await fresh_db.get(MindMap, mindmap.id)
            if fresh is not None:
                target = find_node(fresh.root, node_id)
                if target is not None:
                    target["detail"] = full_text.strip()
                    fresh.root = normalize_node(fresh.root, fresh.title)
                    await fresh_db.commit()
                    persisted = True
    except Exception:
        logger.exception("节点详情持久化失败: mindmap=%s node=%s", mindmap.id, node_id)

    yield {"type": "done", "detail": full_text.strip(), "node_id": node_id, "persisted": persisted}


async def stream_node_qa(
    mindmap: MindMap,
    node_id: str,
    question: str,
    history: list[dict[str, str]],
    db: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """针对思维导图中的特定节点展开专注对话问答。"""
    node = find_node(mindmap.root, node_id)
    if not node:
        yield {"type": "error", "detail": "节点不存在"}
        return

    path = get_node_path(mindmap.root, node_id) or [node.get("title", "")]
    path_str = " > ".join(path)
    adapter = await create_adapter_from_settings(db, scene="chat")
    profile_snippet = await format_profile_for_prompt(db)

    system_prompt = render_prompt(
        "mindmap_node_qa",
        MAP_TITLE=mindmap.title,
        NODE_TITLE=node.get("title", ""),
        NODE_PATH=path_str,
        NODE_SUMMARY=node.get("summary") or "（无）",
        NODE_DETAIL=node.get("detail") or "（暂无详细解析）",
        LEARNER_PROFILE=profile_snippet,
    )

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-8:]:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question.strip()})

    stream = await adapter.chat(messages, stream=True)
    async for chunk in stream:
        if chunk:
            yield {"type": "delta", "text": chunk}

    yield {"type": "done"}


async def seed_sample_mindmap(db: AsyncSession) -> None:
    """初次启动播种示例思维导图（若库中没有任何导图且未播种过）。"""
    from app.core.config import settings

    flag_file = settings.data_dir / ".sample_mindmap_seeded"
    if flag_file.exists():
        return

    # 检查数据库是否已有导图
    stmt = select(MindMap).limit(1)
    res = await db.execute(stmt)
    if res.scalars().first():
        try:
            flag_file.touch(exist_ok=True)
        except OSError:
            pass
        return

    sample_tree = {
        "id": "node_root",
        "title": "计算机系统与现代软件架构",
        "summary": "从底层硬件底座到上层分布式软件工程的完整知识图谱",
        "detail": "# 计算机系统与现代软件架构全景\n\n本导图是 LearnFlow 预置的示例思维导图，涵盖计算机体系、操作系统、网络传输与软件架构核心基石。\n\n你可以：\n- 点击任意节点在右侧抽屉查看或生成详细知识剖析\n- 打开「🧠 伴学 Agent」下达自然语言指令增删改导图\n- 点击节点悬浮的「＋」或「🗑️」自由拓展定制",
        "collapsed": False,
        "children": [
            {
                "id": new_node_id(),
                "title": "计算机体系底座",
                "summary": "硬件与体系结构基石",
                "detail": "计算机体系结构关注硬件组件的组织和互连，构成了所有软件系统运行的物理底座。",
                "collapsed": False,
                "children": [
                    {
                        "id": new_node_id(),
                        "title": "CPU流水线与乱序执行",
                        "summary": "指令级并行与分支预测",
                        "detail": "### CPU 流水线\n现代处理器通过将指令执行拆分为取指、译码、执行、访存、写回等多级流水线，配合分支预测器与乱序执行引擎，大幅提升每时钟周期指令数（IPC）。",
                        "children": [],
                    },
                    {
                        "id": new_node_id(),
                        "title": "多级缓存体系与局部性",
                        "summary": "L1/L2/L3 与时间/空间局部性",
                        "detail": "### 内存层次体系\n利用时间局部性和空间局部性原理，现代 CPU 构筑了寄存器、L1、L2、L3 高速缓存与主存的层次结构，以缓解主存访问延迟的物理瓶颈。",
                        "children": [],
                    },
                    {
                        "id": new_node_id(),
                        "title": "虚拟内存与页表机制",
                        "summary": "地址翻译与TLB快表",
                        "detail": "### 虚拟内存\n通过 MMU（内存管理单元）将进程的虚拟地址映射至物理内存页，实现内存空间隔离、安全保护与惰性按需换页机制。",
                        "children": [],
                    },
                ],
            },
            {
                "id": new_node_id(),
                "title": "操作系统核心",
                "summary": "资源管理与抽象调度",
                "detail": "操作系统作为底层硬件与上层应用之间的软件中介，承担 CPU 调度、内存隔离与设备抽象三大支柱。",
                "collapsed": False,
                "children": [
                    {
                        "id": new_node_id(),
                        "title": "进程与线程并发模型",
                        "summary": "上下文切换与状态机",
                        "detail": "### 进程与线程\n- **进程**：资源分配与保护的独立基本单位。\n- **线程**：CPU 调度与指令执行的最小单位，共享所属进程的堆区与代码段，拥有独立的栈和寄存器上下文。",
                        "children": [],
                    },
                    {
                        "id": new_node_id(),
                        "title": "进程间通信机制",
                        "summary": "管道、共享内存与消息队列",
                        "detail": "### IPC 机制\n涵盖匿名管道、命名管道、UNIX域套接字、共享内存与信号量同步，其中共享内存拥有极高的吞吐性能但需要锁配合。",
                        "children": [],
                    },
                    {
                        "id": new_node_id(),
                        "title": "虚拟文件系统与PageCache",
                        "summary": "VFS与脏页回写",
                        "detail": "### VFS 与页缓存\nLinux 通过 VFS 为各种文件系统提供统一 API，结合内核 PageCache 缓存磁盘块，大幅减少机械磁盘或闪存的物理 I/O 次数。",
                        "children": [],
                    },
                ],
            },
            {
                "id": new_node_id(),
                "title": "网络协议与通信",
                "summary": "端到端可靠互联",
                "detail": "网络协议栈负责异构网络节点间的数据封装、路由寻址与端到端可靠性保证。",
                "collapsed": False,
                "children": [
                    {
                        "id": new_node_id(),
                        "title": "TCP可靠传输机制",
                        "summary": "三次握手、滑动窗口与拥塞控制",
                        "detail": "### TCP 核心机制\n基于序列号、确认应答、超时重传、滑动窗口流量控制以及慢启动/拥塞避免机制，提供面向连接的字节流可靠传输保障。",
                        "children": [],
                    },
                    {
                        "id": new_node_id(),
                        "title": "HTTP应用层协议演进",
                        "summary": "HTTP/1.1管道、HTTP/2多路复用与HTTP/3",
                        "detail": "### HTTP 协议演进\n- HTTP/1.1：长连接与文本报文\n- HTTP/2：二进制分帧与单一连接多路复用\n- HTTP/3：基于 UDP 的 QUIC 协议，从根本上解决 TCP 线头阻塞问题",
                        "children": [],
                    },
                ],
            },
            {
                "id": new_node_id(),
                "title": "现代分布式架构",
                "summary": "高可用与扩展性设计",
                "detail": "应对海量请求与海量数据的高并发架构设计原则与中间件技术栈。",
                "collapsed": False,
                "children": [
                    {
                        "id": new_node_id(),
                        "title": "分层缓存与一致性",
                        "summary": "本地缓存、Redis与双写一致策略",
                        "detail": "### 缓存架构\n使用分布式缓存抗住读流量，配合 Cache-Aside（旁路缓存）与延迟双删保证数据最终一致性。",
                        "children": [],
                    },
                    {
                        "id": new_node_id(),
                        "title": "异步解耦与消息队列",
                        "summary": "削峰填谷与发布订阅",
                        "detail": "### 消息队列\n通过 Kafka / RocketMQ 实现系统间强解耦、大促流量削峰填谷，以及跨服务事件驱动最终一致性事务。",
                        "children": [],
                    },
                ],
            },
        ],
    }

    sample_map = MindMap(
        title="计算机系统与现代软件架构",
        topic="计算机科学与软件工程",
        root=sample_tree,
        settings={"layout": "lr", "zoom": 1},
    )
    db.add(sample_map)
    await db.commit()
    try:
        flag_file.touch(exist_ok=True)
    except OSError:
        pass

