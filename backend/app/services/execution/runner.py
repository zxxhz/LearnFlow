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
from app.services.execution import toolchain

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_exec_lock = asyncio.Lock()  # 全局串行：本地单用户，避免资源风暴

if _IS_WINDOWS:
    # 沙箱子进程继承此错误模式：缺 DLL 等加载失败不再弹「系统错误」模态框
    # （曾致 cc1plus 找不到 libwinpthread-1.dll 时弹窗挂起），而是直接以退出码失败
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0001)  # SEM_FAILCRITICALERRORS


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
    # 显式声明参数/返回类型：默认按 C int（32 位）转换，HANDLE 语义上不安全
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
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


def _run_process(
    cmd: list[str], workdir: str, timeout: float, env: dict[str, str] | None = None
) -> tuple[str, str, int | None, bool]:
    """运行进程，返回 (stdout_tail, stderr_tail, exit_code|None, timed_out)。env=None 继承当前环境。"""
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        job_ctx = _windows_job() if _IS_WINDOWS else None
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=workdir,
                env=env,
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,
            )
        except BaseException:
            if job_ctx:  # Popen 失败时没人接手 job 句柄，必须就地关闭（KILL_ON_JOB_CLOSE 兜底）
                _jh, _k32 = job_ctx
                _k32.CloseHandle(_jh)
            raise
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
                if timed_out:
                    k32.TerminateJobObject(job_handle, 0)
                k32.CloseHandle(job_handle)  # KILL_ON_JOB_CLOSE 兜底清孤儿
        out_f.seek(0)
        err_f.seek(0)
        return _tail(out_f.read()), _tail(err_f.read()), proc.returncode, timed_out


def run_code_sync(language: str, code: str) -> dict:
    """同步执行（应通过 asyncio.to_thread 调用）。返回执行结果字典（不含持久化字段）。"""
    workdir = tempfile.mkdtemp(prefix="learnflow-exec-")
    try:
        if language == "python":
            src = tempfile.mktemp(suffix=".py", dir=workdir)
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            python = toolchain.find_python()
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
            compiler = toolchain.find_cpp_compiler()
            if not compiler:
                return {
                    "status": EXEC_COMPILER_MISSING,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "未检测到 C++ 编译器。可点下方「一键安装」获取便携版 g++"
                    "（约 92MB，装在软件目录，不影响系统），Python 运行不受影响。",
                    "duration_ms": 0,
                }
            compiler = toolchain.ascii_compiler(compiler)
            workdir = toolchain.ascii_workdir(workdir)
            src = tempfile.mktemp(suffix=".cpp", dir=workdir)
            exe = tempfile.mktemp(suffix=".exe" if _IS_WINDOWS else "", dir=workdir)
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            t0 = time.perf_counter()
            # 编译步同样前置编译器 bin 到 PATH：cc1plus/collect2 等 g++ 子进程的
            # libwinpthread-1.dll 等 DLL 都在其 bin 目录，且不继承应用自身环境
            compile_env = toolchain.dll_run_env(compiler)
            cout, cerr, crc, _ = _run_process(
                [compiler, "-std=c++17", "-O0", "-o", exe, src],
                workdir,
                COMPILE_TIMEOUT_SECONDS,
                env=compile_env,
            )
            if crc != 0:
                return {
                    "status": EXEC_COMPILE_ERROR,
                    "exit_code": crc,
                    "stdout": cout,
                    "stderr": _tail(f"[编译失败]\n{cerr}".encode()),
                    "duration_ms": int((time.perf_counter() - t0) * 1000),
                }
            # 编译器 bin 目录前置到 PATH：托管安装的 exe 需要 libstdc++ 等运行时 DLL
            out, err, rc, timed_out = _run_process(
                [exe], workdir, DEFAULT_TIMEOUT_SECONDS, env=toolchain.dll_run_env(compiler)
            )
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
