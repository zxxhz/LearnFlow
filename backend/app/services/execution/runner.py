"""受限代码运行器（PRD §5.8）。

红线措施（Windows 实现）：
- 时间限制：wall-clock 超时 + 进程树终止（taskkill /T /F，含子进程）
- 内存限制：Job Object PROCESS_MEMORY 上限 256MB
- 进程数限制：Job Object ActiveProcessLimit，防 fork 炸弹
- 孤儿清理：KILL_ON_JOB_CLOSE，句柄关闭即全杀
- 工作目录：一次性临时目录，运行结束销毁；stdin 接 DEVNULL（防 input() 挂起）
- 输出截断：stdout/stderr 各保留末尾 64K 字符

已知取舍（PRD 实现备注 8）：Windows Job Object 无法便捷禁网，
网络隔离未强制执行（本地单用户场景），由时间/内存/进程数限制兜底。
"""
import asyncio
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.models.execution import (
    COMPILE_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    EXEC_COMPILER_MISSING,
    EXEC_COMPILE_ERROR,
    EXEC_ERROR,
    EXEC_RUNTIME_ERROR,
    EXEC_SUCCESS,
    EXEC_TIMEOUT,
    MAX_OUTPUT_CHARS,
    MEMORY_LIMIT_BYTES,
)

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_exec_lock = asyncio.Lock()  # 全局串行：本地单用户，避免资源风暴


def _tail(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")[-MAX_OUTPUT_CHARS:]


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if _IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


# ---------- Windows Job Object（ctypes，无第三方依赖） ----------

def _windows_job():
    """创建带内存/进程数限制 + kill-on-close 的 Job Object 句柄。"""
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    k32 = ctypes.windll.kernel32
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = EXTENDED_LIMITS()
    limits.BasicLimitInformation.LimitFlags = (
        0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | 0x4  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    )
    limits.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
    limits.BasicLimitInformation.ActiveProcessLimit = 64
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        k32.CloseHandle(job)
        return None
    return job, k32


def _assign_to_job(job_handle, k32, proc: subprocess.Popen) -> None:
    try:
        k32.AssignProcessToJobObject(job_handle, int(proc._handle))  # noqa: SLF001
    except Exception:  # noqa: BLE001
        logger.warning("AssignProcessToJobObject failed；降级为无内存限制运行")


def _run_process(cmd: list[str], workdir: str, timeout: float) -> tuple[str, str, int | None, bool]:
    """运行进程，返回 (stdout_tail, stderr_tail, exit_code|None, timed_out)。"""
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        job_ctx = _windows_job() if _IS_WINDOWS else None
        proc = subprocess.Popen(
            cmd,
            cwd=workdir,
            stdout=out_f,
            stderr=err_f,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,
        )
        job_handle = None
        if job_ctx:
            job_handle, k32 = job_ctx
            _assign_to_job(job_handle, k32, proc)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        finally:
            if job_handle:
                k32.TerminateJobObject(job_handle, 0) if timed_out else None
                k32.CloseHandle(job_handle)  # KILL_ON_JOB_CLOSE 兜底清孤儿
        out_f.seek(0)
        err_f.seek(0)
        return _tail(out_f.read()), _tail(err_f.read()), proc.returncode, timed_out


def _find_cpp_compiler() -> str | None:
    return shutil.which("g++") or shutil.which("clang++")


def _sandbox_python() -> str:
    """用户代码运行器。

    打包版 sys.executable 是后端 exe 自身，不能用来跑用户代码；
    随包内置独立 python-runtime（spec datas，stdlib 级别，-I 隔离运行），缺失时回落 PATH。
    """
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "python-runtime" / "python.exe"
        if bundled.exists():
            return str(bundled)
        return shutil.which("python") or "python"
    return sys.executable or "python"


def run_code_sync(language: str, code: str) -> dict:
    """同步执行（应通过 asyncio.to_thread 调用）。返回执行结果字典（不含持久化字段）。"""
    workdir = tempfile.mkdtemp(prefix="learnflow-exec-")
    try:
        if language == "python":
            src = tempfile.mktemp(suffix=".py", dir=workdir)
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            python = _sandbox_python()
            t0 = time.perf_counter()
            out, err, rc, timed_out = _run_process(
                [python, "-I", "-B", "-X", "utf8", src], workdir, DEFAULT_TIMEOUT_SECONDS
            )
            duration = int((time.perf_counter() - t0) * 1000)
            status = EXEC_TIMEOUT if timed_out else (EXEC_SUCCESS if rc == 0 else EXEC_RUNTIME_ERROR)
            if timed_out:
                err = (err + f"\n[LearnFlow] 超过 {DEFAULT_TIMEOUT_SECONDS:g}s 运行上限，已终止。").strip()
            return {"status": status, "exit_code": rc, "stdout": out, "stderr": err, "duration_ms": duration}

        if language == "cpp":
            compiler = _find_cpp_compiler()
            if not compiler:
                return {
                    "status": EXEC_COMPILER_MISSING,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "未检测到 C++ 编译器。请安装 MinGW-w64（g++）并加入 PATH 后重启应用；"
                    "Python 运行不受影响。",
                    "duration_ms": 0,
                }
            src = tempfile.mktemp(suffix=".cpp", dir=workdir)
            exe = tempfile.mktemp(suffix=".exe" if _IS_WINDOWS else "", dir=workdir)
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            t0 = time.perf_counter()
            cout, cerr, crc, _ = _run_process(
                [compiler, "-std=c++17", "-O0", "-o", exe, src],
                workdir,
                COMPILE_TIMEOUT_SECONDS,
            )
            if crc != 0:
                return {
                    "status": EXEC_COMPILE_ERROR,
                    "exit_code": crc,
                    "stdout": cout,
                    "stderr": _tail(f"[编译失败]\n{cerr}".encode()),
                    "duration_ms": int((time.perf_counter() - t0) * 1000),
                }
            out, err, rc, timed_out = _run_process([exe], workdir, DEFAULT_TIMEOUT_SECONDS)
            duration = int((time.perf_counter() - t0) * 1000)
            status = EXEC_TIMEOUT if timed_out else (EXEC_SUCCESS if rc == 0 else EXEC_RUNTIME_ERROR)
            if timed_out:
                err = (err + f"\n[LearnFlow] 超过 {DEFAULT_TIMEOUT_SECONDS:g}s 运行上限，已终止。").strip()
            return {"status": status, "exit_code": rc, "stdout": out, "stderr": err, "duration_ms": duration}

        return {
            "status": EXEC_ERROR,
            "exit_code": None,
            "stdout": "",
            "stderr": f"不支持的语言：{language}",
            "duration_ms": 0,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("sandbox execution failed")
        return {"status": EXEC_ERROR, "exit_code": None, "stdout": "", "stderr": f"沙箱异常：{e}", "duration_ms": 0}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def run_code(language: str, code: str) -> dict:
    async with _exec_lock:
        return await asyncio.to_thread(run_code_sync, language, code)
