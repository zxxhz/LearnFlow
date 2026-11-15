"""同步墓碑族回归（v0.5.8 全量体检修复验证）：真实双端 HTTP 链路。

覆盖修复项：
- P0-1   设备 pull 墓碑段对「本地仍持有子题/作答的题库」级联删除，不再 FK IntegrityError
- P1-3   课程/文档/划线删除记墓碑：云端真删除 + pull 侧落地删除（不再按缺即建复活）
- P2-2   收到的 bank_question 墓碑落本地 SyncTombstone（随 push 传播，不再拉锯）
- P2-3   服务端 push upsert 校验持久化墓碑全集（旧快照不得复活已删条目）
- P2-8   服务端按墓碑真删时同步清理 bank_attempts（孤儿作答不再虚增统计）

拓扑：驱动进程内起真实服务端（uvicorn 线程，独立 DATA_DIR）；
三个「设备」各用独立 APP_DATA_DIR 子进程（seed-A / delete-A / seed-old-C + pull-C）。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# server/ 包位于项目根，app/ 包位于 backend/（脚本直跑时两者都不在默认 sys.path）
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
PY = str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe")
SELF = str(Path(__file__).resolve())

COURSE_ID = "crs_treg01"
DOC_ID = "doc_treg01"
BANK_ID = "bank_treg01"
QUESTION_IDS = ["bq_treg01", "bq_treg02"]
ATTEMPT_IDS = ["att_treg01", "att_treg02"]
EXPECT_TOMBSTONES = {BANK_ID, *QUESTION_IDS, COURSE_ID, DOC_ID}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pull(server: str) -> dict:
    with urllib.request.urlopen(f"{server}/api/relay/sync/pull", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run_step(step: str, app_data_dir: str, server: str) -> None:
    env = {**os.environ, "APP_DATA_DIR": app_data_dir, "TREG_SERVER": server}
    proc = subprocess.run(
        [PY, SELF, step],
        cwd=str(ROOT / "backend"),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        print(proc.stdout[-4000:])
        print(proc.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"step {step} failed (exit {proc.returncode})")
    for line in proc.stdout.splitlines():
        if line.startswith("STEP_RESULT "):
            print(f"  [{step}] {line[len('STEP_RESULT '):]}")


# ---------------------------------------------------------------- 设备步骤 ----
async def _backend_session():
    """设备侧：初始化本地库并返回会话工厂（APP_DATA_DIR 由驱动注入）。须在事件循环内调用。"""
    from app.core.db import async_session_factory, init_db

    await init_db()
    return async_session_factory


def step_seed() -> dict:
    """设备 A：造课程+文档+题库（含题目与作答）并推云。"""
    import asyncio

    from app.models import BankAttempt, BankQuestion, Course, Document, QuestionBank
    from app.models.base import utcnow_iso
    from app.services.relay.sync import collect_local_sync_payload, push_local_data_to_server

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _backend_session()
        async with factory() as db:
            db.add(Course(id=COURSE_ID, title="回归课程", topic="测试", status="ready"))
            db.add(
                Document(
                    id=DOC_ID,
                    course_id=COURSE_ID,
                    chapter_index=1,
                    title="回归章节",
                    file_path=f"courses/{COURSE_ID}/{DOC_ID}/current.md",
                    status="done",
                )
            )
            db.add(QuestionBank(id=BANK_ID, name="回归题库", question_count=len(QUESTION_IDS)))
            # 分阶段 flush（对齐 create_bank 惯例）：本环境 SQLAlchemy 2.1 一次性跨表
            # flush 的发射顺序不保证父行先落，FK 立即约束会炸
            await db.flush()
            for i, qid in enumerate(QUESTION_IDS):
                db.add(
                    BankQuestion(
                        id=qid,
                        bank_id=BANK_ID,
                        seq=i + 1,
                        qtype="single",
                        title=f"回归题目 {i}",
                        options='["A","B","C","D","","","",""]',
                        answer="A",
                    )
                )
            await db.flush()
            for i, aid in enumerate(ATTEMPT_IDS):
                db.add(
                    BankAttempt(
                        id=aid,
                        bank_id=BANK_ID,
                        question_id=QUESTION_IDS[i % len(QUESTION_IDS)],
                        content="B",
                        passed=False,
                    )
                )
            # 旧口径行：updated_at 留空，模拟 0.5.8 前存量数据
            await db.commit()
        payload = await collect_local_sync_payload()
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res
        return {"banks": len(payload["banks"]), "questions": len(payload["bank_questions"])}

    return asyncio.run(main())


def step_delete() -> dict:
    """设备 A：走真实 DELETE 端点删课程与题库（触发修复后的墓碑记录），再推云。"""
    import asyncio

    from app.core.db import async_session_factory

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        await _backend_session()
        # _AccessGuard（v0.5.8）：TestClient 的 client addr 非 loopback（"testclient"），
        # 需要打开局域网访问文件标志；Host 用回环地址过 Host 严格性校验
        import app.services.system as _sys
        from app.services.system import get_access_token, lan_access_path

        lan_access_path().write_text("1", encoding="utf-8")
        _sys._LAN_CACHE = None

        from fastapi.testclient import TestClient

        from app.main import app

        token = get_access_token()
        with TestClient(
            app,
            base_url="http://127.0.0.1:8420",
            headers={"x-access-token": token},
        ) as client:
            r1 = client.delete(f"/api/courses/{COURSE_ID}")
            assert r1.status_code == 200, r1.text
            r2 = client.delete(f"/api/banks/{BANK_ID}")
            assert r2.status_code == 200, r2.text

        from app.services.relay.sync import collect_local_sync_payload, push_local_data_to_server

        payload = await collect_local_sync_payload()
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res
        kinds = sorted({t["kind"] for t in payload["tombstones"]})
        return {
            "local_banks_left": len(payload["banks"]),
            "tombstone_kinds": kinds,
            "tombstone_ids": sorted(t["object_id"] for t in payload["tombstones"]),
        }

    return asyncio.run(main())


def step_seed_old() -> dict:
    """设备 C（模拟未同步删除的旧设备）：原样重建同 id 旧快照并推云（不带墓碑）。"""
    import asyncio

    from app.models import BankAttempt, BankQuestion, Course, QuestionBank
    from app.services.relay.sync import collect_local_sync_payload, push_local_data_to_server

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _backend_session()
        async with factory() as db:
            db.add(Course(id=COURSE_ID, title="旧快照课程", topic="测试", status="ready"))
            db.add(QuestionBank(id=BANK_ID, name="旧快照题库", question_count=len(QUESTION_IDS)))
            await db.flush()
            for i, qid in enumerate(QUESTION_IDS):
                db.add(
                    BankQuestion(
                        id=qid,
                        bank_id=BANK_ID,
                        seq=i + 1,
                        qtype="single",
                        title=f"旧快照题目 {i}",
                        options='["A","B","C","D","","","",""]',
                        answer="A",
                    )
                )
            await db.flush()
            for i, aid in enumerate(ATTEMPT_IDS):
                db.add(
                    BankAttempt(
                        id=aid,
                        bank_id=BANK_ID,
                        question_id=QUESTION_IDS[i % len(QUESTION_IDS)],
                        content="B",
                        passed=False,
                    )
                )
            await db.commit()
        payload = await collect_local_sync_payload()
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res
        return {"pushed_banks": len(payload["banks"])}

    return asyncio.run(main())


def step_pull() -> dict:
    """设备 C：pull 云端（含墓碑）——P0 主场景：本地仍持有题库+子行，级联删除不崩。"""
    import asyncio

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _backend_session()
        res = await _pull_and_assert(factory, server)
        # 二次 pull：幂等复跑不崩（服务端墓碑只增不删）
        await _pull_and_assert(factory, server)
        return res

    return asyncio.run(main())


async def _pull_and_assert(factory, server: str) -> dict:
    from sqlalchemy import select

    from app.models import BankQuestion, BankAttempt, Course, Document, QuestionBank, SyncTombstone
    from app.services.relay.sync import pull_cloud_data_to_local

    res = await pull_cloud_data_to_local(server_url=server)
    assert res.get("ok"), res
    async with factory() as db:
        banks = (await db.scalars(select(QuestionBank))).all()
        questions = (await db.scalars(select(BankQuestion))).all()
        attempts = (await db.scalars(select(BankAttempt))).all()
        courses = (await db.scalars(select(Course))).all()
        docs = (await db.scalars(select(Document))).all()
        tombs = (await db.scalars(select(SyncTombstone.object_id))).all()
    assert not banks, f"题库未被墓碑删除: {[b.id for b in banks]}"
    assert not questions, f"题目未被级联删除: {[q.id for q in questions]}"
    assert not attempts, f"作答未被级联删除: {[a.id for a in attempts]}"
    assert not courses, f"课程未被墓碑删除: {[c.id for c in courses]}"
    assert not docs, f"文档未被墓碑删除: {[d.id for d in docs]}"
    missing = EXPECT_TOMBSTONES - set(tombs)
    assert not missing, f"收到的墓碑未落本地 SyncTombstone: 缺 {sorted(missing)}"
    return {
        "local_left": {"banks": 0, "questions": 0, "attempts": 0, "courses": 0, "docs": 0},
        "local_tombstones": len(tombs),
    }


# ------------------------------------------------------------------ 驱动 ----
def main_driver() -> None:
    data_root = Path(tempfile.mkdtemp(prefix="treg_"))
    port = _free_port()
    server = f"http://127.0.0.1:{port}"
    os.environ["DATA_DIR"] = str(data_root / "server-data")
    os.environ["RELAY_AUTH_REQUIRED"] = "false"

    import uvicorn

    from server.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{server}/health", timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("server failed to start")

    print("== 1. 设备 A seed（课程/文档/题库/题目/作答 → push）==")
    _run_step("seed", str(data_root / "deviceA"), server)
    pull = _pull(server)
    assert len(pull["banks"]) == 1 and len(pull["question_banks"]) == 1, "seed push 未生效"
    assert len(pull["bank_questions"]) == 2 and len(pull["bank_attempts"]) == 2, "seed 数据不全"
    assert len(pull["courses"]) == 1 and len(pull["documents"]) == 1

    print("== 2. 设备 A delete（真实 DELETE 端点 → 墓碑 → push）==")
    _run_step("delete", str(data_root / "deviceA"), server)
    pull = _pull(server)
    assert not pull["banks"] and not pull["courses"] and not pull["documents"], "云端未真删（P1-3）"
    assert not pull["bank_questions"], "云端题目未级联删除"
    assert not pull["bank_attempts"], "云端作答未级联删除（P2-8）"
    cloud_tombs = {t["object_id"] for t in pull["tombstones"]}
    missing = EXPECT_TOMBSTONES - cloud_tombs
    assert not missing, f"云端墓碑不全: 缺 {sorted(missing)}（P1-3）"

    print("== 3. 设备 C 持旧快照 push（无墓碑）——服务端须拒绝复活（P2-3）==")
    _run_step("seed-old", str(data_root / "deviceC"), server)
    pull = _pull(server)
    assert not pull["banks"], "旧快照把已删题库复活了！（P2-3 失守）"
    assert not pull["bank_questions"] and not pull["bank_attempts"], "旧快照复活了题目/作答（P2-3 失守）"
    assert not pull["courses"], "旧快照把已删课程复活了！（P2-3 失守）"

    print("== 4. 设备 C pull（本地仍持有题库+子行）——P0 主场景级联删除不 FK 崩溃 ==")
    _run_step("pull", str(data_root / "deviceC"), server)

    print("== 5. 复活防线终验：C pull 后再 push 全量快照，云端仍无复活 ==")
    _run_step("seed-old", str(data_root / "deviceC"), server)
    pull = _pull(server)
    assert not pull["banks"] and not pull["courses"], "终验：旧快照复活（拉锯未闭环）"

    print("\n✅ 墓碑族回归全部通过：P0-1 / P1-3 / P2-2 / P2-3 / P2-8")
    srv.should_exit = True
    thread.join(timeout=10)


STEPS = {"seed": step_seed, "delete": step_delete, "seed-old": step_seed_old, "pull": step_pull}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in STEPS:
        result = STEPS[sys.argv[1]]()
        print("STEP_RESULT", json.dumps(result, ensure_ascii=False))
    else:
        main_driver()
