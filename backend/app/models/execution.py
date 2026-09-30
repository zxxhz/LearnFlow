"""代码执行记录（PRD §5.8 / §8.2 [M3]，随执行持久化并回显到文档）。"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk, UserIdMixin

# status 取值
EXEC_SUCCESS = "success"  # 退出码 0
EXEC_RUNTIME_ERROR = "runtime_error"  # 运行完成但退出码非 0
EXEC_TIMEOUT = "timeout"  # 超时被终止
EXEC_COMPILE_ERROR = "compile_error"  # C++ 编译失败
EXEC_COMPILER_MISSING = "compiler_missing"  # 未检测到 C++ 编译器
EXEC_ERROR = "error"  # 沙箱基础设施异常

MAX_CODE_LENGTH = 64_000
MAX_OUTPUT_CHARS = 64_000
DEFAULT_TIMEOUT_SECONDS = 10.0
COMPILE_TIMEOUT_SECONDS = 30.0
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024


class CodeExecution(UUIDPk, UserIdMixin, CreatedAt, Base):
    __tablename__ = "code_executions"

    document_id: Mapped[str] = mapped_column(String(32), index=True)
    section_id: Mapped[str] = mapped_column(String(32), index=True)
    document_version: Mapped[int] = mapped_column(Integer, default=0)
    # python / cpp（规范化后）
    language: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=EXEC_ERROR)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
