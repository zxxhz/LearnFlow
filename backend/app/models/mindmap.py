"""思维导图模型：独立于课程体系的树状知识结构与伴学 Agent 资产。"""
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UserIdMixin, UUIDPk


class MindMap(Base, UUIDPk, UserIdMixin, Timestamps):
    __tablename__ = "mind_maps"

    title: Mapped[str] = mapped_column(String(255), default="新建思维导图", index=True)
    topic: Mapped[str] = mapped_column(String(255), default="")
    # 根节点及多级子分支递归树（MindMapNode 序列化结构）
    root: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 画布设置与视图偏好（布局模式、默认缩放等）
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
