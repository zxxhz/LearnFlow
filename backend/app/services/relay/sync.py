"""本地与云端数据同步管理模块。

读取本地的课程、文档正文、题库、练习作答、错题、学习画像、思维导图与划线标注等，
打包后通过 HTTP POST 请求云端的 /api/relay/sync/push，并在同步成功后更新 last_sync_at。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import APP_VERSION, settings
from app.core.db import async_session_factory
from app.models import (
    Annotation,
    BankAttempt,
    BankQuestion,
    Course,
    Document,
    Exercise,
    ExerciseAttempt,
    LearnerMisconception,
    LearnerProfile,
    MindMap,
    QuestionBank,
    StudyDay,
)
from app.services.bank import bank_lock
from app.services.mindmap import _mm_lock, normalize_node, sanitize_settings
from app.models.base import utcnow_iso
from app.services.relay.config import (
    get_relay_config,
    normalize_http_url,
    update_relay_config,
)
from app.services.sections_text import load_document_markdown

logger = logging.getLogger(__name__)

# 云端 payload 中 id 类字段的合法字符集（防路径穿越/注入，v0.5.2 体检 P0）
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_-]+")


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """将 SQLAlchemy ORM 实例安全序列化为普通字典。"""
    if obj is None:
        return {}
    res: dict[str, Any] = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        res[col.name] = val
    return res


async def collect_local_sync_payload(since: str | None = None) -> dict[str, Any]:
    """收集本地所有待同步的数据集合。"""
    async with async_session_factory() as db:
        # 1. 课程与章节文档
        courses_res = await db.scalars(select(Course))
        courses = [_model_to_dict(c) for c in courses_res]

        docs_res = await db.scalars(select(Document))
        documents = []
        for d in docs_res:
            d_dict = _model_to_dict(d)
            # 附加读取本地生成的/导入的 markdown 原文
            d_dict["content_md"] = load_document_markdown(d)
            documents.append(d_dict)

        # 2. 题库与刷题流水
        banks_res = await db.scalars(select(QuestionBank))
        banks = [_model_to_dict(b) for b in banks_res]

        bank_questions_res = await db.scalars(select(BankQuestion))
        bank_questions = [_model_to_dict(q) for q in bank_questions_res]

        bank_attempts_res = await db.scalars(select(BankAttempt))
        bank_attempts = [_model_to_dict(a) for a in bank_attempts_res]

        # 3. 伴学练习与提交记录
        exercises_res = await db.scalars(select(Exercise))
        exercises = [_model_to_dict(e) for e in exercises_res]

        exercise_attempts_res = await db.scalars(select(ExerciseAttempt))
        exercise_attempts = [_model_to_dict(ea) for ea in exercise_attempts_res]

        # 4. 汇总错题清单（提取未通过或存疑的作答记录）
        mistakes = []
        for ba in bank_attempts:
            if not ba.get("passed") or ba.get("is_doubtful"):
                mistakes.append({
                    "source": "bank",
                    "question_id": ba.get("question_id"),
                    "bank_id": ba.get("bank_id"),
                    "attempt_id": ba.get("id"),
                    "content": ba.get("content"),
                    "created_at": ba.get("created_at"),
                })
        for ea in exercise_attempts:
            if not ea.get("passed") or ea.get("is_doubtful"):
                mistakes.append({
                    "source": "exercise",
                    "exercise_id": ea.get("exercise_id"),
                    "attempt_id": ea.get("id"),
                    "content": ea.get("content"),
                    "created_at": ea.get("created_at"),
                })

        # 5. 认知画像与薄弱点标签（完整采集画像与所有盲区记录，保障云端与本地一致）
        from app.services.profile import get_or_create_profile
        try:
            profile_res = await get_or_create_profile(db)
            learner_profile = _model_to_dict(profile_res)
        except Exception:
            profile_res = await db.scalar(select(LearnerProfile).where(LearnerProfile.id == "local"))
            learner_profile = _model_to_dict(profile_res) if profile_res else None

        misconceptions_res = await db.scalars(select(LearnerMisconception))
        learner_misconceptions = [_model_to_dict(m) for m in misconceptions_res]
        if learner_profile is not None:
            learner_profile["misconceptions"] = learner_misconceptions

        # 6. 划线批注
        annotations_res = await db.scalars(select(Annotation))
        annotations = [_model_to_dict(ann) for ann in annotations_res]

        # 7. 思维导图
        mindmaps_res = await db.scalars(select(MindMap))
        mindmaps = [_model_to_dict(mm) for mm in mindmaps_res]

        # 8. 学习打卡天数统计
        study_days_res = await db.scalars(select(StudyDay))
        study_days = [_model_to_dict(sd) for sd in study_days_res]

    return {
        "version": 1,
        "client_version": APP_VERSION,
        "synced_at": utcnow_iso(),
        "since": since,
        "courses": courses,
        "documents": documents,
        "banks": banks,
        "bank_questions": bank_questions,
        "bank_attempts": bank_attempts,
        "exercises": exercises,
        "exercise_attempts": exercise_attempts,
        "mistakes": mistakes,
        "learner_profile": learner_profile,
        "learner_misconceptions": learner_misconceptions,
        "annotations": annotations,
        "mindmaps": mindmaps,
        "study_days": study_days,
    }


async def push_local_data_to_server(
    server_url: str | None = None,
    server_token: str | None = None,
) -> dict[str, Any]:
    """将本地数据打包后推送至云端中转服务器的 /api/relay/sync/push。"""
    cfg = get_relay_config()
    target_url = server_url or cfg.server_url
    target_token = server_token if server_token is not None else cfg.server_token

    if not target_url:
        return {"ok": False, "success": False, "message": "云端服务器地址未配置"}

    http_base = normalize_http_url(target_url)
    push_endpoint = f"{http_base}/api/relay/sync/push"

    logger.info("准备同步本地数据到: %s", push_endpoint)

    headers = {"Content-Type": "application/json"}
    if target_token:
        headers["x-server-token"] = target_token
        headers["x-access-token"] = target_token

    try:
        payload = await collect_local_sync_payload(since=cfg.last_sync_at)

        timeout = httpx.Timeout(timeout=60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(push_endpoint, json=payload, headers=headers)

            if resp.status_code == 200:
                synced_at = payload["synced_at"]
                update_relay_config(last_sync_at=synced_at)
                summary_items = [
                    f"课程 {len(payload['courses'])} 个",
                    f"章节 {len(payload['documents'])} 篇",
                    f"题库 {len(payload['banks'])} 个",
                    f"导图 {len(payload['mindmaps'])} 幅",
                ]
                if payload.get("learner_profile"):
                    summary_items.append("认知画像已同步")
                summary = "，".join(summary_items)
                logger.info("数据同步成功: %s", summary)
                return {
                    "ok": True,
                    "success": True,
                    "message": f"同步成功（{summary}）",
                    "synced_at": synced_at,
                }
            elif resp.status_code in (401, 403):
                return {
                    "ok": False,
                    "success": False,
                    "message": "同步被拒绝：访问令牌无效或权限不足",
                }
            else:
                detail = resp.text[:200]
                return {
                    "ok": False,
                    "success": False,
                    "message": f"服务器返回异常 ({resp.status_code}): {detail}",
                }

    except Exception as exc:
        logger.exception("推送到云端同步接口失败: %s", exc)
        return {
            "ok": False,
            "success": False,
            "message": f"同步请求失败: {exc}",
        }


async def pull_cloud_data_to_local(
    server_url: str | None = None,
    server_token: str | None = None,
) -> dict[str, Any]:
    """从云端服务器的 /api/relay/sync/pull 拉取数据并幂等合并到本地 SQLite 数据库。"""
    cfg = get_relay_config()
    target_url = server_url or cfg.server_url
    target_token = server_token if server_token is not None else cfg.server_token

    if not target_url:
        return {"ok": False, "success": False, "message": "云端服务器地址未配置"}

    http_base = normalize_http_url(target_url)
    pull_endpoint = f"{http_base}/api/relay/sync/pull"

    logger.info("准备从云端拉取数据: %s", pull_endpoint)

    headers = {}
    if target_token:
        headers["x-server-token"] = target_token
        headers["x-access-token"] = target_token

    try:
        timeout = httpx.Timeout(timeout=60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(pull_endpoint, headers=headers)

            if resp.status_code != 200:
                detail = resp.text[:200]
                return {
                    "ok": False,
                    "success": False,
                    "message": f"云端拉取失败 ({resp.status_code}): {detail}",
                }

            data = resp.json()

        courses = data.get("courses") or []
        documents = data.get("documents") or []
        banks = data.get("banks") or data.get("question_banks") or []
        bank_questions = data.get("bank_questions") or data.get("questions") or []
        bank_attempts = data.get("bank_attempts") or []
        mindmaps = data.get("mindmaps") or []
        learner_profile = data.get("learner_profile")

        counts = {
            "courses": 0,
            "documents": 0,
            "banks": 0,
            "questions": 0,
            "attempts": 0,
            "mindmaps": 0,
        }

        async with async_session_factory() as db:
            # 1. 合并课程
            for c in courses:
                cid = c.get("id")
                if not cid:
                    continue
                outline = c.get("outline")
                outline_str = outline if isinstance(outline, str) else json.dumps(outline or [])
                c_settings = c.get("course_settings")
                settings_str = c_settings if isinstance(c_settings, str) else json.dumps(c_settings or {})

                existing_c = await db.get(Course, cid)
                if existing_c:
                    existing_c.title = c.get("title", existing_c.title)
                    existing_c.topic = c.get("topic", existing_c.topic)
                    existing_c.level = c.get("level", existing_c.level)
                    existing_c.outline = outline_str
                    existing_c.status = c.get("status", existing_c.status)
                    existing_c.course_settings = settings_str
                    existing_c.scope = c.get("scope", existing_c.scope)
                    existing_c.chapter_count = c.get("chapter_count", existing_c.chapter_count)
                    existing_c.updated_at = c.get("updated_at") or utcnow_iso()
                else:
                    new_c = Course(
                        id=cid,
                        title=c.get("title", "未命名课程"),
                        topic=c.get("topic", ""),
                        level=c.get("level"),
                        outline=outline_str,
                        status=c.get("status", "draft"),
                        course_settings=settings_str,
                        scope=c.get("scope"),
                        chapter_count=c.get("chapter_count", 0),
                        created_at=c.get("created_at") or utcnow_iso(),
                        updated_at=c.get("updated_at") or utcnow_iso(),
                        user_id=c.get("user_id", "local"),
                    )
                    db.add(new_c)
                counts["courses"] += 1

            # 2. 合并章节文档并持久化保存 Markdown
            for d in documents:
                did = d.get("id")
                cid = d.get("course_id")
                if not did or not cid:
                    continue

                content_md = d.get("content_md") or d.get("content") or ""
                rel_path = d.get("file_path") or f"courses/{cid}/{did}/current.md"

                # 路径穿越守卫（v0.5.2 体检 P0，PoC 实证）：云端 payload 的 file_path/cid/did
                # 完全由对端控制，恶意中转可借 ../../ 逃出 data_dir 任意写文件。
                # resolve() 后强断言仍在 data_dir 内（对齐 system.py 备份解压的既有范式），
                # id 一律限 [A-Za-z0-9_-]，越界条目告警跳过。
                if not _SAFE_ID_RE.fullmatch(str(did)) or not _SAFE_ID_RE.fullmatch(str(cid)):
                    logger.warning("丢弃非法 id 的云端文档条目 (cid=%s did=%s)", cid, did)
                    continue
                try:
                    full_path = (settings.data_dir / rel_path).resolve()
                    if not full_path.is_relative_to(settings.data_dir.resolve()):
                        raise ValueError(f"路径越界：{rel_path}")
                    alt_path = (settings.courses_dir / cid / f"{did}.md").resolve()
                    if not alt_path.is_relative_to(settings.courses_dir.resolve()):
                        raise ValueError(f"备选路径越界：{cid}/{did}.md")
                except (ValueError, OSError) as guard_err:
                    logger.warning("丢弃路径不安全的云端文档条目 (did=%s): %s", did, guard_err)
                    continue

                # 写入本地磁盘 data/courses/{cid}/{did}/current.md 与 data/courses/{cid}/{did}.md
                # （先落盘后 commit：commit 失败只留无害孤儿文件，反向分裂会让 DB 指向缺失文件）
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content_md, encoding="utf-8")
                    alt_path.parent.mkdir(parents=True, exist_ok=True)
                    alt_path.write_text(content_md, encoding="utf-8")
                except Exception as write_err:
                    logger.warning("持久化文档 Markdown 失败 (id=%s): %s", did, write_err)

                existing_doc = await db.get(Document, did)
                if existing_doc:
                    existing_doc.course_id = cid
                    existing_doc.chapter_index = d.get("chapter_index", existing_doc.chapter_index)
                    existing_doc.title = d.get("title", existing_doc.title)
                    existing_doc.version = d.get("version", existing_doc.version)
                    existing_doc.file_path = rel_path
                    existing_doc.summary = d.get("summary", existing_doc.summary)
                    existing_doc.status = d.get("status", existing_doc.status)
                    existing_doc.source = d.get("source", existing_doc.source)
                    existing_doc.updated_at = d.get("updated_at") or utcnow_iso()
                else:
                    new_doc = Document(
                        id=did,
                        course_id=cid,
                        chapter_index=d.get("chapter_index", 0),
                        title=d.get("title", "未命名章节"),
                        version=d.get("version", 1),
                        file_path=rel_path,
                        summary=d.get("summary", ""),
                        status=d.get("status", "done"),
                        source=d.get("source", "generated"),
                        created_at=d.get("created_at") or utcnow_iso(),
                        updated_at=d.get("updated_at") or utcnow_iso(),
                        user_id=d.get("user_id", "local"),
                    )
                    db.add(new_doc)
                counts["documents"] += 1

            # 3~5. 合并题库/题目/作答：按 bank 粒度持 _bank_lock 锁内合并（v0.5.2 体检 P1：
            # 此前 pull 绕过本地全部写锁，与并发改题/替换/刷题交错造成丢失更新与 FK 死锁）
            attempts_by_bank: dict[str, list[dict]] = {}
            for a in bank_attempts:
                bid_a = str(a.get("bank_id") or "")
                if bid_a:
                    attempts_by_bank.setdefault(bid_a, []).append(a)
            questions_by_bank: dict[str, list[dict]] = {}
            for q in bank_questions:
                bid_q = str(q.get("bank_id") or "")
                if bid_q:
                    questions_by_bank.setdefault(bid_q, []).append(q)

            for b in banks:
                bid = b.get("id")
                if not bid:
                    continue
                async with bank_lock(str(bid)):
                    existing_bank = await db.get(QuestionBank, bid)
                    if existing_bank:
                        existing_bank.name = b.get("name", existing_bank.name)
                        existing_bank.source_file = b.get("source_file", existing_bank.source_file)
                        existing_bank.question_count = b.get("question_count", existing_bank.question_count)
                        existing_bank.ai_prompt = b.get("ai_prompt", existing_bank.ai_prompt)
                    else:
                        new_bank = QuestionBank(
                            id=bid,
                            name=b.get("name", "未命名题库"),
                            source_file=b.get("source_file", ""),
                            question_count=b.get("question_count", 0),
                            ai_prompt=b.get("ai_prompt", ""),
                            created_at=b.get("created_at") or utcnow_iso(),
                            user_id=b.get("user_id", "local"),
                        )
                        db.add(new_bank)
                    counts["banks"] += 1

                    # 4. 合并该库题目：seq 与本地现有/本批已有撞号时改派 max+1，
                    # 防 pull 直接落库重复 seq 破坏排序与错题池去重口径（v0.5.2 体检 P2 实证）
                    used_seqs = {
                        row
                        for row in (
                            await db.scalars(
                                select(BankQuestion.seq).where(BankQuestion.bank_id == bid)
                            )
                        )
                    }
                    for q in questions_by_bank.get(str(bid), []):
                        qid = q.get("id")
                        if not qid:
                            continue
                        opts = q.get("options", [])
                        opts_str = json.dumps(opts, ensure_ascii=False) if isinstance(opts, (list, dict)) else str(opts or "[]")
                        existing_q = await db.get(BankQuestion, qid)
                        if existing_q:
                            existing_q.bank_id = bid
                            existing_q.seq = q.get("seq", existing_q.seq)
                            existing_q.qtype = q.get("qtype", existing_q.qtype)
                            existing_q.title = q.get("title", existing_q.title)
                            existing_q.options = opts_str
                            existing_q.answer = q.get("answer", existing_q.answer)
                            existing_q.answer_raw = q.get("answer_raw", existing_q.answer_raw)
                            existing_q.difficulty = q.get("difficulty", existing_q.difficulty)
                            existing_q.explanation = q.get("explanation") or q.get("analysis", existing_q.explanation)
                            existing_q.ai_explanation = q.get("ai_explanation", existing_q.ai_explanation)
                        else:
                            seq = int(q.get("seq") or 0)
                            if seq in used_seqs:
                                seq = (max(used_seqs) if used_seqs else 0) + 1
                            used_seqs.add(seq)
                            new_q = BankQuestion(
                                id=qid,
                                bank_id=bid,
                                seq=seq,
                                qtype=q.get("qtype", "single"),
                                title=q.get("title", ""),
                                options=opts_str,
                                answer=q.get("answer", ""),
                                answer_raw=q.get("answer_raw", ""),
                                difficulty=q.get("difficulty", ""),
                                explanation=q.get("explanation") or q.get("analysis", ""),
                                ai_explanation=q.get("ai_explanation", ""),
                                created_at=q.get("created_at") or utcnow_iso(),
                                user_id=q.get("user_id", "local"),
                            )
                            db.add(new_q)
                        counts["questions"] += 1

                    # 5. 合并该库作答（FK 安全，v0.5.2 体检 P1 实证）：云端残留已被本地
                    # replace 删除的题目的作答时，直接重插会 FK 失败并整体回滚整个 pull。
                    # 先按本地现存 question_id 集合过滤；本地已有同 id 记录则按字段更新（幂等）。
                    local_qids = set(
                        await db.scalars(
                            select(BankQuestion.id).where(BankQuestion.bank_id == bid)
                        )
                    )
                    for a in attempts_by_bank.get(str(bid), []):
                        aid = a.get("id")
                        qid_a = a.get("question_id")
                        if not aid or qid_a not in local_qids:
                            continue
                        content = a.get("content") or a.get("user_answer") or ""
                        passed = bool(a.get("passed") if "passed" in a else a.get("is_correct", True))
                        is_doubtful = bool(a.get("is_doubtful", False))
                        existing_att = await db.get(BankAttempt, aid)
                        if existing_att:
                            existing_att.content = content
                            existing_att.passed = passed
                            existing_att.is_doubtful = is_doubtful
                        else:
                            db.add(
                                BankAttempt(
                                    id=aid,
                                    bank_id=str(a.get("bank_id") or bid),
                                    question_id=str(qid_a),
                                    content=content,
                                    passed=passed,
                                    is_doubtful=is_doubtful,
                                    created_at=a.get("created_at") or utcnow_iso(),
                                    user_id=a.get("user_id", "local"),
                                )
                            )
                            counts["attempts"] += 1

            # 6. 合并思维导图：持 _mm_lock 锁内合并；云端 root 必须过 normalize_node +
            # sanitize_settings（v0.5.2 体检 P1：此前绕过本地全部写路径的不变量，畸形数据可直落库）
            for m in mindmaps:
                mid = m.get("id")
                if not mid:
                    continue
                root = m.get("root") or m.get("nodes") or {}
                if isinstance(root, list):
                    root = {"id": "root", "title": m.get("title", "根节点"), "children": root}
                settings_val = m.get("settings") or {}
                try:
                    async with _mm_lock(str(mid)):
                        existing_m = await db.get(MindMap, mid)
                        if existing_m:
                            existing_m.title = m.get("title", existing_m.title)
                            existing_m.topic = m.get("topic", existing_m.topic)
                            if isinstance(root, dict) and root:
                                existing_m.root = normalize_node(root, existing_m.title)
                            if isinstance(settings_val, dict) and settings_val:
                                existing_m.settings = sanitize_settings(settings_val, existing_m.root)
                            existing_m.updated_at = m.get("updated_at") or utcnow_iso()
                        else:
                            new_m = MindMap(
                                id=mid,
                                title=m.get("title", "新建思维导图"),
                                topic=m.get("topic", ""),
                                root=normalize_node(root, m.get("title", "新建思维导图")) if isinstance(root, dict) and root else {},
                                settings=sanitize_settings(settings_val, root) if isinstance(settings_val, dict) and isinstance(root, dict) and settings_val else {},
                                source=m.get("source", "manual"),
                                course_id=m.get("course_id"),
                                created_at=m.get("created_at") or utcnow_iso(),
                                updated_at=m.get("updated_at") or utcnow_iso(),
                                user_id=m.get("user_id", "local"),
                            )
                            db.add(new_m)
                        counts["mindmaps"] += 1
                except Exception as mm_err:
                    logger.warning("丢弃无法归一化的云端思维导图 (id=%s): %s", mid, mm_err)
                    continue

            # 7. 合并学习者画像与认知盲区
            if learner_profile:
                prof = await db.scalar(select(LearnerProfile).where(LearnerProfile.id == "local"))
                data_dict = (
                    learner_profile.get("data")
                    if "data" in learner_profile and isinstance(learner_profile["data"], dict)
                    else learner_profile
                )
                if prof:
                    if "background_summary" in data_dict:
                        prof.background_summary = str(data_dict.get("background_summary", ""))
                    if "socratic_mode" in data_dict:
                        prof.socratic_mode = bool(data_dict.get("socratic_mode", True))
                    prof.updated_at = utcnow_iso()
                else:
                    new_prof = LearnerProfile(
                        id="local",
                        background_summary=str(data_dict.get("background_summary", "")),
                        socratic_mode=bool(data_dict.get("socratic_mode", True)),
                        updated_at=utcnow_iso(),
                    )
                    db.add(new_prof)

                # 合并认知盲区（复活守卫：本地已 resolve 的盲区不被云端 active 快照回退，v0.5.1 体检遗留）
                misconceptions_list = data_dict.get("misconceptions") or data.get("learner_misconceptions") or []
                for m in misconceptions_list:
                    mid = m.get("id")
                    if not mid:
                        continue
                    existing_m = await db.get(LearnerMisconception, mid)
                    if existing_m:
                        existing_m.topic = m.get("topic", existing_m.topic)
                        existing_m.tag = m.get("tag", existing_m.tag)
                        existing_m.evidence = m.get("evidence", existing_m.evidence)
                        if not (existing_m.status == "resolved" and m.get("status") == "active"):
                            existing_m.status = m.get("status", existing_m.status)
                        existing_m.scope = m.get("scope", existing_m.scope)
                    else:
                        new_m = LearnerMisconception(
                            id=mid,
                            topic=m.get("topic", ""),
                            tag=m.get("tag", ""),
                            evidence=m.get("evidence", ""),
                            status=m.get("status", "active"),
                            resolved_at=m.get("resolved_at"),
                            scope=m.get("scope", "general"),
                            source_type=m.get("source_type", ""),
                            source_id=m.get("source_id", ""),
                        )
                        db.add(new_m)

            await db.commit()

        synced_at = data.get("synced_at") or utcnow_iso()
        update_relay_config(last_sync_at=synced_at)
        summary_items = [
            f"课程 {counts['courses']} 个",
            f"文档 {counts['documents']} 篇",
            f"题库 {counts['banks']} 个",
            f"题目 {counts['questions']} 道",
            f"导图 {counts['mindmaps']} 幅",
        ]
        if learner_profile:
            summary_items.append("认知画像已同步")
        summary = "，".join(summary_items)
        logger.info("云端数据拉取并合并成功: %s", summary)
        return {
            "ok": True,
            "success": True,
            "message": f"拉取合并成功（{summary}）",
            "synced_at": synced_at,
            "counts": counts,
        }

    except Exception as exc:
        logger.exception("拉取云端数据失败: %s", exc)
        return {
            "ok": False,
            "success": False,
            "message": f"拉取合并失败: {exc}",
        }


async def execute_bi_directional_sync(
    server_url: str | None = None,
    server_token: str | None = None,
) -> dict[str, Any]:
    """执行双向数据同步：先从云端拉取更新合并到本地，再将本地最新数据推向云端。"""
    logger.info("开始执行双向数据同步流程...")
    pull_res = await pull_cloud_data_to_local(server_url=server_url, server_token=server_token)
    if not pull_res.get("success") and "未配置" in pull_res.get("message", ""):
        return pull_res

    push_res = await push_local_data_to_server(server_url=server_url, server_token=server_token)

    now_str = utcnow_iso()
    update_relay_config(last_sync_at=now_str)

    pulled_msg = pull_res.get("message", "拉取成功")
    pushed_msg = push_res.get("message", "推送成功")
    return {
        "ok": True,
        "success": True,
        "message": f"双向同步完成（拉取: {pulled_msg}; 推送: {pushed_msg}）",
        "synced_at": now_str,
        "pulled": pull_res,
        "pushed": push_res,
        "pulled_count": sum(pull_res.get("counts", {}).values()) if isinstance(pull_res.get("counts"), dict) else 0,
    }

