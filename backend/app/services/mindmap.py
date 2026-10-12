"""思维导图业务逻辑与伴学 Agent 服务：
支持 Markdown/JSON 大纲互转、LLM 纯净概念树生成、Agent 对话式增删改导图、节点深度剖析与学习画像因材施教。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mindmap import MindMap
from app.schemas.mindmap import (
    MindMapCreate,
    MindMapDetail,
    MindMapSummary,
    MindMapUpdate,
)
from app.services.llm import create_adapter_from_settings, extract_json
from app.services.profile import format_profile_for_prompt

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. 节点树辅助函数 (递归计算、查找、修改、去冒号格式化)
# ==============================================================================

def new_node_id() -> str:
    return f"node_{uuid.uuid4().hex[:10]}"


def clean_title(title: str) -> str:
    """清理节点标题：坚决杜绝 'xxx：xxxx' 或 'xxx: xxxx' 等键值对格式，提取精炼概念名。"""
    t = title.strip()
    # 移除常见的列表序号前缀如 1. 1.1 - 等
    t = re.sub(r"^[\d\.\-\*\+、\s]+", "", t).strip()
    # 移除中文冒号或英文冒号前缀如 "核心机制：页面置换" -> "页面置换"
    if "：" in t:
        parts = t.split("：", 1)
        # 如果冒号后内容具体且不为空，取后半段；如果前半段才是概念名，则保留更像概念的一段
        t = parts[1].strip() if len(parts[1].strip()) >= 2 else parts[0].strip()
    elif ":" in t and not t.startswith("http"):
        parts = t.split(":", 1)
        t = parts[1].strip() if len(parts[1].strip()) >= 2 else parts[0].strip()
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
    stmt = select(MindMap).order_by(desc(MindMap.updated_at))
    result = await db.execute(stmt)
    records = result.scalars().all()
    summaries: list[MindMapSummary] = []
    for m in records:
        summaries.append(
            MindMapSummary(
                id=m.id,
                title=m.title,
                topic=m.topic,
                node_count=count_nodes(m.root),
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
    return summaries


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

MINDMAP_GEN_SYSTEM_PROMPT = """你是一个专业的知识架构师与思维导图生成 Agent。
你的任务是根据用户给出的主题或材料，构建结构严密、层级分明的高质量思维导图树。

【必须严格遵守的命名与格式规范】：
1. 节点标题 (title) 必须是纯粹、精炼、直观的概念短语（如「虚拟内存管理」、「页表机制」、「TLB 快表」、「缺页异常处理」）。
2. 【绝对禁止】在节点标题中出现类似「xxx：xxxx」或「key: value」的冒号键值对格式！严禁使用类似「机制：基于页面的置换」或「原理：利用空间局部性」！直接命名为「页面置换」或「空间局部性原理」！
3. 分支层次丰富（至少 3 层，包含根节点、4~6 个一级大分支、每个一级分支 2~4 个二级子分支，重要概念继续深挖三级/四级分支）。
4. 每个节点可包含简短的 `summary`（10~25字以内的本质总结或记忆要点）。

{learner_profile}

请严格输出合法的 JSON 格式，不要包含任何额外的 Markdown 解释说明，根结构如下：
```json
{{
  "title": "主题名称",
  "root": {{
    "title": "中心主题",
    "summary": "全局核心定位",
    "children": [
      {{
        "title": "一级分支名称",
        "summary": "简短要点",
        "children": [
          {{
            "title": "二级子分支名称",
            "summary": "说明",
            "children": [
              {{
                "title": "三级深度分支",
                "summary": "说明"
              }}
            ]
          }}
        ]
      }}
    ]
  }}
}}
```"""


async def generate_mindmap_tree(
    prompt: str,
    depth: int,
    import_content: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """结合用户画像与深度要求，生成多层级纯净思维导图。"""
    adapter = create_adapter_from_settings(db, scene="generation")
    profile_snippet = await format_profile_for_prompt(db)
    system_prompt = MINDMAP_GEN_SYSTEM_PROMPT.format(learner_profile=profile_snippet)

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
    db: AsyncSession,
) -> AsyncIterator[dict[str, Any]]:
    """
    思维导图伴学 Agent：
    解析用户自然语言意图，调用工具对导图进行动态增删改查修剪，并流式反馈解释。
    """
    adapter = create_adapter_from_settings(db, scene="chat")
    profile_snippet = await format_profile_for_prompt(db)
    outline = _format_tree_outline_for_agent(mindmap.root)

    focus_hint = ""
    if selected_node_id:
        target = find_node(mindmap.root, selected_node_id)
        if target:
            focus_hint = f"\n当前用户在画布上选中的焦点节点为：[{selected_node_id}] {target.get('title')}"

    system_prompt = f"""你是一个智能思维导图伴学 Agent。
你正在协助学生协同构建和优化一张关于「{mindmap.title}」的思维导图。

当前思维导图的完整结构大纲如下（带节点 ID）：
{outline}
{focus_hint}

【你的职责与规则】：
1. 你可以调用工具直接对导图结构进行增删改（add_nodes, delete_nodes, update_node, expand_branch）。
2. 如果用户表达了修改意图（如“在xx下加几个子节点”、“把xx分支删了”、“重命名xx”、“再展开详细一点”），【必须优先调用相应工具】执行修改！
3. 所有节点标题必须精炼纯粹，【坚决杜绝】类似「xxx：xxxx」的冒号格式！
4. 在调用工具后，向学生用亲切、清晰、富有启发性的语言解释你做了哪些调整，以及为什么这样组织知识体系。
5. 结合学生的认知偏好与学习画像因材施教。

{profile_snippet}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    # 1. 尝试函数调用
    tree_changed = False
    try:
        raw_msg = await adapter.chat_raw(messages, tools=MINDMAP_AGENT_TOOLS)
        tool_calls = getattr(raw_msg, "tool_calls", None) or []
    except Exception as e:
        logger.warning(f"MindMap agent tool call error, falling back to direct chat: {e}")
        tool_calls = []

    if tool_calls:
        # 执行工具调用更新本地内存树
        for tc in tool_calls:
            fname = tc.function.name
            try:
                fargs = json.loads(tc.function.arguments)
            except Exception:
                fargs = {}

            yield {"type": "tool_call", "name": fname, "args": fargs}

            if fname == "add_nodes":
                pid = fargs.get("parent_id") or selected_node_id or mindmap.root.get("id")
                nodes = fargs.get("nodes") or []
                if add_nodes_to_parent(mindmap.root, pid, nodes):
                    tree_changed = True

            elif fname == "delete_nodes":
                nids = fargs.get("node_ids") or []
                for nid in nids:
                    if delete_node_from_tree(mindmap.root, nid):
                        tree_changed = True

            elif fname == "update_node":
                nid = fargs.get("node_id")
                target = find_node(mindmap.root, nid)
                if target:
                    if fargs.get("title"):
                        target["title"] = clean_title(fargs["title"])
                    if "summary" in fargs:
                        target["summary"] = fargs["summary"]
                    tree_changed = True

            elif fname == "expand_branch":
                nid = fargs.get("node_id") or selected_node_id
                sub_branches = fargs.get("sub_branches") or []
                if add_nodes_to_parent(mindmap.root, nid, sub_branches):
                    tree_changed = True

            yield {"type": "tool_result", "name": fname, "success": True}

        if tree_changed:
            mindmap.root = normalize_node(mindmap.root, mindmap.title)
            await db.commit()
            await db.refresh(mindmap)
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
        for tc in tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({"status": "success", "tree_updated": tree_changed}, ensure_ascii=False)
            })

    # 2. 流式返回 Agent 的伴学解释文本
    async for chunk in adapter.chat(messages, stream=True):
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
    adapter = create_adapter_from_settings(db, scene="generation")
    profile_snippet = await format_profile_for_prompt(db)

    prompt = f"""你是一个顶尖的知识导师。请针对思维导图中的具体概念节点，撰写一份结构清晰、深入浅出、极具启发性的深度剖析文档。

【节点信息】：
- 概念名称：{node.get('title')}
- 知识路径定位：{path_str}
- 简短摘要：{node.get('summary') or '（暂无）'}
{f'- 特别要求：{instruction.strip()}' if instruction.strip() else ''}

【生成规范要求】：
1. 使用清晰美观的 Markdown 格式输出。
2. 包含以下核心板块：
   - 📌 **本质定义**：用一两句一针见血的话阐明概念本质，避免套话。
   - 🔍 **核心原理与运作机制**：拆解其底层工作方式，配以直观逻辑链条或步骤。
   - 💡 **直观类比/现实对照**：根据学生画像，结合恰当的生活或工程比喻化抽象为具象。
   - ⚠️ **认知误区澄清**：点出初学者最容易混淆或理解错的 1~2 个关键点。
   - 🚀 **实战应用/关键代码或推导**（视具体学科给出简明示例）。
3. 严格遵循学习者画像，量体裁衣，因材施教。

{profile_snippet}"""

    messages = [
        {"role": "system", "content": "你是一个善于深入剖析概念本质的高级伴学导师。"},
        {"role": "user", "content": prompt},
    ]

    full_text = ""
    async for chunk in adapter.chat(messages, stream=True):
        if chunk:
            full_text += chunk
            yield {"type": "delta", "text": chunk}

    # 结果持久化入该节点
    node["detail"] = full_text.strip()
    mindmap.root = normalize_node(mindmap.root, mindmap.title)
    await db.commit()
    await db.refresh(mindmap)

    yield {"type": "done", "detail": node["detail"], "node_id": node_id}


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
    adapter = create_adapter_from_settings(db, scene="chat")
    profile_snippet = await format_profile_for_prompt(db)

    system_prompt = f"""你是学生在学习思维导图「{mindmap.title}」时的专属伴学助教。
当前学生聚焦在特定知识节点上进行提问与探讨。

【当前焦点节点】：
- 概念名称：{node.get('title')}
- 层级路径：{path_str}
- 节点要点：{node.get('summary') or '（无）'}
- 节点已有详尽解析：
{node.get('detail') or '（暂无详细解析）'}

【助教规则】：
1. 聚焦解答学生关于该节点的疑问，若涉及更深的技术细节或横向对比，可联系上级分支与相邻概念。
2. 保持启发性（Socratic式诱导思考），给出恰当的比喻与推导。
3. 契合学习者认知画像。

{profile_snippet}"""

    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-8:]:
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question.strip()})

    async for chunk in adapter.chat(messages, stream=True):
        if chunk:
            yield {"type": "delta", "text": chunk}

    yield {"type": "done"}
