"""云端 SQLite 数据持久化与查询引擎。

支持：
1. 本地客户端推送上来的结构化数据（课程、文档讲义、题库、错题、思维导图、批注等）的批量事务存储与增量 Upsert。
2. 当本地 Worker 离线时，云端服务直接根据 SQLite 中的数据提供查询服务，实现外网随时查看讲义与题库。
3. 纯 Python 标准库 sqlite3 实现，开启 WAL 模式保证高并发读性能与极致稳定性。
"""
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from server.config import settings

logger = logging.getLogger("server.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RelayDatabase:
    """云端数据存储引擎。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.data_dir / "relay.db")

    def _get_connection(self) -> sqlite3.Connection:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db_sync(self):
        """同步初始化表结构。"""
        with self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                topic TEXT DEFAULT '',
                level TEXT,
                outline TEXT,
                status TEXT DEFAULT 'draft',
                course_settings TEXT DEFAULT '{}',
                scope TEXT,
                chapter_count INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                chapter_index INTEGER DEFAULT 0,
                title TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                content TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                status TEXT DEFAULT 'done',
                source TEXT DEFAULT 'generated',
                created_at TEXT,
                updated_at TEXT,
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_docs_course ON documents(course_id);

            CREATE TABLE IF NOT EXISTS question_banks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_file TEXT DEFAULT '',
                question_count INTEGER DEFAULT 0,
                ai_prompt TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS bank_questions (
                id TEXT PRIMARY KEY,
                bank_id TEXT NOT NULL,
                seq INTEGER DEFAULT 0,
                qtype TEXT DEFAULT 'single',
                title TEXT NOT NULL,
                options TEXT DEFAULT '[]',
                answer TEXT DEFAULT '',
                analysis TEXT DEFAULT '',
                difficulty TEXT DEFAULT '',
                created_at TEXT,
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_bquestions_bank ON bank_questions(bank_id);

            CREATE TABLE IF NOT EXISTS bank_attempts (
                id TEXT PRIMARY KEY,
                bank_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                user_answer TEXT DEFAULT '',
                is_correct INTEGER DEFAULT 1,
                is_doubtful INTEGER DEFAULT 0,
                created_at TEXT,
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_battempts_bank ON bank_attempts(bank_id);

            CREATE TABLE IF NOT EXISTS mistakes (
                id TEXT PRIMARY KEY,
                bank_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                wrong_count INTEGER DEFAULT 1,
                last_attempt_at TEXT,
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_mistakes_bank ON mistakes(bank_id);

            CREATE TABLE IF NOT EXISTS mindmaps (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                topic TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS annotations (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                color TEXT DEFAULT 'yellow',
                note TEXT DEFAULT '',
                anchor TEXT DEFAULT '{}',
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT,
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_annotations_doc ON annotations(document_id);

            CREATE TABLE IF NOT EXISTS learner_profile (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

    async def init_db(self):
        """异步初始化数据库。"""
        await asyncio.to_thread(self.init_db_sync)

    def save_sync_payload_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """批量持久化本地同步上来的数据（事务支持）。"""
        counts = {
            "courses": 0,
            "documents": 0,
            "banks": 0,
            "bank_questions": 0,
            "bank_attempts": 0,
            "mistakes": 0,
            "mindmaps": 0,
            "annotations": 0,
        }
        now_str = _now_iso()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Courses
            courses = payload.get("courses") or []
            for c in courses:
                cid = c.get("id")
                if not cid:
                    continue
                cursor.execute(
                    """
                    INSERT INTO courses (id, title, topic, level, outline, status, course_settings, scope, chapter_count, created_at, updated_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        topic = excluded.topic,
                        level = excluded.level,
                        outline = excluded.outline,
                        status = excluded.status,
                        course_settings = excluded.course_settings,
                        scope = excluded.scope,
                        chapter_count = excluded.chapter_count,
                        updated_at = excluded.updated_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        cid,
                        c.get("title", "未命名课程"),
                        c.get("topic", ""),
                        c.get("level"),
                        json.dumps(c.get("outline"), ensure_ascii=False) if isinstance(c.get("outline"), (list, dict)) else c.get("outline"),
                        c.get("status", "ready"),
                        json.dumps(c.get("course_settings", {}), ensure_ascii=False) if isinstance(c.get("course_settings"), dict) else str(c.get("course_settings", "{}")),
                        c.get("scope"),
                        c.get("chapter_count", 0),
                        c.get("created_at", now_str),
                        c.get("updated_at", now_str),
                        json.dumps(c, ensure_ascii=False),
                    ),
                )
                counts["courses"] += 1

            # 2. Documents
            documents = payload.get("documents") or []
            for d in documents:
                did = d.get("id")
                cid = d.get("course_id")
                if not did or not cid:
                    continue
                cursor.execute(
                    """
                    INSERT INTO documents (id, course_id, chapter_index, title, version, content, summary, status, source, created_at, updated_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        course_id = excluded.course_id,
                        chapter_index = excluded.chapter_index,
                        title = excluded.title,
                        version = excluded.version,
                        content = excluded.content,
                        summary = excluded.summary,
                        status = excluded.status,
                        source = excluded.source,
                        updated_at = excluded.updated_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        did,
                        cid,
                        d.get("chapter_index", 0),
                        d.get("title", "未命名章节"),
                        d.get("version", 1),
                        d.get("content") or d.get("content_md") or "",
                        d.get("summary", ""),
                        d.get("status", "done"),
                        d.get("source", "generated"),
                        d.get("created_at", now_str),
                        d.get("updated_at", now_str),
                        json.dumps(d, ensure_ascii=False),
                    ),
                )
                counts["documents"] += 1

            # 3. Question Banks
            banks = payload.get("banks") or payload.get("question_banks") or []
            for b in banks:
                bid = b.get("id")
                if not bid:
                    continue
                cursor.execute(
                    """
                    INSERT INTO question_banks (id, name, source_file, question_count, ai_prompt, created_at, updated_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        source_file = excluded.source_file,
                        question_count = excluded.question_count,
                        ai_prompt = excluded.ai_prompt,
                        updated_at = excluded.updated_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        bid,
                        b.get("name", "未命名题库"),
                        b.get("source_file", ""),
                        b.get("question_count", 0),
                        b.get("ai_prompt", ""),
                        b.get("created_at", now_str),
                        b.get("updated_at", now_str),
                        json.dumps(b, ensure_ascii=False),
                    ),
                )
                counts["banks"] += 1

            # 4. Bank Questions
            questions = payload.get("bank_questions") or payload.get("questions") or []
            for q in questions:
                qid = q.get("id")
                bid = q.get("bank_id")
                if not qid or not bid:
                    continue
                opts = q.get("options", [])
                opts_str = json.dumps(opts, ensure_ascii=False) if isinstance(opts, (list, dict)) else str(opts)
                cursor.execute(
                    """
                    INSERT INTO bank_questions (id, bank_id, seq, qtype, title, options, answer, analysis, difficulty, created_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        bank_id = excluded.bank_id,
                        seq = excluded.seq,
                        qtype = excluded.qtype,
                        title = excluded.title,
                        options = excluded.options,
                        answer = excluded.answer,
                        analysis = excluded.analysis,
                        difficulty = excluded.difficulty,
                        raw_json = excluded.raw_json
                    """,
                    (
                        qid,
                        bid,
                        q.get("seq", 0),
                        q.get("qtype", "single"),
                        q.get("title", ""),
                        opts_str,
                        q.get("answer", ""),
                        q.get("analysis", ""),
                        q.get("difficulty", ""),
                        q.get("created_at", now_str),
                        json.dumps(q, ensure_ascii=False),
                    ),
                )
                counts["bank_questions"] += 1

            # 5. Mistakes / Wrong Questions
            mistakes = payload.get("mistakes") or payload.get("wrong_questions") or []
            for m in mistakes:
                mid = m.get("id") or f"{m.get('bank_id')}_{m.get('question_id')}"
                if not mid:
                    continue
                cursor.execute(
                    """
                    INSERT INTO mistakes (id, bank_id, question_id, wrong_count, last_attempt_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        wrong_count = excluded.wrong_count,
                        last_attempt_at = excluded.last_attempt_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        mid,
                        m.get("bank_id", ""),
                        m.get("question_id", ""),
                        m.get("wrong_count", 1),
                        m.get("last_attempt_at", now_str),
                        json.dumps(m, ensure_ascii=False),
                    ),
                )
                counts["mistakes"] += 1

            # 5b. Bank Attempts
            attempts = payload.get("bank_attempts") or payload.get("attempts") or []
            for att in attempts:
                aid = att.get("id")
                bid = att.get("bank_id")
                qid = att.get("question_id")
                if not aid or not bid or not qid:
                    continue
                # 字段兼容（v0.5.1 体检 P1）：桌面端 BankAttempt 列名是 passed/content，
                # 此前只读 user_answer/is_correct → 本地键不存在时 is_correct 恒缺省 True，
                # 云端统计变成 100% 正确率。以 passed/content 为主，旧字段名兜底。
                user_ans = att.get("content", att.get("user_answer", ""))
                if isinstance(user_ans, list):
                    user_ans = ",".join(user_ans)
                passed_val = att.get("passed", att.get("is_correct", True))
                cursor.execute(
                    """
                    INSERT INTO bank_attempts (id, bank_id, question_id, user_answer, is_correct, is_doubtful, created_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        user_answer = excluded.user_answer,
                        is_correct = excluded.is_correct,
                        is_doubtful = excluded.is_doubtful,
                        raw_json = excluded.raw_json
                    """,
                    (
                        aid,
                        bid,
                        qid,
                        str(user_ans),
                        1 if passed_val else 0,
                        1 if att.get("is_doubtful", False) else 0,
                        att.get("created_at", now_str),
                        json.dumps(att, ensure_ascii=False),
                    ),
                )
                counts["bank_attempts"] += 1

            # 6. Mindmaps
            mindmaps = payload.get("mindmaps") or []
            for mm in mindmaps:
                mmid = mm.get("id")
                if not mmid:
                    continue
                nodes_val = mm.get("nodes", [])
                nodes_str = json.dumps(nodes_val, ensure_ascii=False) if isinstance(nodes_val, (list, dict)) else str(nodes_val)
                cursor.execute(
                    """
                    INSERT INTO mindmaps (id, title, topic, nodes, created_at, updated_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        topic = excluded.topic,
                        nodes = excluded.nodes,
                        updated_at = excluded.updated_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        mmid,
                        mm.get("title", "未命名导图"),
                        mm.get("topic", ""),
                        nodes_str,
                        mm.get("created_at", now_str),
                        mm.get("updated_at", now_str),
                        json.dumps(mm, ensure_ascii=False),
                    ),
                )
                counts["mindmaps"] += 1

            # 7. Annotations
            annotations = payload.get("annotations") or []
            for a in annotations:
                aid = a.get("id")
                did = a.get("document_id")
                if not aid or not did:
                    continue
                anchor_val = a.get("anchor", {})
                anchor_str = json.dumps(anchor_val, ensure_ascii=False) if isinstance(anchor_val, dict) else str(anchor_val)
                cursor.execute(
                    """
                    INSERT INTO annotations (id, document_id, color, note, anchor, status, created_at, updated_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        color = excluded.color,
                        note = excluded.note,
                        anchor = excluded.anchor,
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        aid,
                        did,
                        a.get("color", "yellow"),
                        a.get("note", ""),
                        anchor_str,
                        a.get("status", "active"),
                        a.get("created_at", now_str),
                        a.get("updated_at", now_str),
                        json.dumps(a, ensure_ascii=False),
                    ),
                )
                counts["annotations"] += 1

            # 8. Learner Profile
            profile = payload.get("learner_profile")
            if profile and isinstance(profile, dict):
                # 附带将 learner_misconceptions 一并存入 profile，保障纯 Web 端离线直读完整数据
                if not profile.get("misconceptions") and payload.get("learner_misconceptions"):
                    profile["misconceptions"] = payload.get("learner_misconceptions")
                cursor.execute(
                    """
                    INSERT INTO learner_profile (id, data, updated_at)
                    VALUES ('local', ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        data = excluded.data,
                        updated_at = excluded.updated_at
                    """,
                    (json.dumps(profile, ensure_ascii=False), now_str),
                )
                counts["learner_profile"] = 1

            # 更新元信息
            cursor.execute(
                """
                INSERT INTO sync_metadata (key, value, updated_at)
                VALUES ('last_sync', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (now_str, now_str),
            )
            conn.commit()

        return {
            "ok": True,
            "synced_at": now_str,
            "counts": counts,
        }

    async def save_sync_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """异步批量保存同步数据。"""
        return await asyncio.to_thread(self.save_sync_payload_sync, payload)

    def get_sync_payload_sync(self) -> dict[str, Any]:
        """获取全量已存储的同步数据。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # courses
            cursor.execute("SELECT raw_json FROM courses ORDER BY created_at DESC")
            courses = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # documents
            cursor.execute("SELECT id, course_id, chapter_index, title, version, content, summary, status, source, created_at, updated_at, raw_json FROM documents ORDER BY chapter_index ASC")
            documents = []
            for r in cursor.fetchall():
                d_dict = json.loads(r["raw_json"]) if r["raw_json"] else dict(r)
                # 确保正文 content 与各关键字段完整
                d_dict["content"] = r["content"] or d_dict.get("content", "")
                d_dict["title"] = r["title"]
                d_dict["version"] = r["version"]
                d_dict["course_id"] = r["course_id"]
                documents.append(d_dict)

            # banks
            cursor.execute("SELECT raw_json FROM question_banks ORDER BY created_at DESC")
            banks = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # bank_questions
            cursor.execute("SELECT raw_json FROM bank_questions ORDER BY seq ASC")
            bank_questions = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # bank_attempts
            cursor.execute("SELECT raw_json FROM bank_attempts ORDER BY created_at ASC")
            bank_attempts = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # mistakes
            cursor.execute("SELECT raw_json FROM mistakes ORDER BY last_attempt_at DESC")
            mistakes = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # mindmaps
            cursor.execute("SELECT raw_json FROM mindmaps ORDER BY created_at DESC")
            mindmaps = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # annotations
            cursor.execute("SELECT raw_json FROM annotations ORDER BY created_at ASC")
            annotations = [json.loads(row[0]) for row in cursor.fetchall() if row[0]]

            # learner_profile
            cursor.execute("SELECT data FROM learner_profile WHERE id = 'local'")
            prof_row = cursor.fetchone()
            profile = json.loads(prof_row[0]) if prof_row and prof_row[0] else {}

            cursor.execute("SELECT value FROM sync_metadata WHERE key = 'last_sync'")
            meta_row = cursor.fetchone()
            last_sync = meta_row[0] if meta_row else None

        return {
            "synced_at": last_sync or _now_iso(),
            "courses": courses,
            "documents": documents,
            "banks": banks,
            "question_banks": banks,
            "bank_questions": bank_questions,
            "bank_attempts": bank_attempts,
            "mistakes": mistakes,
            "mindmaps": mindmaps,
            "annotations": annotations,
            "learner_profile": profile,
        }

    async def get_sync_payload(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_sync_payload_sync)

    # ==========================
    # 供前端直接查询的业务查询接口
    # ==========================

    def list_courses_sync(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, topic, level, status, scope, chapter_count, created_at, updated_at
                FROM courses ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
            result = []
            for r in rows:
                result.append({
                    "id": r["id"],
                    "title": r["title"],
                    "topic": r["topic"],
                    "level": r["level"],
                    "status": r["status"],
                    "scope": r["scope"],
                    "chapter_count": r["chapter_count"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
            return result

    async def list_courses(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_courses_sync)

    def get_course_sync(self, course_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM courses WHERE id = ?", (course_id,))
            c_row = cursor.fetchone()
            if not c_row:
                return None

            cursor.execute("""
                SELECT id, course_id, chapter_index, title, version, status, summary, created_at, updated_at
                FROM documents WHERE course_id = ? ORDER BY chapter_index ASC
            """, (course_id,))
            d_rows = cursor.fetchall()
            # 与桌面端 ChapterProgress 字段对齐：前端课程详情页读 document_id 渲染阅读链接
            documents = [
                {**dict(r), "document_id": r["id"]}
                for r in d_rows
            ]

            outline = None
            if c_row["outline"]:
                try:
                    outline = json.loads(c_row["outline"])
                except Exception:
                    outline = c_row["outline"]

            course_settings = {}
            if c_row["course_settings"]:
                try:
                    course_settings = json.loads(c_row["course_settings"])
                except Exception:
                    pass

            return {
                "id": c_row["id"],
                "title": c_row["title"],
                "topic": c_row["topic"],
                "level": c_row["level"],
                "outline": outline,
                "status": c_row["status"],
                "course_settings": course_settings,
                "scope": c_row["scope"],
                "chapter_count": c_row["chapter_count"],
                "created_at": c_row["created_at"],
                "updated_at": c_row["updated_at"],
                "documents": documents,
            }

    async def get_course(self, course_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_course_sync, course_id)

    def get_document_sync(self, doc_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
            d = cursor.fetchone()
            if not d:
                return None
            return {
                "id": d["id"],
                "course_id": d["course_id"],
                "chapter_index": d["chapter_index"],
                "title": d["title"],
                "version": d["version"],
                "content": d["content"],
                "summary": d["summary"],
                "status": d["status"],
                "source": d["source"] if "source" in d.keys() else "generated",
                "created_at": d["created_at"],
                "updated_at": d["updated_at"],
            }

    async def get_document(self, doc_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_document_sync, doc_id)

    # 题库统计的"判断题"题型常量，与桌面端 QUESTION_JUDGE 保持一致（指纹去重口径需要）
    _JUDGE_QTYPE = "judge"

    def _compute_bank_stats_sync(self, bank_ids: list[str]) -> dict[str, dict[str, Any]]:
        """聚合题库统计，口径与桌面端 bulk_bank_stats 严格对齐。

        错题池口径 = 每题最近一次作答「未通过或存疑」；new_count = 指纹去重后从未作答的题数。
        纯 Web 题库页读取 stats.question_count / stats.new_count 等字段，
        云端直答若缺该结构会直接渲染崩溃（reading 'question_count' / 'new_count'）。
        """
        out: dict[str, dict[str, Any]] = {
            bid: {
                "question_count": 0,
                "answered": 0,
                "new_count": 0,
                "attempts": 0,
                "correct": 0,
                "accuracy": 0,
                "wrong_count": 0,
                "by_type": {},
            }
            for bid in bank_ids
        }
        if not bank_ids:
            return out

        placeholders = ",".join("?" * len(bank_ids))

        def _dedup_key(qtype: str, title: str, options: Any, answer: str) -> tuple:
            """题目内容归一化指纹，与桌面端 _question_dedup_key 同规则（含 answer）。"""
            norm_title = " ".join((title or "").split())
            norm_opts: tuple = ()
            if qtype != self._JUDGE_QTYPE and options:
                try:
                    raw = json.loads(options) if isinstance(options, str) else options
                    if isinstance(raw, list):
                        norm_opts = tuple(" ".join(str(o).split()) for o in raw if str(o).strip())
                except Exception:
                    norm_opts = (" ".join(str(options).split()),)
            return (qtype, norm_title, norm_opts, " ".join((answer or "").split()))

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1) 全量作答次数/正确次数（accuracy 用全量口径）
            cursor.execute(
                f"SELECT bank_id, COUNT(*), COALESCE(SUM(is_correct), 0) FROM bank_attempts "
                f"WHERE bank_id IN ({placeholders}) GROUP BY bank_id",
                bank_ids,
            )
            attempt_rows = cursor.fetchall()
            total_attempts = {r[0]: int(r[1] or 0) for r in attempt_rows}
            correct_attempts = {r[0]: int(r[2] or 0) for r in attempt_rows}

            # 2) 每题最近一次作答（窗口函数取 rn=1；平局随机与桌面端窗口排序一致）
            cursor.execute(
                f"SELECT bank_id, question_id, is_correct, is_doubtful FROM ("
                f"  SELECT bank_id, question_id, is_correct, is_doubtful,"
                f"         ROW_NUMBER() OVER (PARTITION BY bank_id, question_id "
                f"                            ORDER BY created_at DESC) AS rn"
                f"  FROM bank_attempts WHERE bank_id IN ({placeholders})"
                f") WHERE rn = 1",
                bank_ids,
            )
            latest: dict[str, dict[str, tuple[int, int]]] = {}
            for r in cursor.fetchall():
                latest.setdefault(r[0], {})[r[1]] = (int(r[2] or 0), int(r[3] or 0))

            # 3) 题目轻量列（统计分布 + 指纹去重，不拉解析长文本）
            cursor.execute(
                f"SELECT bank_id, id, qtype, title, options, answer FROM bank_questions "
                f"WHERE bank_id IN ({placeholders})",
                bank_ids,
            )
            questions: dict[str, list[tuple]] = {}
            for r in cursor.fetchall():
                questions.setdefault(r[0], []).append(r[1:])

        for bid in bank_ids:
            qs = questions.get(bid, [])
            lat = latest.get(bid, {})
            question_count = len(qs)
            answered = len(lat)
            wrong_count = sum(1 for ok, doubtful in lat.values() if ok == 0 or doubtful == 1)
            correct_latest = sum(1 for ok, doubtful in lat.values() if ok == 1 and doubtful == 0)

            by_type: dict[str, dict[str, int]] = {}
            fp_by_id: dict[str, tuple] = {}
            for qid, qtype, title, options, answer in qs:
                entry = by_type.setdefault(qtype, {"total": 0, "wrong": 0})
                entry["total"] += 1
                last = lat.get(qid)
                if last and (last[0] == 0 or last[1] == 1):
                    entry["wrong"] += 1
                fp_by_id[qid] = _dedup_key(qtype, title, options, answer)

            # new_count：指纹去重后从未作答的题数（重复题算 1 道，与桌面端口径一致）
            new_count = question_count
            if question_count and answered:
                answered_fp = {fp_by_id[qid] for qid in lat if qid in fp_by_id}
                new_count = len({k for k in fp_by_id.values() if k not in answered_fp})

            ta = total_attempts.get(bid, 0)
            out[bid] = {
                "question_count": question_count,
                "answered": answered,
                "new_count": new_count,
                "attempts": ta,
                "correct": correct_latest,
                "accuracy": round(correct_attempts.get(bid, 0) / ta * 100, 1) if ta else 0,
                "wrong_count": wrong_count,
                "by_type": by_type,
            }
        return out

    def list_banks_sync(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, source_file, question_count, ai_prompt, created_at, updated_at
                FROM question_banks ORDER BY created_at DESC
            """)
            rows = [dict(r) for r in cursor.fetchall()]
        stats_map = self._compute_bank_stats_sync([r["id"] for r in rows])
        for r in rows:
            r["stats"] = stats_map.get(r["id"]) or {
                "question_count": 0,
                "answered": 0,
                "new_count": 0,
                "attempts": 0,
                "correct": 0,
                "accuracy": 0,
                "wrong_count": 0,
                "by_type": {},
            }
        return rows

    async def list_banks(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_banks_sync)

    def get_bank_sync(self, bank_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM question_banks WHERE id = ?", (bank_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
        stats_map = self._compute_bank_stats_sync([bank_id])
        d["stats"] = stats_map.get(bank_id) or {
            "question_count": 0,
            "answered": 0,
            "new_count": 0,
            "attempts": 0,
            "correct": 0,
            "accuracy": 0,
            "wrong_count": 0,
            "by_type": {},
        }
        return d

    async def get_bank(self, bank_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_bank_sync, bank_id)

    def get_bank_questions_sync(self, bank_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, bank_id, seq, qtype, title, options, answer, analysis, difficulty, created_at
                FROM bank_questions WHERE bank_id = ? ORDER BY seq ASC
            """, (bank_id,))
            rows = cursor.fetchall()
            res = []
            for r in rows:
                d = dict(r)
                try:
                    d["options"] = json.loads(d["options"])
                except Exception:
                    pass
                res.append(d)
            return res

    async def get_bank_questions(self, bank_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_bank_questions_sync, bank_id)

    def get_bank_wrong_questions_sync(self, bank_id: str) -> list[dict[str, Any]]:
        """云端错题池：与桌面端同口径——每题最近一次作答「未通过或存疑」才算错题（v0.5.1 体检 P1）。

        此前直接 JOIN 永不清理的 mistakes 表：历史失败行永存、exercise 来源塌缩为 None_None，
        且与 _compute_bank_stats_sync 的统计口径互相矛盾。改为从 bank_attempts 窗口函数现算。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT q.*, s.wrong_count, s.last_attempt_at
                FROM bank_questions q
                JOIN (
                    SELECT question_id,
                           SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS wrong_count,
                           MAX(created_at) AS last_attempt_at
                    FROM bank_attempts
                    WHERE bank_id = ?
                    GROUP BY question_id
                ) s ON s.question_id = q.id
                JOIN (
                    SELECT question_id, is_correct, is_doubtful,
                           ROW_NUMBER() OVER (PARTITION BY question_id ORDER BY created_at DESC) AS rn
                    FROM bank_attempts
                    WHERE bank_id = ?
                ) a ON a.question_id = q.id AND a.rn = 1
                WHERE q.bank_id = ? AND (a.is_correct = 0 OR a.is_doubtful = 1)
                ORDER BY s.last_attempt_at DESC
                """,
                (bank_id, bank_id, bank_id),
            )
            rows = cursor.fetchall()
            res = []
            for r in rows:
                d = dict(r)
                try:
                    d["options"] = json.loads(d["options"])
                except Exception:
                    pass
                res.append(d)
            return res

    async def get_bank_wrong_questions(self, bank_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_bank_wrong_questions_sync, bank_id)

    def list_mindmaps_sync(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, topic, created_at, updated_at FROM mindmaps ORDER BY created_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    async def list_mindmaps(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_mindmaps_sync)

    def get_mindmap_sync(self, mindmap_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mindmaps WHERE id = ?", (mindmap_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["nodes"] = json.loads(d["nodes"])
            except Exception:
                pass
            return d

    async def get_mindmap(self, mindmap_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_mindmap_sync, mindmap_id)

    def get_learner_profile_sync(self) -> dict[str, Any]:
        """获取学习者认知画像与认知盲区（供云端 Web 离线或独立模式直接使用）。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data, updated_at FROM learner_profile WHERE id = 'local'")
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    data = json.loads(row[0])
                    if isinstance(data, dict):
                        data.setdefault("id", "local")
                        data.setdefault("background_summary", "")
                        data.setdefault("socratic_mode", True)
                        data.setdefault("misconceptions", [])
                        data.setdefault("updated_at", row[1] or _now_iso())
                        return data
                except Exception:
                    pass
            return {
                "id": "local",
                "background_summary": "",
                "socratic_mode": True,
                "misconceptions": [],
                "updated_at": _now_iso(),
            }

    async def get_learner_profile(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_learner_profile_sync)

    def update_learner_profile_sync(
        self,
        background_summary: Optional[str] = None,
        socratic_mode: Optional[bool] = None,
    ) -> dict[str, Any]:
        """更新学习者认知画像设置（背景描述与苏格拉底模式）。"""
        current = self.get_learner_profile_sync()
        if background_summary is not None:
            current["background_summary"] = str(background_summary).strip()
        if socratic_mode is not None:
            current["socratic_mode"] = bool(socratic_mode)
        now_str = _now_iso()
        current["updated_at"] = now_str

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learner_profile (id, data, updated_at)
                VALUES ('local', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(current, ensure_ascii=False), now_str),
            )
            conn.commit()
        return current

    async def update_learner_profile(
        self,
        background_summary: Optional[str] = None,
        socratic_mode: Optional[bool] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.update_learner_profile_sync, background_summary, socratic_mode
        )

    def reset_learner_profile_sync(self) -> dict[str, Any]:
        """重置学习者画像并清空盲区。"""
        now_str = _now_iso()
        fresh = {
            "id": "local",
            "background_summary": "",
            "socratic_mode": True,
            "misconceptions": [],
            "updated_at": now_str,
        }
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learner_profile (id, data, updated_at)
                VALUES ('local', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(fresh, ensure_ascii=False), now_str),
            )
            conn.commit()
        return fresh

    async def reset_learner_profile(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.reset_learner_profile_sync)

    def delete_misconception_sync(self, misconception_id: str) -> bool:
        """从学习者画像中移除单个认知盲区。"""
        current = self.get_learner_profile_sync()
        misconceptions = current.get("misconceptions", [])
        new_misconceptions = [m for m in misconceptions if m.get("id") != misconception_id]
        current["misconceptions"] = new_misconceptions
        now_str = _now_iso()
        current["updated_at"] = now_str

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learner_profile (id, data, updated_at)
                VALUES ('local', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(current, ensure_ascii=False), now_str),
            )
            conn.commit()
        return True

    async def delete_misconception(self, misconception_id: str) -> bool:
        return await asyncio.to_thread(self.delete_misconception_sync, misconception_id)

    def get_db_stats_sync(self) -> dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            stats = {}
            for table in (
                "courses",
                "documents",
                "question_banks",
                "bank_questions",
                "mistakes",
                "mindmaps",
                "annotations",
                "learner_profile",
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            return stats

    async def get_db_stats(self) -> dict[str, int]:
        return await asyncio.to_thread(self.get_db_stats_sync)


relay_db = RelayDatabase()
