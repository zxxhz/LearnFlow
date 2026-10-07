"""运行环境工具链：检测 + 一键便携安装（PRD §5.8 沙箱配套）。

设置页「代码运行环境」与代码块 compiler_missing 提示共用：
- C++：niXman mingw-builds 便携版（GCC 14.2.0 / UCRT / posix-seh，7z ~92MB）→ <toolchains>/mingw64/
- Python：python.org embeddable（3.12.10，~11MB，仅标准库，与打包版内置运行时同级）→ <toolchains>/python/

硬性约束（产品决定）：不动系统——不写 PATH / 注册表，不跑系统安装器，
全部文件落在软件安装目录下的 toolchains/（只读时兜底到数据目录）；
沙箱查找顺序固定：系统 PATH → 托管目录（见 runner.py）。

下载按「并发竞速试读」在直连/镜像间择优（GitHub release 大文件在国内直连常超时，
ghproxy 系镜像兜底；python.org 失败走华为云 / npmmirror），先拿到真实数据流的源胜出；
产物做 SHA-256 校验（镜像路径可能被替换，不符即拒装），支持断点续传（分片缓存
.partials/ 跨安装尝试复用）。安装跑在守护线程，进度经 install/status 轮询（前端 1s）。
"""
import copy
import hashlib
import logging
import os
import shutil
import stat as stat_mod
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_EXE = ".exe" if _IS_WINDOWS else ""
_UA = {"User-Agent": "LearnFlow-Toolchain/0.1"}

# 固定版本（确定性优先，不做 latest 探测：版本升级随应用发版一起手动 bump）
MINGW_TAG = "14.2.0-rt_v12-rev2"
MINGW_ASSET = "x86_64-14.2.0-release-posix-seh-ucrt-rt_v12-rev2.7z"
PYTHON_VERSION = "3.12.10"
PYTHON_ASSET = f"python-{PYTHON_VERSION}-embed-amd64.zip"

# 下载产物 SHA-256（供应链校验：镜像路径可能被替换，不符即拒装）。
# bump 版本时随资产名一起从官方源重取；空串 = 未录入，跳过校验并记 warning（勿长期留空）。
MINGW_SHA256 = "918732a84fc8006586be0f5909b75896ab85d5e0e9df521b4d4f9202e7debc12"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
ASSET_SHA256: dict[str, str] = {"cpp": MINGW_SHA256, "python": PYTHON_SHA256}

# 镜像前缀按优先级排列，并发竞速试读择优；空串 = GitHub 直连
_GITHUB_MIRRORS = ["", "https://ghproxy.net/", "https://gh-proxy.com/"]

Component = Literal["python", "cpp"]


def _new_state() -> dict[str, Any]:
    return {"state": "idle", "percent": 0.0, "message": "", "error": None, "log": []}


_INSTALL_STATES: dict[str, dict[str, Any]] = {"python": _new_state(), "cpp": _new_state()}
_STATE_LOCK = threading.Lock()
_THREADS: dict[str, threading.Thread] = {}


def _update(kind: Component, /, **fields: Any) -> None:
    with _STATE_LOCK:
        st = _INSTALL_STATES[kind]
        msg = fields.pop("message", None)
        if msg is not None:
            st["message"] = msg
            st["log"] = (st["log"] + [msg])[-40:]
        st.update(fields)


def get_install_status() -> dict[str, Any]:
    with _STATE_LOCK:
        components = copy.deepcopy(_INSTALL_STATES)
    active = [k for k, t in _THREADS.items() if t.is_alive()]
    return {"components": components, "active": active[0] if active else None}


def _fs_retry(fn, attempts: int = 4, delay: float = 1.0):
    """Windows 上杀软/索引器会短暂锁住刚写入的文件（WinError 5），重试等待即过。"""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except PermissionError as e:
            last_exc = e
            time.sleep(delay * (i + 1))
    raise last_exc  # type: ignore[misc]


def _writable_tree(p: Path) -> None:
    """递归清掉只读位：7z 解压会还原归档里的只读属性，不提前清则后续 rmtree 删不动。"""
    for dirpath, dirnames, filenames in os.walk(p):
        for name in dirnames + filenames:
            try:
                os.chmod(Path(dirpath) / name, stat_mod.S_IWRITE)
            except OSError:
                pass


def _force_rmtree(p: Path) -> None:
    """先清只读再删，配合重试兜底杀软短暂锁定。"""
    if not p.exists():
        return
    _writable_tree(p)
    _fs_retry(lambda: shutil.rmtree(p, ignore_errors=True))


def _cleanup_stale_workdirs(root: Path) -> None:
    """清掉上次失败留下的临时解压目录（超过 1 天的才动，避免误删进行中的安装）。"""
    for d in root.glob("learnflow-tc-*"):
        try:
            if time.time() - d.stat().st_mtime > 86400:
                _force_rmtree(d)
        except OSError:
            pass


def _cleanup_stale_partials(root: Path) -> None:
    """分片缓存只对当前资产名有效（版本 bump 后旧分片永远续传不上），直接清掉。"""
    current = {f"{MINGW_ASSET}.part", f"{PYTHON_ASSET}.part"}
    pdir = root / ".partials"
    if not pdir.is_dir():
        return
    for f in pdir.iterdir():
        try:
            if f.is_file() and f.name not in current:
                f.unlink()
        except OSError:
            pass


def _cleanup_stale_archives(root: Path) -> None:
    """安装包缓存只保留当前版本的资产（版本 bump 后旧包自动淘汰）。"""
    current = {MINGW_ASSET, PYTHON_ASSET}
    adir = root / ".archives"
    if not adir.is_dir():
        return
    for f in adir.iterdir():
        try:
            if f.is_file() and f.name not in current:
                f.unlink()
        except OSError:
            pass


def _archive_cache_path(kind: Component) -> Path:
    name = MINGW_ASSET if kind == "cpp" else PYTHON_ASSET
    return toolchains_root() / ".archives" / name


def _cache_valid(cache: Path, kind: Component) -> bool:
    """缓存包必须通过 SHA-256 校验才能复用（防损坏/被替换）。"""
    if not ASSET_SHA256[kind] or not cache.is_file():
        return False
    try:
        return _sha256_file(cache) == ASSET_SHA256[kind]
    except OSError:
        return False


def start_install(component: str) -> None:
    """启动后台安装线程；已在装/平台不支持时抛 RuntimeError（API 层转 409）。"""
    if component not in ("python", "cpp"):
        raise ValueError(f"未知组件：{component}")
    if not _IS_WINDOWS:
        raise RuntimeError("一键安装仅支持 Windows；其他平台请用系统包管理器安装 g++ / python")
    t = _THREADS.get(component)
    if t and t.is_alive():
        raise RuntimeError(f"{component} 正在安装中")
    root = toolchains_root()
    _cleanup_stale_workdirs(root)
    _cleanup_stale_partials(root)
    _cleanup_stale_archives(root)
    _update(component, state="downloading", percent=0.0, error=None, message="准备下载…")
    thread = threading.Thread(target=_install_worker, args=(component,), daemon=True, name=f"tc-install-{component}")
    _THREADS[component] = thread
    thread.start()


# ---------- 目录与检测 ----------

_ROOT_CACHE: Path | None = None


def toolchains_root() -> Path:
    """工具链根目录：软件安装目录下（打包版 = 安装目录/backend/toolchains，开发版 = backend/toolchains）。

    安装目录只读（如装进 Program Files）时兜底到数据目录，保证功能可用。
    结果按会话缓存：目录只读与否在一次运行内不会变化，不必每次查找都做写探测。
    """
    global _ROOT_CACHE
    if _ROOT_CACHE is not None:
        return _ROOT_CACHE
    primary = settings.toolchains_dir
    try:
        primary.mkdir(parents=True, exist_ok=True)
        probe = primary / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _ROOT_CACHE = primary
    except OSError:
        fallback = settings.data_dir / "toolchains"
        fallback.mkdir(parents=True, exist_ok=True)
        _ROOT_CACHE = fallback
    return _ROOT_CACHE


def managed_python_exe() -> Path | None:
    cand = toolchains_root() / "python" / f"python{_EXE}"
    return cand if cand.exists() else None


def managed_cpp_exe() -> Path | None:
    root = toolchains_root() / "mingw64"
    candidates = [root / "bin" / f"g++{_EXE}", root / "mingw64" / "bin" / f"g++{_EXE}"]
    candidates.extend(root.glob("*/bin/g++.exe"))
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _bundled_python() -> Path | None:
    """打包版随包内置的沙箱运行时（stdlib 级，spec datas 解包到 _MEIPASS）。"""
    if not getattr(sys, "frozen", False):
        return None
    cand = Path(getattr(sys, "_MEIPASS", "")) / "python-runtime" / f"python{_EXE}"
    return cand if cand.exists() else None


def find_python() -> str:
    """沙箱 Python 解释器。打包版优先随包内置运行时，其次应用内托管，最后系统 PATH；
    开发版直接用当前解释器（venv 内含第三方依赖，功能更强）。"""
    bundled = _bundled_python()
    if bundled:
        return str(bundled)
    if not getattr(sys, "frozen", False):
        return sys.executable or "python"
    managed = managed_python_exe()
    if managed:
        return str(managed)
    return shutil.which("python") or "python"


def find_cpp_compiler() -> str | None:
    """C++ 编译器：系统 PATH 优先（用户自装的通常更新），其次应用内托管 g++。"""
    which = shutil.which("g++") or shutil.which("clang++")
    if which:
        return which
    managed = managed_cpp_exe()
    return str(managed) if managed else None


def dll_run_env(compiler: str) -> dict[str, str] | None:
    """运行编译产物时的环境：把编译器 bin 目录前置到 PATH，让 exe 找到
    libstdc++-6.dll 等运行时 DLL（MinGW 目录布局下 DLL 与 g++.exe 同目录）。"""
    if not _IS_WINDOWS:
        return None
    bin_dir = Path(compiler).resolve().parent
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


# ---------- 非 ASCII 路径规避（g++/ld 的 ANSI 编码缺陷） ----------
# MinGW 的 gcc/ld 内部用 ANSI 码页转码 argv 与自身 lib 前缀：路径含非 ASCII 且系统
# 码页表示不了时（如西欧/俄语码页遇上中文路径），ld 报 cannot find crtend.o。
# 解法：把「编译器可见的一切」收进纯 ASCII 空间——目录 junction 别名（免管理员）
# + ASCII 基下的临时工作目录。Python 侧全程宽字符 API，不受影响，无需处理。

def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def _alias_base() -> Path | None:
    """可写且纯 ASCII 的别名基目录（系统临时目录通常就是；中文用户名时退 C:\\Windows\\Temp / Public）。"""
    for base in (Path(tempfile.gettempdir()), Path("C:/Windows/Temp"), Path("C:/Users/Public")):
        try:
            if not _is_ascii(str(base)):
                continue
            d = base / "learnflow-cc"
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return d
        except OSError:
            continue
    return None


def _ascii_mirror(root: Path) -> Path | None:
    """把发行根硬链接克隆到 ASCII 基并返回镜像根。

    gcc 会对 argv[0] 做 realpath：junction/symlink 别名会被解析回真实路径而失效；
    硬链接则是普通文件，realpath 透明，且不占额外磁盘。克隆一次复用（元数据里
    记录源与版本指纹），源变更或被系统清理后自动重建（约 1.4 万文件，20s 级）。"""
    base = _alias_base()
    if base is None:
        return None
    tag = hashlib.sha256(str(root).lower().encode("utf-8")).hexdigest()[:12]
    dst = base / f"tc-{tag}"
    stage: Path | None = None
    try:
        gpp_src = root / "bin" / f"g++{_EXE}"
        if not gpp_src.exists():
            return None
        expect = f"{root}|{gpp_src.stat().st_size}|{int(gpp_src.stat().st_mtime)}"
        if (dst / "bin" / f"g++{_EXE}").exists() and (dst / "bin" / "ld.exe").exists() \
                and (dst / ".learnflow-src").read_text(encoding="utf-8") == expect:
            return dst  # 镜像就绪
        stage = base / f"tc-{tag}.building-{os.getpid()}"
        _force_rmtree(stage)
        for dirpath, _dirnames, filenames in os.walk(root):
            rel = Path(dirpath).relative_to(root)
            (stage / rel).mkdir(parents=True, exist_ok=True)
            for fn in filenames:
                s, d = Path(dirpath) / fn, stage / rel / fn
                try:
                    if d.exists():  # 上次构建的残留（只读文件可能删不净）
                        os.chmod(d, stat_mod.S_IWRITE)
                        os.unlink(d)
                except OSError as e:
                    if not (d.exists() and os.path.samefile(s, d)):
                        raise
                try:
                    os.link(s, d)  # 硬链接：同卷瞬时且零空间；跨卷/不支持时退回复制
                except OSError:
                    shutil.copy2(s, d)
        (stage / ".learnflow-src").write_text(expect, encoding="utf-8")
        _force_rmtree(dst)
        os.rename(stage, dst)
        return dst
    except OSError as e:
        logger.warning("ASCII 硬链接镜像构建失败，g++ 按原路径调用：%s", e)
        if stage is not None:
            _force_rmtree(stage)
        return None


def ascii_compiler(compiler: str) -> str:
    """编译器路径非 ASCII 时返回其 ASCII 硬链接镜像下的等价路径，其余原样返回。"""
    if not _IS_WINDOWS or _is_ascii(compiler):
        return compiler
    root = Path(compiler).resolve().parent.parent  # .../mingw64
    mirror = _ascii_mirror(root)
    if mirror and (mirror / "bin" / Path(compiler).name).exists():
        return str(mirror / "bin" / Path(compiler).name)
    return compiler  # 镜像不可用就原样试（GBK 码页系统本身能跑）


def ascii_workdir(workdir: str) -> str:
    """工作目录非 ASCII 时改在别名基下新建（含源码、编译产物，调用链全 ASCII）。"""
    if _is_ascii(workdir):
        return workdir
    base = _alias_base()
    if base is None:
        return workdir
    return tempfile.mkdtemp(prefix="learnflow-exec-", dir=base)


def _probe_version(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        flags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags)
        first = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        return first[0].strip() if first else ""
    except Exception:  # noqa: BLE001
        return ""


def _probe_version_steady(cmd: list[str], attempts: int = 3, timeout: float = 20.0) -> str:
    """带重试的版本探测：杀软对新解压的上千个文件做首次扫描时，单次短超时探针会误判安装失败。"""
    for i in range(attempts):
        v = _probe_version(cmd, timeout=timeout)
        if v:
            return v
        if i < attempts - 1:
            time.sleep(1.5)
    return ""


def component_status(kind: Component) -> dict[str, Any]:
    if kind == "python":
        if not getattr(sys, "frozen", False):
            # 开发版固定用当前解释器（venv 内含第三方依赖，比托管 embeddable 更强）
            path = sys.executable or shutil.which("python") or ""
            return {"installed": bool(path), "source": "system" if path else "none",
                    "path": path, "version": _probe_version([path, "--version"]) if path else ""}
        bundled = _bundled_python()
        if bundled:
            return {"installed": True, "source": "bundled", "path": str(bundled),
                    "version": _probe_version([str(bundled), "-I", "--version"])}
        managed = managed_python_exe()
        if managed:
            return {"installed": True, "source": "managed", "path": str(managed),
                    "version": _probe_version([str(managed), "-I", "--version"])}
        system = shutil.which("python")
        if system:
            return {"installed": True, "source": "system", "path": system,
                    "version": _probe_version([system, "--version"])}
        return {"installed": False, "source": "none", "path": "", "version": ""}
    # cpp
    system = shutil.which("g++") or shutil.which("clang++")
    if system:
        return {"installed": True, "source": "system", "path": system, "version": _probe_version([system, "--version"])}
    managed = managed_cpp_exe()
    if managed:
        return {"installed": True, "source": "managed", "path": str(managed), "version": _probe_version([str(managed), "--version"])}
    return {"installed": False, "source": "none", "path": "", "version": ""}


def runtime_status() -> dict[str, Any]:
    return {
        "python": component_status("python"),
        "cpp": component_status("cpp"),
        "platform": sys.platform,
        "installable": _IS_WINDOWS,
        "toolchains_dir": str(toolchains_root()),
    }


# ---------- 下载与安装 ----------

def _candidate_urls(kind: Component) -> list[str]:
    if kind == "cpp":
        url = (f"https://github.com/niXman/mingw-builds-binaries/releases/"
               f"download/{MINGW_TAG}/{MINGW_ASSET}")
        from app.services.download_mirrors import get_ordered_mirror_prefixes

        prefixes = get_ordered_mirror_prefixes()
        return [m + url for m in prefixes]
    return [
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ASSET}",
        f"https://mirrors.huaweicloud.com/python/{PYTHON_VERSION}/{PYTHON_ASSET}",
        f"https://registry.npmmirror.com/-/binary/python/{PYTHON_VERSION}/{PYTHON_ASSET}",
    ]


def _probe_url(url: str) -> tuple[bool, str]:
    """512KB Range 试读：拿到真实数据流即认为该源可用。返回 (可用, 失败原因)。"""
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, read=15.0), follow_redirects=True, headers=_UA) as client:
            with client.stream("GET", url, headers={"Range": "bytes=0-524287"}) as r:
                if r.status_code not in (200, 206):
                    return False, f"HTTP {r.status_code}"
                got = 0
                for chunk in r.iter_bytes(65536):
                    got += len(chunk)
                    if got >= 65536:
                        return True, ""
                return False, "响应体过短"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]


def _pick_url(urls: list[str]) -> str:
    """并发竞速择源：先产出真实数据流的源胜出——直连在无外网时不必等满超时才轮到镜像，
    且试读耗时与真实下载速度相关，试读快的源下载也快。"""
    errors: dict[str, str] = {}
    pool = ThreadPoolExecutor(max_workers=len(urls), thread_name_prefix="tc-probe")
    try:
        futs = {pool.submit(_probe_url, u): u for u in urls}
        for fut in as_completed(futs):
            url = futs[fut]
            ok, err = fut.result()
            if ok:
                for f in futs:
                    f.cancel()
                return url
            errors[url] = err
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    detail = "; ".join(f"{httpx.URL(u).host}：{e}" for u, e in errors.items())
    raise RuntimeError(f"所有下载源均不可达（网络受限时可检查代理设置）：{detail or urls}")


def _download_first_available(urls: list[str], dest: Path, kind: Component) -> str:
    """竞速择优 + 逐源回退的完整下载：试读小包成功不代表大文件传输能撑住
    （连接中途被掐很常见），失败自动换下一个源续传（.partials 跨源复用），
    全部失败才抛错。返回最终成功的源 URL。"""
    order: list[str] = []
    try:
        order.append(_pick_url(urls))
    except Exception as e:  # noqa: BLE001
        logger.warning("竞速择源全部失败，退化为顺序尝试：%s", e)
    order += [u for u in urls if u not in order]
    last_err: Exception | None = None
    for i, url in enumerate(order, 1):
        host = httpx.URL(url).host
        try:
            _update(kind, message=f"尝试下载源（{i}/{len(order)}）：{host}")
            _download_to(url, dest, kind)
            return url
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("下载源失败 %s：%s", url, e)
            _update(kind, message=f"下载源 {host} 失败，换下一个…")
    raise RuntimeError(f"所有下载源均下载失败：{last_err}")


def _partial_path(kind: Component) -> Path:
    # 分片名带资产名：版本 bump 后旧分片自动作废，不会错误续传到新资产上
    name = MINGW_ASSET if kind == "cpp" else PYTHON_ASSET
    return toolchains_root() / ".partials" / f"{name}.part"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_to(url: str, dest: Path, kind: Component) -> None:
    """流式下载到 dest：断点续传（分片存 .partials/，失败后下次安装接着下）+
    SHA-256 校验（不符则清分片拒装）。校验通过才落位 dest。"""
    partial = _partial_path(kind)
    partial.parent.mkdir(parents=True, exist_ok=True)
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {**_UA, **({"Range": f"bytes={offset}-"} if offset else {})}
    with httpx.Client(timeout=httpx.Timeout(15.0, read=60.0, write=60.0), follow_redirects=True, headers=headers) as client:
        with client.stream("GET", url) as r:
            if r.status_code == 206 and offset:
                start = offset  # 服务器支持续传
            else:
                r.raise_for_status()
                start = 0  # 无分片 / 服务器不支持 Range：从头下
            total = start + int(r.headers.get("content-length") or 0)
            done = start
            last_pct, last_mb = -1, -1
            with open(partial, "ab" if start else "wb") as f:
                for chunk in r.iter_bytes(262144):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = int(5 + done / total * 85)
                        if pct >= last_pct + 2:  # 节流：状态最多每 2% 写一次
                            last_pct = pct
                            _update(kind, state="downloading", percent=float(pct),
                                    message=f"下载中 {done / 1e6:.0f} / {total / 1e6:.0f} MB（{pct}%）")
                    elif done >= last_mb + 8_000_000:  # 无 Content-Length：按 MB 汇报
                        last_mb = done
                        _update(kind, state="downloading", percent=0.0,
                                message=f"下载中 {done / 1e6:.0f} MB")
    expected = ASSET_SHA256[kind]
    actual = _sha256_file(partial)
    if expected:
        if actual != expected:
            partial.unlink(missing_ok=True)
            raise RuntimeError("下载内容 SHA-256 校验失败（源可能被污染），已清除分片，可重试或换网络环境")
    else:
        logger.warning("toolchain %s 未预置 SHA-256，跳过完整性校验", kind)
    shutil.move(str(partial), str(dest))


def _zip_member_unsafe(name: str) -> bool:
    n = name.replace("\\", "/")
    parts = Path(n).parts
    return n.startswith("/") or ".." in parts or (len(n) > 1 and n[1] == ":")


def _extract_zip_safe(archive: Path, dest: Path, kind: Component) -> None:
    """解压 zip，带 zip-slip 防护（跳过绝对路径 / .. 成员）+ 进度。"""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        infos = [m for m in z.infolist() if not _zip_member_unsafe(m.filename)]
        total = max(1, len(infos))
        for i, m in enumerate(infos):
            target = dest / m.filename.replace("\\", "/")
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as srcf, open(target, "wb") as out:
                    shutil.copyfileobj(srcf, out)
            if i % 20 == 0 or i == total - 1:
                pct = 90.0 + 8.0 * (i + 1) / total
                _update(kind, state="extracting", percent=round(pct, 1),
                        message=f"解压中 {i + 1} / {total} 项…")


def _extract_7z(archive: Path, stage: Path, kind: Component) -> None:
    """py7zr 解压 + 进度：py7zr 无解压回调，解压跑子线程，主线程数 stage 已落盘
    条目推算百分比（只读目录名，不触碰压缩流）。"""
    try:
        import py7zr
    except ImportError as e:
        raise RuntimeError("缺少 py7zr 依赖，无法解压 7z 包") from e
    with py7zr.SevenZipFile(archive, mode="r") as z:
        total = max(1, len(z.list()))
        err: list[BaseException] = []

        def work() -> None:
            try:
                z.extractall(stage)
            except BaseException as e:  # noqa: BLE001
                err.append(e)

        th = threading.Thread(target=work, daemon=True, name="tc-extract")
        th.start()
        while th.is_alive():
            th.join(timeout=1.0)
            done = sum(1 for _ in stage.rglob("*")) if stage.exists() else 0
            pct = 90.0 + 8.0 * min(done / total, 1.0)
            _update(kind, state="extracting", percent=round(pct, 1),
                    message=f"解压中 {done} / {total} 项…")
        if err:
            raise err[0]


def _locate_payload(stage: Path, kind: Component) -> Path:
    """解压后定位要落位的目录：cpp 找含 bin/g++.exe 的发行根，python 就是解压根。"""
    if kind == "cpp":
        if (stage / "mingw64" / "bin" / f"g++{_EXE}").exists():
            return stage / "mingw64"
        for child in stage.iterdir():
            if child.is_dir() and (child / "bin" / f"g++{_EXE}").exists():
                return child
        raise RuntimeError("压缩包内未找到 g++（发行布局变化？）")
    if (stage / f"python{_EXE}").exists():
        return stage
    for child in stage.iterdir():
        if child.is_dir() and (child / f"python{_EXE}").exists():
            return child
    raise RuntimeError("压缩包内未找到 python.exe")


def _install_worker(kind: Component) -> None:
    root = toolchains_root()
    workdir = Path(tempfile.mkdtemp(prefix=f"learnflow-tc-{kind}-", dir=root))
    dest = root / ("mingw64" if kind == "cpp" else "python")
    try:
        archive = workdir / ("toolchain.7z" if kind == "cpp" else "toolchain.zip")
        cache = _archive_cache_path(kind)
        if _cache_valid(cache, kind):
            # 本地留档的安装包（上次下载已过校验）：直接复用，不重新下载
            _update(kind, state="downloading", percent=90.0, message="命中本地缓存的安装包，跳过下载")
            try:
                os.link(cache, archive)  # 同卷硬链接：瞬时且零空间
            except OSError:
                shutil.copyfile(cache, archive)
        else:
            url = _download_first_available(_candidate_urls(kind), archive, kind)
            logger.info("toolchain %s downloaded from %s", kind, httpx.URL(url).host)
            try:  # 留档：重装/重试不再重新下载（版本 bump 后由 _cleanup_stale_archives 淘汰）
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(archive, cache)
            except OSError:
                logger.warning("安装包留档失败（不影响本次安装）：%s", cache)

        _update(kind, state="extracting", percent=90.0, message="解压准备中…")
        stage = workdir / "stage"
        if archive.suffix == ".7z":
            _extract_7z(archive, stage, kind)
        else:
            _extract_zip_safe(archive, stage, kind)

        src = _locate_payload(stage, kind)
        if dest.exists():
            _force_rmtree(dest)
        try:
            _fs_retry(lambda: os.rename(src, dest))  # 同卷改名：原子且瞬时
        except OSError:
            # 改名被锁（杀软持有句柄）时退化为复制：读不受锁影响，落位即算装好，
            # 源目录残留只降级为警告（下次安装前 _cleanup_stale_workdirs 会清）
            shutil.copytree(src, dest, dirs_exist_ok=True)
            try:
                _fs_retry(lambda: shutil.rmtree(src))
            except PermissionError:
                logger.warning("toolchain 临时目录清理失败（不影响安装结果）：%s", src)

        if kind == "cpp":
            version = _probe_version_steady([str(dest / "bin" / f"g++{_EXE}"), "--version"])
            if not version:
                raise RuntimeError("安装后 g++ 无法运行（可能缺 VC 运行库或被杀软拦截）")
            _update(kind, state="done", percent=100.0, message=f"安装完成：{version}")
        else:
            version = _probe_version_steady([str(dest / f"python{_EXE}"), "-I", "--version"])
            _update(kind, state="done", percent=100.0, message=f"安装完成：{version or 'Python'}")
        logger.info("toolchain %s installed at %s", kind, dest)
    except Exception as e:  # noqa: BLE001
        logger.exception("toolchain install failed: %s", kind)
        _update(kind, state="error", error=str(e), message=f"安装失败：{e}")
    finally:
        try:
            _force_rmtree(workdir)
        except Exception:  # noqa: BLE001
            pass
