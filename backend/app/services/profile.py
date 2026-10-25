"""学习者画像与认知诊断服务：获取、更新、Prompt 注入与基于对话的异步认知提炼。"""
import asyncio
import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.models.base import utcnow_iso
from app.models.study import LearnerMisconception, LearnerProfile
from app.services.llm import create_adapter_from_settings, extract_json

logger = logging.getLogger(__name__)

# 单用户本地桌面端默认用户 ID
DEFAULT_PROFILE_ID = "local"


_background_tasks: set[asyncio.Task] = set()


async def get_or_create_profile(db: AsyncSession, profile_id: str = DEFAULT_PROFILE_ID) -> LearnerProfile:
    """获取学习者画像；不存在时用独立短会话落库默认实例。

    不能在调用方会话上写入默认画像：
    - commit 会把调用方未完事务一起提前提交；
    - flush 会挂起一条写事务，长流式请求期间（LLM 响应数十秒）锁死 SQLite 单写者，
      其他写入全部 database is locked 超时（实测踩中）。
    """
    profile = await db.get(LearnerProfile, profile_id)
    if profile is None:
        import asyncio as _asyncio

        from sqlalchemy.exc import IntegrityError

        try:
            async with async_session_factory() as s:
                existing = await s.get(LearnerProfile, profile_id)
                if existing is None:
                    s.add(
                        LearnerProfile(
                            id=profile_id,
                            background_summary="",
                            socratic_mode=True,
                            updated_at=utcnow_iso(),
                        )
                    )
                    await s.commit()
        except IntegrityError:
            # 并发首建竞态：另一会话已创建，忽略即可
            await _asyncio.sleep(0)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"默认画像创建失败（继续使用空画像）: {e}")
        # 行已由短会话落库，从调用方会话读取（读事务不持写锁）
        profile = await db.get(LearnerProfile, profile_id)
        if profile is None:
            # 极端兜底：库仍读不到时构造非持久化实例，功能不中断
            profile = LearnerProfile(
                id=profile_id,
                background_summary="",
                socratic_mode=True,
                updated_at=utcnow_iso(),
            )
    return profile


async def get_active_misconceptions(
    db: AsyncSession, limit: int = 10
) -> list[LearnerMisconception]:
    """获取用户当前未解决的易错认知/盲区记录。"""
    stmt = (
        select(LearnerMisconception)
        .where(LearnerMisconception.status == "active")
        .order_by(LearnerMisconception.created_at.desc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def format_profile_for_prompt(db: AsyncSession) -> str:
    """为大纲/正文/问答/助教 Prompt 格式化学习者认知上下文。

    若画像完全为空且无活跃盲区，返回空字符串；
    若包含信息，则组合成引导语。
    """
    profile = await get_or_create_profile(db)
    misconceptions = await get_active_misconceptions(db, limit=8)

    bg = (profile.background_summary or "").strip()
    has_misc = bool(misconceptions)

    if not bg and not has_misc:
        # 仅有启发模式配置时，给一个简明教学风格指导
        style_hint = "优先采用苏格拉底式启发提问，引导学生自主思考" if profile.socratic_mode else "直接、清晰、结构化给出解答"
        return f"\n## 教学风格偏好\n- 答疑与引导风格：{style_hint}\n"

    lines = ["\n## 学习者画像与认知背景（请结合该背景定制教学内容与深度）："]
    if bg:
        lines.append(f"- 背景特征与认知偏好：{bg}")
    style_hint = "优先采用苏格拉底式启发引导" if profile.socratic_mode else "直接清晰解答"
    lines.append(f"- 答疑偏好：{style_hint}")

    if misconceptions:
        misc_desc = "、".join([f"{m.topic}（{m.evidence or m.tag}）" for m in misconceptions if m.topic])
        if misc_desc:
            lines.append(f"- 近期高频认知薄弱点/易错概念：{misc_desc}（讲解相关内容时请予以特别点拨澄清）")

    lines.append("")
    return "\n".join(lines)


EVOLVE_PROMPT = """你是一个认知诊断与学习者画像分析专家。
分析以下学生的近期学习交互内容（提问、报错、对话），提炼该学生的认知特征和知识薄弱点。

已知该学生当前画像：
{current_summary}

学生交互内容：
{dialogue_snippet}

请完成两项分析：
1. updated_summary: 综合已有画像与最新表现，给出一段连贯精炼的学习者画像总结（100字以内，涵盖：专业背景/基础强弱/思维习惯/学习偏好。如果本次交互未显露新的特征，则保留或微调原画像）。
2. new_misconceptions: 本次交互中学生显露出的【明确概念理解误区或薄弱点】（0~2个）。每个包含：
   - topic: 知识点名称（如 "C++ 指针运算"、"递归栈溢出"、"微积分链式法则"）
   - tag: 简短错误类型标签（如 "语法混淆"、"边界条件缺失"、"概念错位"）
   - evidence: 错误具体表现（20字以内）

请以 JSON 格式输出，不要有额外解释：
```json
{{
  "updated_summary": "...",
  "new_misconceptions": [
    {{"topic": "...", "tag": "...", "evidence": "..."}}
  ]
}}
```"""


async def evolve_profile_from_interaction(
    dialogue_snippet_or_factory: Any = "",
    *,
    context: str = "",
    interaction: str = "",
    dialogue_snippet: str = "",
) -> dict[str, Any] | None:
    """根据一次学习交互提炼并更新画像与认知易错点。

    兼容单参数 (dialogue_snippet) 以及 (session_factory, context=..., interaction=...) 多种历史调用方式。
    """
    parts = []
    if context:
        parts.append(str(context).strip())
    if interaction:
        parts.append(str(interaction).strip())
    if dialogue_snippet:
        parts.append(str(dialogue_snippet).strip())
    if not parts and isinstance(dialogue_snippet_or_factory, str):
        parts.append(dialogue_snippet_or_factory.strip())

    snippet = "\n".join(p for p in parts if p).strip()
    if len(snippet) < 6:
        return None

    # 控制截断，防止分析消耗过大
    if len(snippet) > 1500:
        snippet = snippet[:1500] + "..."

    async with async_session_factory() as db:
        try:
            profile = await get_or_create_profile(db)
            current_summary = profile.background_summary or "（暂无，尚待建立）"

            prompt = EVOLVE_PROMPT.format(
                current_summary=current_summary,
                dialogue_snippet=snippet,
            )

            adapter = await create_adapter_from_settings(db, scene="chat")
            response = await adapter.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            data = extract_json(response)
            if not isinstance(data, dict):
                return None

            updated_summary = data.get("updated_summary")
            if updated_summary and isinstance(updated_summary, str) and updated_summary.strip():
                # 仅在非空且有内容时更新画像
                profile.background_summary = updated_summary.strip()
                profile.updated_at = utcnow_iso()

            new_miscs = data.get("new_misconceptions") or []
            if isinstance(new_miscs, list):
                for item in new_miscs:
                    if isinstance(item, dict) and item.get("topic"):
                        topic_str = str(item["topic"])[:64]
                        tag_str = str(item.get("tag", "理解偏差"))[:32]
                        # 避免重复插入相同 topic 和 tag 的未解决盲区
                        existing = await db.scalar(
                            select(LearnerMisconception).where(
                                LearnerMisconception.topic == topic_str,
                                LearnerMisconception.tag == tag_str,
                                LearnerMisconception.status == "active",
                            )
                        )
                        if existing:
                            continue
                        misc = LearnerMisconception(
                            topic=topic_str,
                            tag=tag_str,
                            evidence=str(item.get("evidence", ""))[:128],
                            status="active",
                        )
                        db.add(misc)

            await db.commit()
            return data
        except Exception as e:
            logger.warning(f"Failed to evolve learner profile: {e}")
            return None


def trigger_profile_evolution(
    dialogue_snippet: str = "",
    *,
    context: str = "",
    interaction: str = "",
) -> None:
    """触发非阻塞后台认知演进任务，持有强引用避免被 GC 回收。"""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            evolve_profile_from_interaction(
                dialogue_snippet=dialogue_snippet,
                context=context,
                interaction=interaction,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        # 没有活跃事件循环时直接安全忽略
        pass

    return None


extract_and_update_learner_profile = evolve_profile_from_interaction
