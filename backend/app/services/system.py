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
        # 写失败时不要回填 mtime 缓存：p.stat() 可能同样抛错（目录不可写），
        # 且缓存了错误 mtime 会让后续请求反复踩同一失败路径
        logger.warning("访问令牌写入失败，本次使用临时令牌")
        return token
    try:
        _TOKEN_CACHE = (p, p.stat().st_mtime, token)
    except OSError:
        pass
    return token


def rotate_access_token() -> str:
    global _TOKEN_CACHE
    token = secrets.token_urlsafe(16)
    token_path().write_text(token, encoding="utf-8")
    _TOKEN_CACHE = (token_path(), token_path().stat().st_mtime, token)
    return token


def lan_access_path() -> Path:
    return settings.data_dir / "lan_access_enabled.txt"


_LAN_CACHE: tuple[float, bool] | None = None


def is_lan_access_enabled() -> bool:
    """是否允许局域网设备访问，默认关闭（False）。带 mtime 缓存：
    中间件对每个非回环请求都会调用，不能每次都读磁盘。"""
    global _LAN_CACHE
    p = lan_access_path()
    try:
        m = p.stat().st_mtime
    except OSError:
        _LAN_CACHE = None
        return False
    if _LAN_CACHE is not None and _LAN_CACHE[0] == m:
        return _LAN_CACHE[1]
    try:
        enabled = p.read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return False
    _LAN_CACHE = (m, enabled)
    return enabled


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
    """打包数据目录核心资产（app.db + courses/ + banks/ + 镜像配置）到 backups/。返回 zip 路径。"""
    import time

    from app.core.db import engine

    # 后台仍在生成章节时提示（不阻断）：DB 与 courses/ 文件可能逻辑不一致
    try:
        from app.services.generation import pipeline as _pipeline

        if _pipeline.any_running():
            logger.warning("备份时仍有课程生成任务在运行，备份可能包含半生成章节")
    except Exception:  # noqa: BLE001
        pass

    dest = backups_dir() / f"backup-{utcnow_compact()}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        # 写库前合并 WAL，保证 app.db 单文件完整。
        # TRUNCATE 在有并发读时可能 busy（返回 busy=1）——重试几次，
        # 仍 busy 则把 -wal 一并打包，恢复时由 SQLite 自动重放
        engine.sync_engine.dispose()
        import sqlite3

        wal_busy = False
        conn = sqlite3.connect(settings.db_path)
        try:
            for _ in range(4):
                row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if row and row[0] == 0:  # busy 标志为 0 = 成功
                    break
                time.sleep(0.3)
            else:
                wal_busy = True
                logger.warning("WAL checkpoint 未能完全合并（busy），备份将附带 -wal 文件")
        finally:
            conn.close()
        if settings.db_path.exists():
            z.write(settings.db_path, "app.db")
        if wal_busy:
            wal = Path(str(settings.db_path) + "-wal")
            if wal.exists():
                z.write(wal, "app.db-wal")
        for sub in ("courses", "banks"):
            d = settings.data_dir / sub
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file():
                        z.write(f, f.relative_to(settings.data_dir).as_posix())
        # 自定义镜像源与手动锁定选择一并备份
        for name in ("custom_mirrors.json", "mirror_selection.json"):
            f = settings.data_dir / name
            if f.exists():
                z.write(f, name)
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


def _validate_backup_zip(zpath: Path) -> zipfile.ZipFile:
    """恢复前校验备份完整性：必须是可读 zip 且包含 app.db，杜绝先删库后解压失败导致的数据丢失。

    注意 testzip() 返回首个 CRC 损坏条目名（None = 全部完好），必须检查返回值——
    只调用不检查等于没校验。
    """
    try:
        z = zipfile.ZipFile(zpath)
        bad = z.testzip()
    except Exception as e:
        raise ValueError(f"备份文件损坏或不可读，已取消恢复：{e}") from e
    if bad is not None:
        z.close()
        raise ValueError(f"备份条目 CRC 校验失败：{bad}，已取消恢复")
    names = z.namelist()
    if "app.db" not in names:
        z.close()
        raise ValueError("备份缺少 app.db，已取消恢复")
    # zip-slip 防护：用 Path.is_relative_to 判定（前缀字符串匹配会放过同级前缀目录）
    data_root = settings.data_dir.resolve()
    for n in names:
        target = (settings.data_dir / n).resolve()
        if not target.is_relative_to(data_root):
            z.close()
            raise ValueError(f"备份包含非法路径条目：{n}")
    return z


def apply_pending_restore() -> None:
    """启动早于 init_db 调用：把标记的备份覆盖回数据目录。

    安全顺序：完整校验（CRC + app.db + 路径穿越）→ 解压到暂存目录 → 删旧数据 → 原子搬入。
    校验或解压失败时旧数据原封不动；任何失败都不留 .restore-pending，避免后端每次启动崩溃死循环。
    """
    flag = settings.data_dir / RESTORE_FLAG
    if not flag.exists():
        return
    name = flag.read_text(encoding="utf-8").strip()
    zpath = backups_dir() / name
    logger.info("应用启动恢复备份：%s", name)

    def _abort(reason: str) -> None:
        logger.error("%s，取消恢复：%s", reason, zpath)
        flag.unlink(missing_ok=True)

    if not zpath.exists():
        _abort("备份文件不存在")
        return
    try:
        z = _validate_backup_zip(zpath)
    except ValueError as e:
        _abort(str(e))
        return

    staging = settings.data_dir / ".restore-staging"
    try:
        # 先完整解压到暂存目录——磁盘满/中途失败时旧数据仍完好
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        z.extractall(staging)
        z.close()

        # 旧库先挪进暂存目录而不是直接删：move 阶段中途失败时，
        # 旧数据 + 完整备份都还在，可手工恢复（而不是两头全丢）
        rescued = staging / "_rescued_old"
        rescued.mkdir(exist_ok=True)
        for victim in (
            settings.db_path,
            Path(str(settings.db_path) + "-wal"),
            Path(str(settings.db_path) + "-shm"),
            settings.data_dir / "courses",
            settings.data_dir / "banks",
        ):
            if victim.exists():
                shutil.move(str(victim), str(rescued / victim.name))

        for entry in list(staging.iterdir()):
            if entry.name == "_rescued_old":
                continue
            target = settings.data_dir / entry.name
            shutil.move(str(entry), str(target))
        shutil.rmtree(staging, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        # 关键：失败时保留暂存目录（内含完整备份 + 被救回的旧数据），绝不删除
        logger.exception(
            "备份恢复失败。旧数据与备份已保留在 %s（内含 _rescued_old/），可手工恢复",
            staging,
        )
        _abort(f"恢复执行失败：{e}；数据已保留在 {staging}")
        return
    flag.unlink(missing_ok=True)
    logger.info("备份恢复完成")


def utcnow_compact() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S")
