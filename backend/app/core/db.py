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
            # v0.2.1 练习错题自动成卡的溯源
            "ALTER TABLE review_cards ADD COLUMN exercise_id VARCHAR(32) DEFAULT ''",
        ]
        for ddl in migrations:
            try:
                await conn.execute(text(ddl))
            except Exception:  # 列已存在
                pass
    logger.info("数据库已就绪: %s", settings.db_path)
