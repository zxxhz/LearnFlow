"""异步 SQLAlchemy 引擎与会话工厂。SQLite 开 WAL + 外键约束。"""
import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.db_path.as_posix()}",
    connect_args={"timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    async with async_session_factory() as session:
        yield session


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
            # v0.4.22 题库自定义提示词
            "ALTER TABLE question_banks ADD COLUMN ai_prompt TEXT DEFAULT ''",
        ]
        for ddl in migrations:
            try:
                await conn.execute(text(ddl))
            except Exception:  # 列已存在
                pass

    # v0.4.0 移除费曼/复习模块的老库清理。须在 foreign_keys=OFF 的独立连接上做：
    # feynman 对话连带消息先删 → DROP 三张表；conversations 里指向已删表的
    # feynman_session_id 列受 FK 约束无法 DROP COLUMN，按 SQLite 流程重建表。
    # 新库没有这些表/列，全部幂等跳过。
    async with engine.connect() as legacy:
        await legacy.exec_driver_sql("PRAGMA foreign_keys=OFF")
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
    logger.info("数据库已就绪: %s", settings.db_path)
