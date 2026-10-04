"""系统级服务：局域网访问令牌 + 数据目录备份/恢复（本地优先的数据资产保障）。"""
import logging
import secrets
import shutil
import socket
import zipfile
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

RESTORE_FLAG = ".restore-pending"


# ---------- 访问令牌 ----------

_TOKEN_CACHE: tuple[Path, float, str] | None = None


def token_path() -> Path:
    return settings.data_dir / "access_token.txt"


def get_access_token() -> str:
    """读取（或首次生成）访问令牌：非回环来源访问 API 时必须携带。带 mtime 缓存。"""
    global _TOKEN_CACHE
    p = token_path()
    if p.exists():
        m = p.stat().st_mtime
        if _TOKEN_CACHE is not None and _TOKEN_CACHE[0] == p and _TOKEN_CACHE[1] == m:
            return _TOKEN_CACHE[2]
        token = p.read_text(encoding="utf-8").strip()
        _TOKEN_CACHE = (p, m, token)
        return token
    token = secrets.token_urlsafe(16)
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(token, encoding="utf-8")
    except OSError:
        logger.warning("访问令牌写入失败，本次使用临时令牌")
    _TOKEN_CACHE = (p, p.stat().st_mtime, token)
    return token


def rotate_access_token() -> str:
    global _TOKEN_CACHE
    token = secrets.token_urlsafe(16)
    token_path().write_text(token, encoding="utf-8")
    _TOKEN_CACHE = (token_path(), token_path().stat().st_mtime, token)
    return token


def lan_access_path() -> Path:
    return settings.data_dir / "lan_access_enabled.txt"


def is_lan_access_enabled() -> bool:
    """是否允许局域网设备访问，默认开启（True）。"""
    p = lan_access_path()
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip() != "0"
        except OSError:
            return True
    return True


def set_lan_access_enabled(enabled: bool) -> bool:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        lan_access_path().write_text("1" if enabled else "0", encoding="utf-8")
    except OSError:
        logger.warning("局域网开关写入失败")
    return enabled


def lan_urls() -> list[str]:
    """本机局域网地址（供平板访问提示）。"""
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return [f"http://{ip}:{settings.port}" for ip in sorted(ips)]


# ---------- 备份 / 恢复 ----------

def backups_dir() -> Path:
    d = settings.data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup() -> Path:
    """打包数据目录核心资产（app.db + courses/）到 backups/。返回 zip 路径。"""
    from app.core.db import engine

    dest = backups_dir() / f"backup-{utcnow_compact()}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        # 写库前合并 WAL，保证 app.db 单文件完整
        engine.sync_engine.dispose()
        import sqlite3

        conn = sqlite3.connect(settings.db_path)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        if settings.db_path.exists():
            z.write(settings.db_path, "app.db")
        courses = settings.courses_dir
        if courses.exists():
            for f in courses.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(settings.data_dir).as_posix())
    return dest


def list_backups() -> list[dict]:
    out = []
    for f in sorted(backups_dir().glob("backup-*.zip"), reverse=True):
        out.append({"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    return out


def request_restore(name: str) -> None:
    """标记待恢复：重启应用后生效（live 库不能热替换）。"""
    safe = Path(name).name
    if not (backups_dir() / safe).exists():
        raise LookupError("备份不存在")
    (settings.data_dir / RESTORE_FLAG).write_text(safe, encoding="utf-8")


def delete_backup(name: str) -> None:
    safe = Path(name).name
    p = backups_dir() / safe
    if p.exists():
        p.unlink()


def apply_pending_restore() -> None:
    """启动早于 init_db 调用：把标记的备份覆盖回数据目录。"""
    flag = settings.data_dir / RESTORE_FLAG
    if not flag.exists():
        return
    name = flag.read_text(encoding="utf-8").strip()
    zpath = backups_dir() / name
    logger.info("应用启动恢复备份：%s", name)
    settings.db_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
    if settings.courses_dir.exists():
        shutil.rmtree(settings.courses_dir, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(settings.data_dir)
    flag.unlink(missing_ok=True)
    logger.info("备份恢复完成")


def utcnow_compact() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S")
