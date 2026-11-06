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
                user_ans = att.get("user_answer", "")
                if isinstance(user_ans, list):
                    user_ans = ",".join(user_ans)
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
                        1 if att.get("is_correct", True) else 0,
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
            documents = [dict(r) for r in d_rows]

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
                "created_at": d["created_at"],
                "updated_at": d["updated_at"],
            }

    async def get_document(self, doc_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_document_sync, doc_id)

    def list_banks_sync(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, source_file, question_count, ai_prompt, created_at, updated_at
                FROM question_banks ORDER BY created_at DESC
            """)
            return [dict(r) for r in cursor.fetchall()]

    async def list_banks(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.list_banks_sync)

    def get_bank_sync(self, bank_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM question_banks WHERE id = ?", (bank_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT q.*, m.wrong_count, m.last_attempt_at
                FROM mistakes m
                JOIN bank_questions q ON m.question_id = q.id
                WHERE m.bank_id = ?
                ORDER BY m.last_attempt_at DESC
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

    def get_db_stats_sync(self) -> dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            stats = {}
            for table in ("courses", "documents", "question_banks", "bank_questions", "mistakes", "mindmaps", "annotations"):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            return stats

    async def get_db_stats(self) -> dict[str, int]:
        return await asyncio.to_thread(self.get_db_stats_sync)


relay_db = RelayDatabase()
