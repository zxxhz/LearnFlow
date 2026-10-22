"""思维导图 Pydantic 模式定义。"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class MindMapNode(BaseModel):
    """思维导图树节点（支持任意深度递归嵌套）。"""
    id: str = Field(description="节点唯一 ID")
    title: str = Field(description="精炼概念标题（绝不出现 key:value 冒号格式）")
    summary: str = Field(default="", description="简短概念说明或关键词")
    detail: str = Field(default="", description="该节点详尽 Markdown 知识剖析")
    children: list[MindMapNode] = Field(default_factory=list, description="子分支列表")
    collapsed: bool = Field(default=False, description="是否折叠子分支")


class MindMapCreate(BaseModel):
    title: str = Field(default="新建思维导图", description="思维导图标题")
    topic: str = Field(default="", description="导图核心领域或主题")
    root: MindMapNode | dict[str, Any] | None = Field(default=None, description="初始根节点")
    settings: dict[str, Any] = Field(default_factory=dict, description="画布视图配置")


class MindMapUpdate(BaseModel):
    title: str | None = None
    topic: str | None = None
    root: MindMapNode | dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class MindMapSummary(BaseModel):
    id: str
    title: str
    topic: str
    node_count: int
    created_at: str
    updated_at: str


class MindMapDetail(BaseModel):
    id: str
    title: str
    topic: str
    root: dict[str, Any]
    settings: dict[str, Any]
    created_at: str
    updated_at: str


class MindMapGenerateRequest(BaseModel):
    prompt: str = Field(description="主题或生成提示，如「计算机网络传输层与TCP协议」")
    depth: int = Field(default=3, ge=2, le=5, description="思维导图层级深度")
    import_content: str = Field(default="", description="可选参考材料或粘贴的文章长文本")


class MindMapImportRequest(BaseModel):
    title: str = Field(default="", description="导图标题（留空则从首行或根节点自动提取）")
    content: str = Field(description="Markdown 大纲文本或 JSON 字符串")
    format: str = Field(default="auto", description="输入格式：auto / markdown / json")


class MindMapAgentChatRequest(BaseModel):
    message: str = Field(description="用户对话指令，如「在进程调度分支下补充时间片轮转算法」")
    selected_node_id: str | None = Field(default=None, description="当前用户选中的焦点节点 ID")
    history: list[dict[str, str]] = Field(default_factory=list, description="多轮对话历史上下文")


class MindMapNodeDetailRequest(BaseModel):
    instruction: str = Field(default="", description="可选针对此节点生成的特殊要求")


class MindMapNodeQARequest(BaseModel):
    question: str = Field(description="用户关于该节点的追问")
    history: list[dict[str, str]] = Field(default_factory=list, description="历史对话上下文")
