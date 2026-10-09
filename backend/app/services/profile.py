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


async def get_or_create_profile(db: AsyncSession, profile_id: str = DEFAULT_PROFILE_ID) -> LearnerProfile:
    """获取学习者画像；不存在时自动创建并持久化默认实例。"""
    profile = await db.get(LearnerProfile, profile_id)
    if profile is None:
        profile = LearnerProfile(
            id=profile_id,
            background_summary="",
            socratic_mode=True,
            updated_at=utcnow_iso(),
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
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


async def evolve_profile_from_interaction(dialogue_snippet: str) -> dict[str, Any] | None:
    """根据一次学习交互提炼并更新画像与认知易错点。"""
    snippet = dialogue_snippet.strip()
    if len(snippet) < 6:
        return None

    # 控制截断，防止分析消耗过大
    if len(snippet) > 1500:
        snippet = snippet[:1500] + "..."

    async with async_session_factory() as db:
        profile = await get_or_create_profile(db)
        current_summary = profile.background_summary or "（暂无，尚待建立）"

        prompt = EVOLVE_PROMPT.format(
            current_summary=current_summary,
            dialogue_snippet=snippet,
        )

        try:
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
                        misc = LearnerMisconception(
                            topic=str(item["topic"])[:64],
                            tag=str(item.get("tag", "理解偏差"))[:32],
                            evidence=str(item.get("evidence", ""))[:128],
                            status="active",
                        )
                        db.add(misc)

            await db.commit()
            return data
        except Exception as e:
            logger.warning(f"Failed to evolve learner profile: {e}")
            return None


def trigger_profile_evolution(dialogue_snippet: str) -> None:
    """触发非阻塞后台认知演进任务。"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(evolve_profile_from_interaction(dialogue_snippet))
    except RuntimeError:
        # 没有活跃事件循环时直接安全忽略
        pass

    return None


extract_and_update_learner_profile = evolve_profile_from_interaction
