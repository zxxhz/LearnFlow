"""异步 SQLAlchemy 引擎与会话工厂。SQLite 开 WAL + 外键约束。"""
import logging
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

# 用 URL.create 而非 f-string 拼 URL：路径含 ? / # 时会被误解析成 query/fragment，
# create 会对 database 字段做正确转义（方言保持 sqlite+aiosqlite 不变）
engine = create_async_engine(
    URL.create("sqlite+aiosqlite", database=str(settings.db_path)),
    connect_args={"timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    # 与 connect_args timeout=30 对齐（两者是同一 busy handler，PRAGMA 会覆盖后者）：
    # relay 全量 pull / 题库替换等长写事务期间，并发写等待 5s 即报 database is locked（v0.5.1 体检 P2 实证）
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def read_snapshot(db: AsyncSession):
    """让同一 Session 的多条 SELECT 共享同一 WAL 快照（v0.5.8 体检 P2）。

    pysqlite/aiosqlite 的 legacy 事务模式把 BEGIN 推迟到首条 DML，纯 SELECT 各自
    autocommit 独立快照——统计/打包/抽轮这类多查询序列在并发写之下会产生自不一致
    结果。显式发出 BEGIN（deferred）让后续 SELECT 进入同一事务；已在事务中（工具链
    等复用会话的场景）则让步、保持调用方原有语义。只可包裹纯读序列（包裹内若出现
    DML 会因事务已开启而行为改变）。
    """
    from sqlalchemy import text as _text

    in_txn = db.in_transaction()
    if not in_txn:
        await db.execute(_text("BEGIN"))
    try:
        yield
    finally:
        if not in_txn:
            await db.commit()


async def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    async with async_session_factory() as session:
        yield session


# ---------------- v0.5.5 一次性数据修复：误触重答流水撤回 ----------------

# 恢复草稿曾把已答题重新解锁（v0.5.5 已修复），误触提交 → 退出重进 → 重答正确
# 会留下一条不出池、却永久拖低累计正确率的错误流水。签名：同题「连续错误段 +
# 紧随的正确作答收尾」且总跨度 ≤ 10 分钟——正常轮内答错后 UI 本不允许重答，
# 该签名只可能来自上述 bug。真实库实测误触对全部落在 5.8s~210s（含一例连错两次），
# 唯一一例真实错题重刷间隔 13.5h，600s 阈值两边留足边际。一次性执行后落
# data_fixes 标记：此后错题重刷等正常场景的快速答对不再被扫描，绝不误撤。
_MISCCLICK_FIX_KEY = "v0.5.5_revoke_misclick_double_submissions"
_MISCCLICK_FIX_SPAN_S = 600


async def _revoke_misclick_double_submissions(conn) -> None:
    from sqlalchemy import text

    done = (
        await conn.execute(
            text("SELECT 1 FROM data_fixes WHERE key = :k"), {"k": _MISCCLICK_FIX_KEY}
        )
    ).first()
    if done:
        return
    from datetime import datetime, timezone

    rows = (
        await conn.execute(
            text(
                "SELECT id, question_id, passed, created_at FROM bank_attempts "
                "ORDER BY question_id, created_at"
            )
        )
    ).all()
    by_q: dict[str, list[tuple[str, bool, str]]] = {}
    for aid, qid, passed, ts in rows:
        by_q.setdefault(qid, []).append((aid, bool(passed), ts))

    to_revoke: list[str] = []
    for seq in by_q.values():
        i = 0
        while i < len(seq):
            if not seq[i][1]:  # 连续错误段起点
                j = i
                while j < len(seq) and not seq[j][1]:
                    j += 1
                if j < len(seq) and seq[j][1]:  # 紧随正确收尾
                    try:
                        span = (
                            datetime.fromisoformat(seq[j][2])
                            - datetime.fromisoformat(seq[i][2])
                        ).total_seconds()
                    except ValueError:
                        span = -1.0  # 时间戳畸形宁可漏放不可误撤
                    if 0 <= span <= _MISCCLICK_FIX_SPAN_S:
                        to_revoke.extend(seq[k][0] for k in range(i, j))
                i = j
            else:
                i += 1

    if to_revoke:
        await conn.execute(
            text("UPDATE bank_attempts SET is_revoked = 1 WHERE id = :aid"),
            [{"aid": aid} for aid in to_revoke],
        )
    await conn.execute(
        text("INSERT INTO data_fixes (key, applied_at) VALUES (:k, :t)"),
        {"k": _MISCCLICK_FIX_KEY, "t": datetime.now(timezone.utc).isoformat()},
    )
    if to_revoke:
        logger.info(
            "数据修复：已撤回 %d 条误触重答流水（签名：错误 → 10 分钟内同题答对）",
            len(to_revoke),
        )


async def init_db() -> None:
    from app.models import Base  # noqa: F401  确保全部模型已注册

    # 打包版数据目录可能不存在（APP_DATA_DIR 指向全新应用数据目录）
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移：create_all 不给已存在的表加列（SQLite 无 ADD COLUMN IF NOT EXISTS）。
        # 只追加、不改动历史条目；老库重放时列已存在会报错，按幂等忽略。
        from sqlalchemy import text

        migrations = [
            # v0.1.6 文档来源
            "ALTER TABLE documents ADD COLUMN source VARCHAR(20) DEFAULT 'generated'",
            # v0.2.1 练习新题型与组卷归属
            "ALTER TABLE exercises ADD COLUMN options TEXT DEFAULT ''",
            "ALTER TABLE exercises ADD COLUMN answer TEXT DEFAULT ''",
            "ALTER TABLE exercises ADD COLUMN quiz_id VARCHAR(32) DEFAULT ''",
            # v0.4.0 练习闯关化：关卡顺序 / 渐进提示 / 参考实现
            "ALTER TABLE exercises ADD COLUMN order_index INTEGER DEFAULT 0",
            "ALTER TABLE exercises ADD COLUMN hints TEXT DEFAULT '[]'",
            "ALTER TABLE exercises ADD COLUMN reference_code TEXT DEFAULT ''",
            # v0.4.22 题库自定义提示词与已生成 AI 解析保留
            "ALTER TABLE question_banks ADD COLUMN ai_prompt TEXT DEFAULT ''",
            "ALTER TABLE bank_questions ADD COLUMN ai_explanation TEXT DEFAULT ''",
            # v0.4.47 自动划重点来源标志（清理逻辑依赖，不再按 note 前缀猜测）
            "ALTER TABLE annotations ADD COLUMN is_auto INTEGER DEFAULT 0",
            # v0.4.48 存疑作答与硬骨头跳过、支线搭桥关联（§2/§4）
            "ALTER TABLE bank_attempts ADD COLUMN is_doubtful INTEGER DEFAULT 0",
            "ALTER TABLE exercise_attempts ADD COLUMN is_doubtful INTEGER DEFAULT 0",
            "ALTER TABLE exercises ADD COLUMN is_hard_bone INTEGER DEFAULT 0",
            "ALTER TABLE exercises ADD COLUMN parent_exercise_id VARCHAR(32) DEFAULT ''",
            # v0.4.52 补齐高频查询索引（IF NOT EXISTS，幂等）：仪表盘/错题池/窗口函数取最近作答
            "CREATE INDEX IF NOT EXISTS ix_exercises_quiz_id ON exercises(quiz_id)",
            "CREATE INDEX IF NOT EXISTS ix_exercises_parent_exercise_id ON exercises(parent_exercise_id)",
            "CREATE INDEX IF NOT EXISTS ix_bank_attempts_question_created ON bank_attempts(question_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_exercise_attempts_exercise_created ON exercise_attempts(exercise_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_messages_created_at ON messages(created_at)",
            # v0.4.59 思维导图来源标记与课程关联（课程一键生成导图）
            "ALTER TABLE mind_maps ADD COLUMN source VARCHAR(20) DEFAULT 'manual'",
            "ALTER TABLE mind_maps ADD COLUMN course_id VARCHAR(32)",
            # v0.4.69 认知画像分学科隔离与证据链回溯（吸收 DeepTutor L1/L2/L3 记忆分层）
            "ALTER TABLE learner_misconceptions ADD COLUMN scope VARCHAR(20) DEFAULT 'general'",
            "ALTER TABLE learner_misconceptions ADD COLUMN source_type VARCHAR(20) DEFAULT ''",
            "ALTER TABLE learner_misconceptions ADD COLUMN source_id VARCHAR(64) DEFAULT ''",
            # v0.4.69 出题落库前沙箱自验结果（0 存量未验 / 1 已实测 / 2 输出已校准）
            "ALTER TABLE exercises ADD COLUMN self_verified INTEGER DEFAULT 0",
            # v0.5.0 统一 AI 助教会话归属域（document / bank_question / global）
            "ALTER TABLE conversations ADD COLUMN context_type VARCHAR(20) DEFAULT ''",
            "ALTER TABLE conversations ADD COLUMN context_id VARCHAR(64) DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS ix_conversations_context_id ON conversations(context_id)",
            # v0.5.1 助教会话归属唯一性：并发首访不再产生重复会话（消息黑洞）；
            # 服务层配合 IntegrityError 重查兜底。存量若已有重复行，本条创建失败仅告警不阻断
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_conversations_assistant ON conversations(kind, context_type, context_id) WHERE kind = 'assistant'",
            # v0.5.5 作答软撤回（误触撤回不计入统计）：物理删除会被同步 upsert 拉回复活，走字段标记
            "ALTER TABLE bank_attempts ADD COLUMN is_revoked INTEGER DEFAULT 0",
            # v0.5.8 同步「新者胜」字段级时间戳（"" 视为最旧的历史行）与删除墓碑表（建表由 create_all 承担）
            "ALTER TABLE bank_questions ADD COLUMN updated_at VARCHAR(40) DEFAULT ''",
            "ALTER TABLE bank_attempts ADD COLUMN updated_at VARCHAR(40) DEFAULT ''",
            # v0.5.5 一次性数据修复的完成标记（幂等 DDL；修复本体见 _revoke_misclick_double_submissions）
            "CREATE TABLE IF NOT EXISTS data_fixes (key TEXT PRIMARY KEY, applied_at TEXT NOT NULL)",
        ]
        for ddl in migrations:
            try:
                await conn.execute(text(ddl))
            except Exception as e:  # noqa: BLE001
                # 仅幂等忽略「列已存在」；其余失败直接中止启动（v0.5.3 体检 P3）：
                # 表缺失/磁盘只读等问题静默吞掉会让依赖该列的后续索引也静默失败，
                # 问题被推迟到运行期以 OperationalError 暴露，排查成本远高于启动失败
                if "duplicate column" in str(e).lower():
                    continue
                logger.error("轻量迁移执行失败，中止启动: %s；原因: %s", ddl, e)
                raise

        # v0.5.5 一次性数据修复：撤回历史误触重答流水（marker 门控，幂等）
        await _revoke_misclick_double_submissions(conn)

    # v0.4.0 移除费曼/复习模块的老库清理。须在 foreign_keys=OFF 的独立连接上做：
    # feynman 对话连带消息先删 → DROP 三张表；conversations 里指向已删表的
    # feynman_session_id 列受 FK 约束无法 DROP COLUMN，按 SQLite 流程重建表。
    # 新库没有这些表/列，全部幂等跳过。
    # 注意：PRAGMA 是连接级状态，该连接归还连接池前必须恢复 foreign_keys=ON，
    # 否则池内这条连接在进程生命周期内永久失去外键约束（迁移中途抛错也不能漏）。
    async with engine.connect() as legacy:
        await legacy.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            tables = {
                r[0] for r in (
                    await legacy.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
                )
            }
            has_session_col = False
            if "conversations" in tables:
                cols = [r[1] for r in (await legacy.execute(text("PRAGMA table_info(conversations)")))]
                has_session_col = "feynman_session_id" in cols
                if has_session_col:
                    await legacy.execute(text(
                        "DELETE FROM messages WHERE conversation_id IN "
                        "(SELECT id FROM conversations WHERE kind = 'feynman')"
                    ))
                    await legacy.execute(text("DELETE FROM conversations WHERE kind = 'feynman'"))
            for t in ("review_logs", "review_cards", "feynman_sessions"):
                if t in tables:
                    await legacy.execute(text(f"DROP TABLE {t}"))
            if has_session_col:
                await legacy.execute(text(
                    "CREATE TABLE conversations_new ("
                    "id VARCHAR(32) NOT NULL PRIMARY KEY, "
                    "user_id VARCHAR(32), "
                    "kind VARCHAR(20), "
                    "annotation_id VARCHAR(32) REFERENCES annotations(id), "
                    "created_at VARCHAR(40))"
                ))
                await legacy.execute(text(
                    "INSERT INTO conversations_new (id, user_id, kind, annotation_id, created_at) "
                    "SELECT id, user_id, kind, annotation_id, created_at FROM conversations"
                ))
                await legacy.execute(text("DROP TABLE conversations"))
                await legacy.execute(text("ALTER TABLE conversations_new RENAME TO conversations"))
                await legacy.execute(text(
                    "CREATE INDEX ix_conversations_user_id ON conversations (user_id)"
                ))
                await legacy.execute(text(
                    "CREATE INDEX ix_conversations_annotation_id ON conversations (annotation_id)"
                ))
            await legacy.commit()
        finally:
            # 归还连接池前恢复外键约束（即使迁移中途抛错），避免污染池内连接
            await legacy.exec_driver_sql("PRAGMA foreign_keys=ON")

    # 数据保留裁剪：仅裁运行痕迹类大表（代码执行记录 / LLM 用量），messages、
    # 作答记录等用户内容一律不动。created_at 为 UTC ISO 字符串，字典序即时间序。
    async with engine.begin() as conn:
        for table, keep in (("code_executions", 500), ("llm_usages", 5000)):
            result = await conn.execute(
                text(
                    f"DELETE FROM {table} WHERE id NOT IN "
                    f"(SELECT id FROM {table} ORDER BY created_at DESC LIMIT {keep})"
                )
            )
            if result.rowcount:
                logger.info("数据保留裁剪：%s 清理 %s 行（仅保留最近 %s 条）", table, result.rowcount, keep)
    logger.info("数据库已就绪: %s", settings.db_path)
