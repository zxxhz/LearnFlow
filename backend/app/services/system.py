"""系统级服务：局域网访问令牌 + 数据目录备份/恢复（本地优先的数据资产保障）。"""
import json
import logging
import os
import secrets
import shutil
import socket
import zipfile
from pathlib import Path

from app.core.config import APP_VERSION, settings

logger = logging.getLogger(__name__)

RESTORE_FLAG = ".restore-pending"


# ---------- 访问令牌 ----------

_TOKEN_CACHE: tuple[Path, float, str] | None = None


def token_path() -> Path:
    return settings.data_dir / "access_token.txt"


def _write_token_atomic(p: Path, token: str) -> None:
    """tmp + os.replace 原子写令牌：进程崩溃/断电不会留下空或截断的令牌文件
    （截断的令牌会让局域网访问全部 401 且难以排查）。"""
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
        _write_token_atomic(p, token)
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
    """轮换访问令牌。写失败（目录不可写/磁盘满）时给出可行动的错误信息，
    而非让 API 层吐出裸 OSError 的 500。"""
    global _TOKEN_CACHE
    token = secrets.token_urlsafe(16)
    p = token_path()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _write_token_atomic(p, token)
        mtime = p.stat().st_mtime
    except OSError as e:
        logger.warning("访问令牌轮换写入失败：%s", e)
        raise RuntimeError("令牌写入失败：请检查数据目录写入权限与磁盘剩余空间") from e
    _TOKEN_CACHE = (p, mtime, token)
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
    global _LAN_CACHE
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        p = lan_access_path()
        p.write_text("1" if enabled else "0", encoding="utf-8")
        # Windows 时钟粒度约 15.6ms：连续两次开关落在同一刻度时 mtime 不变，
        # is_lan_access_enabled 会按旧缓存返回陈旧状态——写成功后直接刷新缓存
        _LAN_CACHE = (p.stat().st_mtime, enabled)
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

BACKUP_KEEP = 10  # 备份保留份数，超出自动淘汰最旧


def backups_dir() -> Path:
    d = settings.data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _vacuum_snapshot(snapshot: Path) -> bool:
    """用 SQLite VACUUM INTO 产出 app.db 的一致性快照（Python 3.11+ 自带 SQLite ≥ 3.27）。

    直接拷贝 db 文件可能撞上写入中的撕裂页；VACUUM INTO 在读事务里产出
    紧凑完整副本。失败（库损坏/磁盘满/老 SQLite）返回 False，调用方回退旧路径。
    """
    import sqlite3

    try:
        conn = sqlite3.connect(settings.db_path)
        try:
            conn.execute("VACUUM INTO ?", (str(snapshot),))
        finally:
            conn.close()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("VACUUM INTO 一致性快照失败，回退直接打包 db 文件：%s", e)
        return False


def _rotate_backups(keep: int = BACKUP_KEEP) -> None:
    """按保留份数轮转：仅删最旧的 backup-*.zip（文件名含毫秒时间戳，字典序=时间序）。
    删除失败仅记日志，不影响本次备份结果。"""
    try:
        backups = sorted(backups_dir().glob("backup-*.zip"))
        for old in backups[:-keep] if len(backups) > keep else []:
            try:
                old.unlink()
                logger.info("已清理超出保留份数的旧备份：%s", old.name)
            except OSError as e:
                logger.warning("旧备份删除失败（不影响本次备份）：%s: %s", old.name, e)
    except Exception as e:  # noqa: BLE001
        logger.warning("备份轮转检查失败：%s", e)


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
    # VACUUM INTO 要求目标文件不存在，先清残留（上次崩溃可能留下）
    snapshot = settings.data_dir / f".backup-snapshot-{os.getpid()}.db"
    snapshot.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            # 不 dispose 共享连接池（v0.5.2 体检 P3）：VACUUM INTO 用独立连接即可拿到
            # 一致快照；dispose 清掉空闲连接会让备份瞬间的并发请求全部重建连接抖动
            import sqlite3

            consistent = settings.db_path.exists() and _vacuum_snapshot(snapshot)
            wal_busy = False
            if not consistent:
                # 回退旧路径：写库前合并 WAL，保证 app.db 单文件完整。
                # TRUNCATE 在有并发读时可能 busy（返回 busy=1）——重试几次，
                # 仍 busy 则把 -wal 一并打包，恢复时由 SQLite 自动重放
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
                if consistent:
                    z.write(snapshot, "app.db")
                else:
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
            # 备份元数据：恢复时用于告警版本不匹配（不阻断）
            from datetime import datetime, timezone

            z.writestr(
                "meta.json",
                json.dumps(
                    {
                        "app_version": APP_VERSION,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    finally:
        snapshot.unlink(missing_ok=True)
    _rotate_backups()
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
        # 先完整解压到暂存目录——磁盘满/中途失败时旧数据仍完好。
        # v0.5.8 体检 P2：解压总量上限 2GB——zip-slip 已有防护，但高压缩比
        # 异常备份可在启动时写满磁盘（本地信任边界内，属纵深防御）
        _RESTORE_MAX_UNCOMPRESSED = 2 * 1024**3
        total_unc = sum(m.file_size for m in z.infolist())
        if total_unc > _RESTORE_MAX_UNCOMPRESSED:
            _abort(f"备份解压体积超上限（{total_unc // (1024**2)}MB > 2048MB），疑似异常备份，已中止")
            return
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        z.extractall(staging)
        z.close()

        # 备份元数据：记录来源版本，与当前不一致仅告警不阻断（允许跨版本恢复）
        meta_file = staging / "meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                b_ver = str(meta.get("app_version") or "?")
                created = str(meta.get("created_at") or "?")
                if b_ver != APP_VERSION:
                    logger.warning(
                        "备份版本 %s（创建于 %s）与当前版本 %s 不一致，继续恢复",
                        b_ver, created, APP_VERSION,
                    )
                else:
                    logger.info("备份版本 %s，创建于 %s", b_ver, created)
            except Exception as e:  # noqa: BLE001
                logger.warning("读取备份 meta.json 失败（忽略）：%s", e)

        # 旧库先挪进暂存目录而不是直接删：move 阶段中途失败时，
        # 旧数据 + 完整备份都还在，可手工恢复（而不是两头全丢）。
        # 镜像配置一并入列：备份里没有时按"恢复到备份时点"语义清掉，
        # 有时随后由解压产物覆盖
        rescued = staging / "_rescued_old"
        rescued.mkdir(exist_ok=True)
        for victim in (
            settings.db_path,
            Path(str(settings.db_path) + "-wal"),
            Path(str(settings.db_path) + "-shm"),
            settings.data_dir / "courses",
            settings.data_dir / "banks",
            settings.data_dir / "custom_mirrors.json",
            settings.data_dir / "mirror_selection.json",
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
    """UTC 紧凑时间戳（精确到毫秒）：本地时间会造成命名误导；毫秒避免同一秒
    内创建多个备份时文件名平局互相覆盖。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S") + f"-{now.microsecond // 1000:03d}"
