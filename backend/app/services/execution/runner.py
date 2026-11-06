"""受限代码运行器（PRD §5.8）。

红线措施（Windows 实现）：
- 时间限制：wall-clock 超时 + 进程树终止（taskkill /T /F，含子进程）
- 内存限制：Job Object 单进程（PROCESS_MEMORY）256MB / Job 全体（JOB_MEMORY）512MB
- 进程数限制：Job Object ActiveProcessLimit，防 fork 炸弹
- 启动时序：CREATE_SUSPENDED 创建 → 赋入 Job → 恢复主线程（消除逃逸窗口）
- 孤儿清理：KILL_ON_JOB_CLOSE，句柄关闭即全杀
- 工作目录：一次性临时目录，运行结束销毁；stdin 接 DEVNULL（防 input() 挂起）
- 输出截断：stdout/stderr 各保留末尾 64K 字符

已知取舍（PRD 实现备注 8）：Windows Job Object 无法便捷禁网，
网络隔离未强制执行（本地单用户场景），由时间/内存/进程数限制兜底。
"""
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

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

# stdout/stderr 落盘上限：死循环 print 在 10s 超时窗口内可写满临时盘，
# Job Object 只限内存/进程数不限 IO，必须由看护线程主动终止
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024

if _IS_WINDOWS:
    # use_last_error=True：ctypes 在每次调用后把 GetLastError 存入线程私有槽，
    # 经 ctypes.get_last_error() 读取，避免错误码被中间 Python 调用覆盖
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # 沙箱子进程继承此错误模式：缺 DLL 等加载失败不再弹「系统错误」模态框
    # （曾致 cc1plus 找不到 libwinpthread-1.dll 时弹窗挂起），而是直接以退出码失败；
    # NOGPFAULTERRORBOX 让用户代码段错误时的 WER 崩溃对话框一并静默。
    # 先 GetErrorMode 取当前值再 OR 合并，避免覆盖宿主进程已设置的其他错误模式位
    _k32.GetErrorMode.restype = wintypes.UINT
    _k32.GetErrorMode.argtypes = []
    _k32.SetErrorMode.restype = wintypes.UINT
    _k32.SetErrorMode.argtypes = [wintypes.UINT]
    _k32.SetErrorMode(_k32.GetErrorMode() | 0x0001 | 0x0002)  # FAILCRITICALERRORS | NOGPFAULTERRORBOX


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

    k32 = _k32
    # 显式声明参数/返回类型：默认按 C int（32 位）转换，HANDLE 语义上不安全
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        logger.warning(
            f"CreateJobObjectW 失败（err={ctypes.get_last_error()}）：本次运行未启用内存/进程红线，仅超时与输出量兜底"
        )
        return None
    limits = EXTENDED_LIMITS()
    limits.BasicLimitInformation.LimitFlags = (
        0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | 0x200  # JOB_OBJECT_LIMIT_JOB_MEMORY（Job 全体进程提交内存总和上限，防多进程摊薄单进程限额）
        | 0x8  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS（0x4 是 JOB_TIME，且未设 Job 时间会 err=87 整体失败）
    )
    limits.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
    # Job 级总内存 = 2× 单进程红线（256MB）：用户代码可 spawn 少量子进程，
    # 总提交内存超过该值时整个 Job 内分配失败（优先于单进程上限触发兜底）
    limits.JobMemoryLimit = 2 * MEMORY_LIMIT_BYTES
    limits.BasicLimitInformation.ActiveProcessLimit = 64
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        err = ctypes.get_last_error()
        logger.warning(
            f"SetInformationJobObject 失败（err={err}）：本次运行未启用内存/进程红线，仅超时与输出量兜底"
        )
        k32.CloseHandle(job)
        return None
    return job, k32


def _assign_to_job(job_handle, k32, proc: subprocess.Popen) -> bool:
    """把进程赋入 Job。返回是否成功；失败时降级运行（由调用方在 stderr 里标注）。"""
    try:
        if k32.AssignProcessToJobObject(job_handle, int(proc._handle)):  # noqa: SLF001
            return True
        logger.warning(
            f"AssignProcessToJobObject 失败（err={ctypes.get_last_error()}）；本次运行未启用内存/进程红线"
        )
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AssignProcessToJobObject 异常（{e}）；本次运行未启用内存/进程红线")
        return False


_TH32CS_SNAPTHREAD = 0x4
_THREAD_SUSPEND_RESUME = 0x0002
_CREATE_SUSPENDED = 0x4


def _resume_suspended_process(pid: int) -> bool:
    """恢复 CREATE_SUSPENDED 启动的进程（经 Toolhelp 快照按 pid 枚举其线程）。

    CREATE_SUSPENDED 刚创建时进程内只有主线程一个线程，按 pid 枚举全部线程
    逐个 ResumeThread 即等价于恢复主线程。返回是否至少成功恢复了一个线程；
    调用方对 False 必须终止进程，绝不能留下挂起进程。
    """
    import ctypes
    from ctypes import wintypes

    class THREADENTRY32(ctypes.Structure):
        """Toolhelp 线程快照条目。"""

        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    k32 = _k32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    k32.OpenThread.restype = wintypes.HANDLE
    k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.ResumeThread.restype = wintypes.DWORD
    k32.ResumeThread.argtypes = [wintypes.HANDLE]

    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return False
    resumed = False
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    ok = bool(k32.Thread32First(snap, ctypes.byref(te)))
    while ok:
        if te.th32OwnerProcessID == pid:
            th = k32.OpenThread(_THREAD_SUSPEND_RESUME, False, te.th32ThreadID)
            if th:
                # 返回 (DWORD)-1 才是失败；0 表示本就未挂起（非主线程残留，同样放行）
                if k32.ResumeThread(th) != 0xFFFFFFFF:
                    resumed = True
                k32.CloseHandle(th)
        te.dwSize = ctypes.sizeof(te)
        ok = bool(k32.Thread32Next(snap, ctypes.byref(te)))
    k32.CloseHandle(snap)
    return resumed


def _run_process(
    cmd: list[str], workdir: str, timeout: float, env: dict[str, str] | None = None
) -> tuple[str, str, int | None, bool]:
    """运行进程，返回 (stdout_tail, stderr_tail, exit_code|None, timed_out)。env=None 继承当前环境。"""
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        job_ctx = _windows_job() if _IS_WINDOWS else None
        degraded_notes: list[str] = []
        if _IS_WINDOWS and job_ctx is None:
            degraded_notes.append("[LearnFlow] 本次运行未启用内存/进程红线（Job Object 创建失败），仅超时与输出量兜底。")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=workdir,
                env=env,
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
                # CREATE_SUSPENDED（0x4）：主线程先挂起，赋入 Job 后再恢复，
                # 消除「进程已跑、尚未进 Job」的逃逸窗口
                creationflags=(subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED) if _IS_WINDOWS else 0,
            )
        except BaseException:
            if job_ctx:  # Popen 失败时没人接手 job 句柄，必须就地关闭（KILL_ON_JOB_CLOSE 兜底）
                _jh, _kh = job_ctx
                _kh.CloseHandle(_jh)
            raise
        job_handle = None
        if job_ctx:
            job_handle, k32 = job_ctx
            if not _assign_to_job(job_handle, k32, proc):
                degraded_notes.append("[LearnFlow] 本次运行未启用内存/进程红线（进程未能加入 Job Object），仅超时与输出量兜底。")
        if _IS_WINDOWS:
            # 赋入 Job 后立即恢复主线程；快照偶发失败重试几次，
            # 彻底失败必须终止——绝不能留下挂起进程（用户会看到"运行卡死"）
            resumed = False
            for _ in range(3):
                if _resume_suspended_process(proc.pid):
                    resumed = True
                    break
                time.sleep(0.05)
            if not resumed:
                _kill_tree(proc)
                if job_handle:
                    k32.TerminateJobObject(job_handle, 0)
                    k32.CloseHandle(job_handle)
                raise RuntimeError("沙箱进程主线程恢复失败（ResumeThread），已终止进程")
        timed_out = False
        flood_killed = False

        def _watch_output() -> None:
            """每 0.5s 查一次输出文件体积，超限即杀进程树（防死循环 print 写满磁盘）。"""
            nonlocal flood_killed
            while True:
                time.sleep(0.5)
                if proc.poll() is not None:
                    return
                try:
                    size = os.fstat(out_f.fileno()).st_size + os.fstat(err_f.fileno()).st_size
                except OSError:
                    return
                if size > _MAX_OUTPUT_BYTES:
                    flood_killed = True
                    _kill_tree(proc)
                    return

        watcher = threading.Thread(target=_watch_output, daemon=True, name="exec-out-watch")
        watcher.start()
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
        out_tail, err_tail = _tail_from_file(out_f), _tail_from_file(err_f)
        if flood_killed:
            err_tail = (
                err_tail
                + f"\n[LearnFlow] 输出量超过 {_MAX_OUTPUT_BYTES // (1024 * 1024)}MB 上限，已强制终止。"
            ).strip()
        if degraded_notes:
            err_tail = "\n".join([err_tail.strip(), *degraded_notes]).strip()
        return out_tail, err_tail, proc.returncode, timed_out


def _tail_from_file(f, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """从临时文件读末尾 max_chars 字节，避免死循环程序把整个输出文件读进内存。"""
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - max_chars * 4))  # UTF-8 最宽 4 字节
    data = f.read()
    text = data.decode("utf-8", errors="replace")
    return text[-max_chars:]


def _unique_file(workdir: str, suffix: str) -> str:
    """workdir 内一次性文件名（替代已废弃的 tempfile.mktemp，避免可预测名竞态）。"""
    return os.path.join(workdir, f"main_{uuid.uuid4().hex[:12]}{suffix}")


def run_code_sync(language: str, code: str) -> dict:
    """同步执行（应通过 asyncio.to_thread 调用）。返回执行结果字典（不含持久化字段）。"""
    workdir = os.path.join(tempfile.gettempdir(), f"learnflow-exec-{uuid.uuid4().hex[:12]}")
    os.makedirs(workdir, exist_ok=True)
    try:
        if language == "python":
            src = _unique_file(workdir, ".py")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            python = toolchain.find_python()
            python_env = toolchain.build_sandbox_env(workdir)
            t0 = time.perf_counter()
            out, err, rc, timed_out = _run_process(
                [python, "-I", "-B", "-X", "utf8", src], workdir, DEFAULT_TIMEOUT_SECONDS, env=python_env
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
            original_workdir = workdir
            workdir = toolchain.ascii_workdir(workdir)
            if workdir != original_workdir:
                # 切到 ASCII 别名目录后，首个含非 ASCII 路径的临时目录立即清理，
                # 否则 finally 只删新目录，每次 C++ 运行都会泄漏一个旧目录
                shutil.rmtree(original_workdir, ignore_errors=True)
            src = _unique_file(workdir, ".cpp")
            exe = _unique_file(workdir, ".exe" if _IS_WINDOWS else "")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            t0 = time.perf_counter()
            # 编译步同样前置编译器 bin 到 PATH：cc1plus/collect2 等 g++ 子进程的
            # libwinpthread-1.dll 等 DLL 都在其 bin 目录，且使用最小隔离环境（不继承应用自身环境与凭据）
            compile_env = toolchain.dll_run_env(compiler, workdir)
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
            # 运行步复用同一环境：编译产物需要 libstdc++-6.dll 等 DLL，与 g++.exe 同目录
            out, err, rc, timed_out = _run_process(
                [exe], workdir, DEFAULT_TIMEOUT_SECONDS, env=compile_env
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
