"""学习者画像与认知诊断服务：获取、更新、Prompt 注入与基于对话的异步认知提炼。"""
import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.models.base import utcnow_iso
from app.models.study import LearnerMisconception, LearnerProfile
from app.services.prompt import render_prompt
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
            pass
        # 行已由短会话落库，从调用方会话读取（读事务不持写锁）。
        # 读不到说明落库失败——宁可抛错让上层降级，也不返回游离实例
        # （游离实例上的画像演进写入会被静默丢弃）。
        profile = await db.get(LearnerProfile, profile_id)
        if profile is None:
            raise LookupError("学习者画像初始化失败，请检查数据目录权限")
    return profile


async def get_active_misconceptions(
    db: AsyncSession, limit: int = 10, scope: str | None = None
) -> list[LearnerMisconception]:
    """获取用户当前未解决的易错认知/盲区记录。

    scope：传入学科域（coding/math/theory）时只取该学科与通用（general）盲区，
    避免其他学科盲区串味；None 保持全量（向后兼容）。
    """
    stmt = select(LearnerMisconception).where(LearnerMisconception.status == "active")
    if scope:
        stmt = stmt.where(LearnerMisconception.scope.in_([scope, "general"]))
    stmt = stmt.order_by(LearnerMisconception.created_at.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


def discipline_for_course(course: Any) -> str:
    """课程 → 学科域（coding/math/theory），取不到回落 general。"""
    if course is None:
        return "general"
    try:
        from app.services.exercise import detect_course_discipline

        return detect_course_discipline(
            str(getattr(course, "topic", "") or ""), str(getattr(course, "title", "") or "")
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("resolve course discipline failed: %s", e)
        return "general"


def discipline_for_text(text: str) -> str:
    """自由文本（课程主题/题库名等）→ 学科域，兜底 general。"""
    try:
        from app.services.exercise import detect_course_discipline

        return detect_course_discipline(str(text or ""), str(text or ""))
    except Exception:  # noqa: BLE001
        return "general"


async def discipline_for_course_id(db: AsyncSession, course_id: str | None) -> str:
    """课程 id → 学科域；无效 id 回落 general。"""
    if not course_id:
        return "general"
    try:
        from app.models.course import Course

        return discipline_for_course(await db.get(Course, course_id))
    except Exception as e:  # noqa: BLE001
        logger.debug("resolve course discipline failed: %s", e)
        return "general"


async def discipline_for_document(db: AsyncSession, document: Any) -> str:
    """文档 → 所属课程学科域；课程缺失或查询失败回落 general（不阻断主链路）。"""
    try:
        course_id = str(getattr(document, "course_id", "") or "") if document else ""
        if not course_id:
            return "general"
        from app.models.course import Course

        return discipline_for_course(await db.get(Course, course_id))
    except Exception as e:  # noqa: BLE001
        logger.debug("resolve document discipline failed: %s", e)
        return "general"


async def format_profile_for_prompt(db: AsyncSession, scope: str | None = None) -> str:
    """为大纲/正文/问答/助教 Prompt 格式化学习者认知上下文。

    若画像完全为空且无活跃盲区，返回空字符串；
    若包含信息，则组合成引导语。
    scope：当前链路所属学科域（coding/math/theory）。传入后仅注入该学科与
    通用盲区，防止跨学科串味（如 C++ 盲区混进高数讲义）；None 保持全量兼容。
    画像初始化失败时降级为通用风格提示，不阻断生成/答疑主链路。
    """
    try:
        profile = await get_or_create_profile(db)
    except LookupError as e:
        logger.warning(f"画像不可用，Prompt 注入降级: {e}")
        return "\n## 教学风格偏好\n- 答疑与引导风格：优先采用苏格拉底式启发提问，引导学生自主思考\n"
    misconceptions = await get_active_misconceptions(db, limit=8, scope=scope)

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





async def evolve_profile_from_interaction(
    dialogue_snippet_or_factory: Any = "",
    *,
    context: str = "",
    interaction: str = "",
    dialogue_snippet: str = "",
    scope: str = "general",
    source_type: str = "",
    source_id: str = "",
) -> dict[str, Any] | None:
    """根据一次学习交互提炼并更新画像与认知易错点。

    兼容单参数 (dialogue_snippet) 以及 (session_factory, context=..., interaction=...) 多种历史调用方式。
    scope/source_type/source_id：本次交互的学科域与证据来源（练习/题库/划线对话），
    落库时盖章到新盲区上，支撑分学科注入与证据回溯。
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

            prompt = render_prompt(
                "profile_evolve",
                CURRENT_SUMMARY=current_summary,
                SNIPPET=snippet,
            )

            # 后台静默任务走 task 槽位（未配置自动回落主配置），并限制输出长度防长跑
            adapter = await create_adapter_from_settings(db, scene="task")
            response = await adapter.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
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
                        # 去重看全部历史行（含 resolved）：用户已判定掌握的盲区
                        # 不得被 LLM 再诊断复活
                        existing = await db.scalar(
                            select(LearnerMisconception).where(
                                LearnerMisconception.topic == topic_str,
                                LearnerMisconception.tag == tag_str,
                            )
                        )
                        if existing:
                            continue
                        misc = LearnerMisconception(
                            topic=topic_str,
                            tag=tag_str,
                            evidence=str(item.get("evidence", ""))[:128],
                            status="active",
                            scope=str(scope or "general")[:20],
                            source_type=str(source_type or "")[:20],
                            source_id=str(source_id or "")[:64],
                        )
                        db.add(misc)

            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to evolve learner profile: {e}")
            return None

    # 活跃盲区超阈值时后台归并同类项（吸收 DeepTutor Memory consolidator）
    try:
        await maybe_consolidate_misconceptions()
    except Exception as e:  # noqa: BLE001
        logger.debug("misconception consolidate skipped: %s", e)
    return data


def trigger_profile_evolution(
    dialogue_snippet: str = "",
    *,
    context: str = "",
    interaction: str = "",
    scope: str = "general",
    source_type: str = "",
    source_id: str = "",
) -> None:
    """触发非阻塞后台认知演进任务，持有强引用避免被 GC 回收。"""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            evolve_profile_from_interaction(
                dialogue_snippet=dialogue_snippet,
                context=context,
                interaction=interaction,
                scope=scope,
                source_type=source_type,
                source_id=source_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        # 没有活跃事件循环时直接安全忽略
        pass

    return None


extract_and_update_learner_profile = evolve_profile_from_interaction


# 盲区证据来源类型常量（source_type 取值）
MISCONCEPTION_SOURCE_EXERCISE = "exercise"
MISCONCEPTION_SOURCE_BANK_QUESTION = "bank_question"
MISCONCEPTION_SOURCE_CONVERSATION = "conversation"

# 活跃盲区超过该数量时触发后台同类项归并（吸收 DeepTutor consolidator 思路）
CONSOLIDATE_THRESHOLD = 25


async def auto_resolve_misconceptions(source_type: str, source_id: str) -> int:
    """来源对象被学习者独立做对后，自动关闭对应盲区（证据闭环）。

    吸收 DeepTutor「练习表现反哺记忆」的闭环：盲区不再只能人工标记已解决，
    而是随原始作答通过自动出清。返回关闭条数。
    """
    if not source_type or not source_id:
        return 0
    try:
        async with async_session_factory() as db:
            stmt = select(LearnerMisconception).where(
                LearnerMisconception.source_type == str(source_type)[:20],
                LearnerMisconception.source_id == str(source_id)[:64],
                LearnerMisconception.status == "active",
            )
            rows = list((await db.scalars(stmt)).all())
            if not rows:
                return 0
            now = utcnow_iso()
            for row in rows:
                row.status = "resolved"
                row.resolved_at = now
            await db.commit()
            return len(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"auto resolve misconceptions failed: {e}")
        return 0


def trigger_misconception_auto_resolve(source_type: str, source_id: str) -> None:
    """非阻塞触发盲区自动关闭（来源题作答通过后调用）。"""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(auto_resolve_misconceptions(source_type, source_id))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        pass


class _MisconceptionMergeGroup(BaseModel):
    keep_id: str = ""
    resolve_ids: list[str] = []
    merged_topic: str = ""
    merged_tag: str = "理解偏差"


class _MisconceptionMergePlan(BaseModel):
    groups: list[_MisconceptionMergeGroup] = []


async def maybe_consolidate_misconceptions(*, threshold: int = CONSOLIDATE_THRESHOLD) -> int:
    """活跃盲区超过阈值时，后台用 LLM 合并同类项并归档冗余行。

    LLM 仅输出合并方案；落库前逐组校验 id 合法且互相独立，防幻觉误删。
    返回归并关闭的行数；未配 LLM 或低于阈值时为 0。
    """
    async with async_session_factory() as db:
        active = list(
            (
                await db.scalars(
                    select(LearnerMisconception)
                    .where(LearnerMisconception.status == "active")
                    .order_by(LearnerMisconception.created_at.asc())
                )
            ).all()
        )
        if len(active) <= threshold:
            return 0
        items = "\n".join(
            f"- id={m.id} | 学科={m.scope} | 标签={m.tag} | 盲区={m.topic}" for m in active
        )
        prompt = render_prompt("profile_consolidate", MISCONCEPTIONS=items)
        try:
            adapter = await create_adapter_from_settings(db, scene="task")
        except Exception:  # noqa: BLE001  未配置 LLM 时静默跳过
            return 0
        try:
            plan = await adapter.chat_json([{"role": "user", "content": prompt}], _MisconceptionMergePlan)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"misconception consolidate LLM failed: {e}")
            return 0

        valid_ids = {m.id for m in active}
        applied = 0
        for group in plan.groups[:10]:
            keep_id = str(group.keep_id or "")
            resolve_ids = [str(r) for r in (group.resolve_ids or []) if str(r) != keep_id]
            if keep_id not in valid_ids or not resolve_ids or not group.merged_topic.strip():
                continue
            if any(rid not in valid_ids for rid in resolve_ids):
                continue
            keep_row = await db.get(LearnerMisconception, keep_id)
            if keep_row is None or keep_row.status != "active":
                continue
            keep_row.topic = group.merged_topic.strip()[:100]
            keep_row.tag = (group.merged_tag.strip() or "理解偏差")[:100]
            for rid in resolve_ids:
                row = await db.get(LearnerMisconception, rid)
                if row is not None and row.status == "active":
                    row.status = "resolved"
                    row.resolved_at = utcnow_iso()
                    applied += 1
        if applied:
            await db.commit()
            logger.info("盲区归并完成：%s 条冗余盲区已归档", applied)
        return applied
