"""LearnFlow v0.5.9 修复批三场景运行时实证验证（真实服务链路）。

沿用 scripts/tombstone_regression.py 的全部坑位经验：
- 拓扑：驱动进程内起真实服务端（uvicorn 线程，独立 DATA_DIR）；
- 每个「设备」用独立 APP_DATA_DIR 子进程（app.core.config 在 import 时读环境变量）；
- 本地 TestClient：base_url 回环 + lan_access 标志文件 + 清 _LAN_CACHE + x-access-token；
- ORM 跨表同事务写入分阶段 flush（本机 SQLAlchemy 2.1 跨表 flush 发射顺序异常）；
- 临时数据目录建于 backend/ 下（treg2_ 前缀），结束时删除。

覆盖场景：
- 场景 1  题库整库替换 × (bank_id, seq) 立即唯一索引 ux_bank_questions_bank_seq：
          保留题相对换序是否必撞 IntegrityError（500 回滚）；顺序不变 / 删题保留不换序对照。
- 场景 2  P1-4 空 updated_at 回退：存量行（updated_at=''）push 后本地编辑/撤回，
          不 push 直接 pull（云端 '' 旧快照）不得覆盖本地较新状态；对照「云端较新正常合入」。
- 场景 3  P1-5 新者胜护栏：导图/课程/文档本地编辑（updated_at=T1）后 pull 云端旧快照，
          本地不得被回退；对照「push→pull 幂等」与「云端较新正常合入」。

用法：backend/.venv/Scripts/python.exe scripts/v059_runtime_verify.py   （无参 = 跑全部驱动）
"""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
PY = str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe")
SELF = str(Path(__file__).resolve())

# 场景 1 固定题目（题干唯一，保证对齐是 Level-1 内容指纹匹配、且换序后 matched 不歧义）
S1_ROWS = {
    "A": ("单选题", "场景1甲题", ["甲选项A", "甲选项B", "甲选项C", "甲选项D", "", "", "", ""], "A", "解析甲"),
    "B": ("单选题", "场景1乙题", ["乙选项A", "乙选项B", "乙选项C", "乙选项D", "", "", "", ""], "B", "解析乙"),
    "C": ("单选题", "场景1丙题", ["丙选项A", "丙选项B", "丙选项C", "丙选项D", "", "", "", ""], "C", "解析丙"),
}
S2_BANK = "bk_v59s2"
S2_Q = "q_v59s2"
S2_Q2 = "q_v59s2b"
S2_ATT = "att_v59s2"
S3_CRS = "crs_v59s3"
S3_DOC = "doc_v59s3"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pull(server: str) -> dict:
    with urllib.request.urlopen(f"{server}/api/relay/sync/pull", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run_step(step: str, app_data_dir: str, server: str) -> dict:
    """子进程跑步骤；返回 STEP_RESULT 解析结果（供驱动断言）。"""
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
    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("STEP_RESULT "):
            result = json.loads(line[len("STEP_RESULT "):])
        elif line.startswith("STEP_NOTE "):
            print(f"  [{step}] {line[len('STEP_NOTE '):]}")
    if result is None:
        raise SystemExit(f"step {step} 未输出 STEP_RESULT；stdout 尾部：{proc.stdout[-800:]}")
    return result


async def _init_db_session_factory():
    from app.core.db import async_session_factory, init_db

    await init_db()
    return async_session_factory


def _testclient_headers():
    """TestClient 直连本地端点的完整配方（对齐 tombstone_regression.step_delete）。"""
    import app.services.system as _sys
    from app.services.system import get_access_token, lan_access_path

    lan_access_path().write_text("1", encoding="utf-8")
    _sys._LAN_CACHE = None

    from fastapi.testclient import TestClient

    from app.main import app

    token = get_access_token()
    client = TestClient(
        app,
        base_url="http://127.0.0.1:8420",
        headers={"x-access-token": token},
    )
    return client


# ------------------------------------------------------------------ 工具 ----
def _build_xlsx(order: list[str]) -> bytes:
    """按 15 列布局构造题库表格：0 题型 | 1 题干 | 2-9 选项 | 10 答案 | 11 备用 | 12 解析 | 13 难度。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["题型", "题干", "A", "B", "C", "D", "E", "F", "G", "H", "正确答案", "备用", "解析", "难度"])
    for key in order:
        qtype, title, opts, answer, expl = S1_ROWS[key]
        ws.append([qtype, title, *opts, answer, "", expl, "简单"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _node_ids(root: dict) -> set[str]:
    ids: set[str] = set()

    def walk(n: dict) -> None:
        if not isinstance(n, dict):
            return
        if n.get("id"):
            ids.add(str(n["id"]))
        for c in n.get("children") or []:
            walk(c)

    walk(root)
    return ids


# ------------------------------------------------------- 场景 1（题库替换）----
def step_s1_setup() -> dict:
    """设备 A：真实 POST /api/banks/import 建 3 题库（A,B,C → seq 1,2,3）。"""
    import asyncio

    async def main() -> dict:
        factory = await _init_db_session_factory()
        client = _testclient_headers()
        with client:
            resp = client.post(
                "/api/banks/import",
                files={"file": ("bank.xlsx", _build_xlsx(["A", "B", "C"]), _XLSX_MIME)},
                data={"name": "场景1题库"},
            )
            assert resp.status_code == 200, f"import 失败 {resp.status_code}: {resp.text}"
            bank_id = resp.json()["id"]
        from sqlalchemy import select

        from app.models import BankQuestion

        async with factory() as db:
            qs = (
                await db.scalars(
                    select(BankQuestion).where(BankQuestion.bank_id == bank_id).order_by(BankQuestion.seq)
                )
            ).all()
        qid_by_title = {q.title: q.id for q in qs}
        return {
            "bank_id": bank_id,
            "qA": qid_by_title["场景1甲题"],
            "qB": qid_by_title["场景1乙题"],
            "qC": qid_by_title["场景1丙题"],
            "questions": [{"id": q.id, "seq": q.seq, "title": q.title} for q in qs],
        }

    return asyncio.run(main())


async def _s1_bank_id_from_env() -> str:
    await _init_db_session_factory()
    return json.loads(os.environ["V59_S1_SETUP"])["bank_id"]


def _s1_replace(order: list[str], bank_id: str, filename: str) -> tuple[int | None, str | None]:
    """POST /api/banks/{id}/replace；返回 (status_code | None, 异常类型+摘要 | None)。"""
    client = _testclient_headers()
    try:
        with client:
            resp = client.post(
                f"/api/banks/{bank_id}/replace",
                files={"file": (filename, _build_xlsx(order), _XLSX_MIME)},
            )
            return resp.status_code, None if resp.status_code == 200 else resp.text[:300]
    except Exception as e:  # noqa: BLE001  TestClient raise_server_exceptions=True：应用内未捕获异常直接抛出
        return None, f"{type(e).__name__}: {str(e)[:300]}"


async def _s1_db_snapshot(bank_id: str) -> dict:
    """库态快照（async：供各 s1 步骤的 async main 内 await；不可再 asyncio.run 套娃）。"""
    factory = await _init_db_session_factory()
    from sqlalchemy import select

    from app.models import BankQuestion, QuestionBank, SyncTombstone

    async with factory() as db:
        bank = await db.get(QuestionBank, bank_id)
        qs = (
            await db.scalars(
                select(BankQuestion).where(BankQuestion.bank_id == bank_id).order_by(BankQuestion.seq)
            )
        ).all()
        tombs = (
            await db.scalars(
                select(SyncTombstone.object_id).where(SyncTombstone.kind == "bank_question")
            )
        ).all()
    return {
        "question_count": bank.question_count,
        "source_file": bank.source_file,
        "questions": [{"id": q.id, "seq": q.seq, "title": q.title} for q in qs],
        "question_tombstones": sorted(tombs),
    }


def _short_qs(snapshot: dict) -> str:
    return "; ".join(f"{q['seq']}:{q['title'][-2:]}" for q in snapshot["questions"])


def step_s1_reorder() -> dict:
    """设备 A：换序替换（保留 B、A、C 且顺序换序）——预期撞 (bank_id, seq) 唯一索引。"""
    import asyncio

    async def main() -> dict:
        bank_id = await _s1_bank_id_from_env()
        before = await _s1_db_snapshot(bank_id)

        status, err = _s1_replace(["B", "A", "C"], bank_id, "replace_reorder.xlsx")
        after = await _s1_db_snapshot(bank_id)
        intact = (
            len(after["questions"]) == 3
            and [q["seq"] for q in after["questions"]] == [1, 2, 3]
            and [q["title"] for q in after["questions"]] == [q["title"] for q in before["questions"]]
            and after["question_count"] == 3
        )
        # v0.5.10：修复后换序替换应成功且库态按新顺序（乙,甲,丙）落位
        applied_correctly = (
            status == 200
            and len(after["questions"]) == 3
            and [q["seq"] for q in after["questions"]] == [1, 2, 3]
            and [q["title"][-2:] for q in after["questions"]] == ["乙题", "甲题", "丙题"]
            and after["question_count"] == 3
        )
        return {
            "bank_id": bank_id,
            "before_seq_title": _short_qs(before),
            "replace_status": status,
            "replace_error": err,
            "after_rollback_intact": intact,
            "applied_correctly": applied_correctly,
            "after_seq_title": _short_qs(after),
        }

    return asyncio.run(main())


def step_s1_control() -> dict:
    """设备 A：顺序不变替换（A,B,C）——对照，预期成功。"""
    import asyncio

    async def main() -> dict:
        bank_id = await _s1_bank_id_from_env()
        status, err = _s1_replace(["A", "B", "C"], bank_id, "replace_same_order.xlsx")
        snap = await _s1_db_snapshot(bank_id)
        return {"replace_status": status, "replace_error": err, "snapshot": snap, "seq_title": _short_qs(snap)}

    return asyncio.run(main())


def step_s1_delete() -> dict:
    """设备 A：删题 + 保留不换序（A,B）——对照，预期成功且 C 落墓碑。"""
    import asyncio

    async def main() -> dict:
        setup = json.loads(os.environ["V59_S1_SETUP"])
        bank_id = await _s1_bank_id_from_env()
        status, err = _s1_replace(["A", "B"], bank_id, "replace_delete_c.xlsx")
        snap = await _s1_db_snapshot(bank_id)
        c_gone = all(q["title"] != "场景1丙题" for q in snap["questions"])
        c_tomb = setup["qC"] in snap["question_tombstones"]
        return {
            "replace_status": status,
            "replace_error": err,
            "seq_title": _short_qs(snap),
            "removed_C_gone": c_gone,
            "C_tombstoned": c_tomb,
        }

    return asyncio.run(main())


# ------------------------------------------------- 场景 2（空 updated_at）----
def step_s2_seed() -> dict:
    """设备 B：造题库 + 题目（updated_at='' 存量行）+ 作答（updated_at=''）并 push；
    随后同进程内不编辑直接 pull（'' vs '' 合并对照：pull 合并路径正常运转）。"""
    import asyncio

    from app.services.relay.sync import (
        collect_local_sync_payload,
        pull_cloud_data_to_local,
        push_local_data_to_server,
    )

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.models import BankAttempt, BankQuestion, QuestionBank

        async with factory() as db:
            db.add(QuestionBank(id=S2_BANK, name="场景2题库", question_count=2))
            await db.flush()
            db.add(
                BankQuestion(
                    id=S2_Q,
                    bank_id=S2_BANK,
                    seq=1,
                    qtype="single",
                    title="场景2题目",
                    options='["甲","乙","丙","丁","","","",""]',
                    answer="A",
                    explanation="旧解析",
                    updated_at="",  # 模拟 0.5.8 前存量行
                )
            )
            db.add(
                BankQuestion(
                    id=S2_Q2,
                    bank_id=S2_BANK,
                    seq=2,
                    qtype="single",
                    title="场景2对照题",
                    options='["子","丑","寅","卯","","","",""]',
                    answer="A",
                    explanation="对照题旧解析",
                    updated_at="",
                )
            )
            await db.flush()
            db.add(
                BankAttempt(
                    id=S2_ATT,
                    bank_id=S2_BANK,
                    question_id=S2_Q,
                    content="B",
                    passed=False,
                    updated_at="",
                )
            )
            await db.commit()
            # 校验存量行确实空
            rows = (await db.scalars(select(BankQuestion).where(BankQuestion.bank_id == S2_BANK))).all()
            empty_ts = len(rows) == 2 and all(r.updated_at == "" for r in rows)

        payload = await collect_local_sync_payload()
        q_payload = next(q for q in payload["bank_questions"] if q["id"] == S2_Q)
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res

        # 对照（同进程内，本地行仍是 ''）：本地不编辑直接 pull → 云端 '' 快照正常合入
        res_pull = await pull_cloud_data_to_local(server_url=server)
        assert res_pull.get("ok"), res_pull
        async with factory() as db:
            q = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q))).one()
            q2 = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q2))).one()
            att = (await db.scalars(select(BankAttempt).where(BankAttempt.id == S2_ATT))).one()
        control_ok = (
            q.explanation == "旧解析"
            and q.answer == "A"
            and q2.explanation == "对照题旧解析"
            and att.content == "B"
            and not bool(att.is_revoked)
            and q.updated_at == ""
            and q2.updated_at == ""
            and att.updated_at == ""
        )
        return {
            "local_updated_at_empty": empty_ts,
            "pushed_question_updated_at": q_payload.get("updated_at"),
            "push_ok": True,
            "self_pull_merged_ok": control_ok,
            "self_pull_message": res_pull.get("message"),
        }

    return asyncio.run(main())


def step_s2_edit() -> dict:
    """设备 B：本地纠错改题（真实 update_question 服务路径）→ updated_at=T1；不 push。

    注：本子进程启动时 init_db 的 v0.5.9 迁移会把上一步遗留的 '' 行回填为 T_b
    （db.py「存量行 updated_at 一次性回填」），故以回填后的 T_b 为未编辑基线：
    纯解析编辑不得改动题目以外的行（对照题 q2 与作答 att 的 ts 必须保持 T_b）。
    """
    import asyncio

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.models import BankAttempt, BankQuestion
        from app.services import bank as bank_service

        async with factory() as db:
            q = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q))).one()
            q2 = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q2))).one()
            att = (await db.scalars(select(BankAttempt).where(BankAttempt.id == S2_ATT))).one()
            t_baseline_q = q.updated_at
            t_baseline_q2 = q2.updated_at
            t_baseline_att = att.updated_at

            q_after, _rec = await bank_service.update_question(db, q, explanation="本地新解析")
            t1 = q_after.updated_at
            att_after = att.updated_at
            q2_after = q2.updated_at
        assert t1, "update_question 未刷新 updated_at"
        return {
            "t1": t1,
            "explanation": q_after.explanation,
            "backfill_ts": t_baseline_q,
            "attempt_ts_before": t_baseline_att,
            "attempt_ts_after": att_after,
            "attempt_untouched_by_edit": t_baseline_att == att_after and att_after != "",
            "q2_ts_baseline": t_baseline_q2,
            "q2_ts_after_edit": q2_after,
        }

    return asyncio.run(main())


def step_s2_pull_edited() -> dict:
    """设备 B：不 push 直接 pull（云端仍是 '' 旧快照）→ 断言本地编辑保留。

    本子进程 init_db 不再有 '' 行（上步已回填），故无二次回填干扰；
    q2（对照题，ts=T_b > 云端 ''）期望被 pull 跳过：值与 ts 均不变。
    """
    import asyncio

    from app.services.relay.sync import pull_cloud_data_to_local

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.models import BankQuestion

        t1 = os.environ["V59_S2_T1"]
        t_baseline_q2 = os.environ["V59_S2_TB_Q2"]
        res = await pull_cloud_data_to_local(server_url=server)
        assert res.get("ok"), res
        async with factory() as db:
            q = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q))).one()
            q2 = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q2))).one()
        preserved = q.explanation == "本地新解析" and q.updated_at == t1 and q.answer == "A"
        untouched_ok = (
            q2.explanation == "对照题旧解析"
            and q2.updated_at == t_baseline_q2
            and q2.answer == "A"
        )
        return {
            "pull_ok": True,
            "pull_message": res.get("message"),
            "pull_counts": res.get("counts"),
            "local_edit_preserved": preserved,
            "q_explanation": q.explanation,
            "q_updated_at": q.updated_at,
            "expected_t1": t1,
            "untouched_row_intact": untouched_ok,
            "q2_state": f"exp={q2.explanation}/ts={q2.updated_at!r}/ans={q2.answer}",
            "q2_expected_ts": t_baseline_q2,
        }

    return asyncio.run(main())


def step_s2_revoke() -> dict:
    """设备 B：真实 revoke 端点撤回作答 → updated_at=T1r；不 push 直接 pull → 断言 is_revoked 仍为 1。"""
    import asyncio

    from app.services.relay.sync import pull_cloud_data_to_local

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.models import BankAttempt

        client = _testclient_headers()
        with client:
            resp = client.post(f"/api/banks/attempts/{S2_ATT}/revoke")
            assert resp.status_code == 200, f"revoke 失败 {resp.status_code}: {resp.text}"
        async with factory() as db:
            att = (await db.scalars(select(BankAttempt).where(BankAttempt.id == S2_ATT))).one()
            t1r = att.updated_at
            revoked_now = bool(att.is_revoked)
        assert t1r, "revoke 未刷新 updated_at"

        res = await pull_cloud_data_to_local(server_url=server)
        assert res.get("ok"), res
        async with factory() as db:
            att = (await db.scalars(select(BankAttempt).where(BankAttempt.id == S2_ATT))).one()
        preserved = bool(att.is_revoked) and att.updated_at == t1r and att.content == "B"
        return {
            "revoked_before_pull": revoked_now,
            "t1r": t1r,
            "after_pull_revoked_preserved": preserved,
            "after_pull_state": f"is_revoked={int(bool(att.is_revoked))}/ts={att.updated_at!r}",
        }

    return asyncio.run(main())


def step_s2_newer_push() -> dict:
    """设备 C：模拟另一设备本地编辑后 push 同 id 的「较新」题目/作答（answer 不变，避免 pull 重判刷新作答时间戳）。"""
    import asyncio

    from app.models.base import utcnow_iso
    from app.services.relay.sync import push_local_data_to_server

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from app.models import BankAttempt, BankQuestion, QuestionBank

        t2 = utcnow_iso()
        async with factory() as db:
            db.add(QuestionBank(id=S2_BANK, name="场景2题库", question_count=2))
            await db.flush()
            db.add(
                BankQuestion(
                    id=S2_Q,
                    bank_id=S2_BANK,
                    seq=1,
                    qtype="single",
                    title="场景2题目",
                    options='["甲","乙","丙","丁","","","",""]',
                    answer="A",
                    explanation="云端新解析",
                    updated_at=t2,
                )
            )
            await db.flush()
            db.add(
                BankAttempt(
                    id=S2_ATT,
                    bank_id=S2_BANK,
                    question_id=S2_Q,
                    content="B",
                    passed=False,
                    is_revoked=False,
                    updated_at=t2,
                )
            )
            await db.commit()
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res
        return {"t2": t2, "push_ok": True}

    return asyncio.run(main())


def step_s2_cloud_wins() -> dict:
    """设备 B：pull 云端较新快照（T2 > T1）→ 对照：合并路径未坏，云端较新值正常合入。"""
    import asyncio

    from app.services.relay.sync import pull_cloud_data_to_local

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.models import BankAttempt, BankQuestion

        res = await pull_cloud_data_to_local(server_url=server)
        assert res.get("ok"), res
        async with factory() as db:
            q = (await db.scalars(select(BankQuestion).where(BankQuestion.id == S2_Q))).one()
            att = (await db.scalars(select(BankAttempt).where(BankAttempt.id == S2_ATT))).one()
        merged = q.explanation == "云端新解析"
        unrevoked = not bool(att.is_revoked)
        return {
            "cloud_newer_merged": merged,
            "q_explanation_after": q.explanation,
            "q_updated_at_after": q.updated_at,
            "attempt_unrevoked": unrevoked,
            "att_after": f"is_revoked={int(bool(att.is_revoked))}/ts={att.updated_at!r}",
        }

    return asyncio.run(main())


# ------------------------------------------------- 场景 3（新者胜护栏）----
def step_s3_seed() -> dict:
    """设备 D：真实 create_mindmap 建两节点导图 + 课程 + 文档（磁盘正文），push。"""
    import asyncio

    from app.services.relay.sync import push_local_data_to_server

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from app.core.config import settings
        from app.models import Course, Document
        from app.schemas.mindmap import MindMapCreate
        from app.services import mindmap as mindmap_service

        async with factory() as db:
            mm = await mindmap_service.create_mindmap(
                db,
                MindMapCreate(
                    title="场景3导图",
                    topic="场景3",
                    root={"id": "mroot", "title": "根", "children": [{"id": "mn1", "title": "子一"}]},
                ),
            )
            db.add(Course(id=S3_CRS, title="场景3课程", topic="场景3", status="ready", outline="[]"))
            doc = Document(
                id=S3_DOC,
                course_id=S3_CRS,
                chapter_index=1,
                title="场景3章节",
                file_path=f"courses/{S3_CRS}/{S3_DOC}/current.md",
                status="done",
            )
            db.add(doc)
            await db.flush()  # 分阶段 flush（父行先落）
            doc_path = settings.data_dir / doc.file_path
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text("云端原文内容", encoding="utf-8")
            await db.commit()
            mm_ts = mm.updated_at
            mm_id = mm.id
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res
        return {"mm_id": mm_id, "mm_updated_at_seed": mm_ts, "push_ok": True}

    return asyncio.run(main())


def step_s3_edit() -> dict:
    """设备 D：真实 update_mindmap 改树（加第三节点）+ 课程改名（真实 PATCH）+ 文档改名改文；不 push。"""
    import asyncio

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.core.config import settings
        from app.models import Course, Document
        from app.schemas.mindmap import MindMapUpdate
        from app.services import mindmap as mindmap_service

        mm_id = os.environ["V59_S3_MM"]
        async with factory() as db:
            mm = await mindmap_service.update_mindmap(
                db,
                mm_id,
                MindMapUpdate(
                    root={
                        "id": "mroot",
                        "title": "根",
                        "children": [{"id": "mn1", "title": "子一"}, {"id": "mn2", "title": "子二"}],
                    }
                ),
            )
            t1_mm = mm.updated_at
            node_ids_mm = sorted(_node_ids(mm.root))

            # 课程：真实 PATCH 端点（api/courses.py update_course 刷新 updated_at）
            client = _testclient_headers()
            with client:
                resp = client.patch(f"/api/courses/{S3_CRS}", json={"title": "本地新课程名"})
                assert resp.status_code == 200, f"course patch 失败 {resp.status_code}: {resp.text}"

            # 文档：直接改行 + 磁盘正文（任务书允许的存量编辑路径；onupdate=utcnow_iso 刷新 updated_at）
            doc = (await db.scalars(select(Document).where(Document.id == S3_DOC))).one()
            doc.title = "本地新章节名"
            doc_path = settings.data_dir / doc.file_path
            doc_path.write_text("本地新内容", encoding="utf-8")
            await db.commit()
            t1_doc = doc.updated_at

        async with factory() as db:
            crs = (await db.scalars(select(Course).where(Course.id == S3_CRS))).one()
            t1_crs = crs.updated_at
        assert t1_mm and t1_crs and t1_doc, "本地编辑未刷新 updated_at"
        return {
            "t1_mindmap": t1_mm,
            "t1_course": t1_crs,
            "t1_doc": t1_doc,
            "node_ids_after_edit": node_ids_mm,
        }

    return asyncio.run(main())


def step_s3_pull() -> dict:
    """设备 D：不 push 直接 pull（云端旧树/旧课程/旧文档）→ 断言本地树仍含第三节点等。"""
    import asyncio

    from app.services.relay.sync import pull_cloud_data_to_local

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.core.config import settings
        from app.models import Course, Document, MindMap

        mm_id = os.environ["V59_S3_MM"]
        res = await pull_cloud_data_to_local(server_url=server)
        assert res.get("ok"), res
        async with factory() as db:
            mm = (await db.scalars(select(MindMap).where(MindMap.id == mm_id))).one()
            crs = (await db.scalars(select(Course).where(Course.id == S3_CRS))).one()
            doc = (await db.scalars(select(Document).where(Document.id == S3_DOC))).one()
        disk = (settings.data_dir / doc.file_path).read_text(encoding="utf-8")
        ids = sorted(_node_ids(mm.root))
        mm_ok = "mn2" in ids and len(ids) == 3
        crs_ok = crs.title == "本地新课程名"
        doc_ok = doc.title == "本地新章节名" and disk == "本地新内容"
        return {
            "pull_ok": True,
            "mindmap_local_tree_preserved": mm_ok,
            "node_ids_after_pull": ids,
            "course_local_title_preserved": crs_ok,
            "course_title_after": crs.title,
            "doc_local_preserved": doc_ok,
            "doc_title_after": doc.title,
            "doc_disk_after": disk,
        }

    return asyncio.run(main())


def step_s3_push_pull() -> dict:
    """设备 D（对照）：先 push 再 pull → 幂等无变化（护栏不得阻断正常回路）。"""
    import asyncio

    from app.services.relay.sync import pull_cloud_data_to_local, push_local_data_to_server

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.core.config import settings
        from app.models import Course, Document, MindMap

        mm_id = os.environ["V59_S3_MM"]
        pres = await push_local_data_to_server(server_url=server)
        assert pres.get("ok"), pres
        res = await pull_cloud_data_to_local(server_url=server)
        assert res.get("ok"), res
        async with factory() as db:
            mm = (await db.scalars(select(MindMap).where(MindMap.id == mm_id))).one()
            crs = (await db.scalars(select(Course).where(Course.id == S3_CRS))).one()
            doc = (await db.scalars(select(Document).where(Document.id == S3_DOC))).one()
        disk = (settings.data_dir / doc.file_path).read_text(encoding="utf-8")
        ids = sorted(_node_ids(mm.root))
        return {
            "still_three_nodes": "mn2" in ids and len(ids) == 3,
            "node_ids": ids,
            "course_title": crs.title,
            "doc_title": doc.title,
            "doc_disk": disk,
        }

    return asyncio.run(main())


def step_s3_newer_push() -> dict:
    """设备 E：模拟另一设备 push 同 id「较新」4 节点导图（T2 > T1）。"""
    import asyncio

    from app.models.base import utcnow_iso
    from app.services.relay.sync import push_local_data_to_server

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from app.models import MindMap

        t2 = utcnow_iso()
        mm_id = os.environ["V59_S3_MM"]
        async with factory() as db:
            db.add(
                MindMap(
                    id=mm_id,
                    title="云端导图",
                    topic="场景3",
                    root={
                        "id": "mroot",
                        "title": "根",
                        "children": [
                            {"id": "mn1", "title": "子一"},
                            {"id": "mn2", "title": "子二"},
                            {"id": "mn3", "title": "子三"},
                        ],
                    },
                    settings={},
                    source="manual",
                    updated_at=t2,
                )
            )
            await db.commit()
        res = await push_local_data_to_server(server_url=server)
        assert res.get("ok"), res
        return {"t2": t2, "push_ok": True}

    return asyncio.run(main())


def step_s3_cloud_wins() -> dict:
    """设备 D：pull 云端较新导图 → 对照：护栏不得拦下真正的新者，4 节点合入。"""
    import asyncio

    from app.services.relay.sync import pull_cloud_data_to_local

    server = os.environ["TREG_SERVER"]

    async def main() -> dict:
        factory = await _init_db_session_factory()
        from sqlalchemy import select

        from app.models import MindMap

        mm_id = os.environ["V59_S3_MM"]
        res = await pull_cloud_data_to_local(server_url=server)
        assert res.get("ok"), res
        async with factory() as db:
            mm = (await db.scalars(select(MindMap).where(MindMap.id == mm_id))).one()
        ids = sorted(_node_ids(mm.root))
        return {
            "cloud_newer_merged": "mn3" in ids and len(ids) == 4,
            "node_ids": ids,
            "title": mm.title,
            "updated_at": mm.updated_at,
        }

    return asyncio.run(main())


# ------------------------------------------------------------------ 驱动 ----
def main_driver() -> None:
    data_root = Path(tempfile.mkdtemp(prefix="treg2_", dir=str(ROOT / "backend")))
    port = _free_port()
    server = f"http://127.0.0.1:{port}"
    os.environ["DATA_DIR"] = str(data_root / "server-data")
    os.environ["RELAY_AUTH_REQUIRED"] = "false"

    srv = None
    thread = None
    try:
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

        scenario_results: list[dict] = []

        # ============================ 场景 1 ============================
        print("== 场景 1：题库整库替换 × (bank_id,seq) 立即唯一索引 ==")
        s1 = _run_step("s1-setup", str(data_root / "deviceA"), server)
        assert len(s1["questions"]) == 3, s1
        print(f"  [setup] bank={s1['bank_id'][:12]}… 初始序：{_short_qs({'questions': s1['questions']})}")

        os.environ["V59_S1_SETUP"] = json.dumps(s1)
        s1r = _run_step("s1-reorder", str(data_root / "deviceA"), server)
        print(
            f"  [reorder] status={s1r['replace_status']} err={s1r['replace_error']}\n"
            f"  [reorder] 前序={s1r['before_seq_title']} → 回滚后={s1r['after_seq_title']} "
            f"intact={s1r['after_rollback_intact']}"
        )
        reorder_failed = s1r["replace_status"] is None and s1r["replace_error"] is not None
        reorder_http500 = s1r["replace_status"] == 500
        err_is_integrity = "IntegrityError" in (s1r["replace_error"] or "")
        # v0.5.10 双向判定：换序替换成功且库态按新顺序（乙,甲,丙）落位 = 两阶段重排修复生效
        applied_correctly = s1r.get("applied_correctly") is True

        s1c = _run_step("s1-control", str(data_root / "deviceA"), server)
        print(f"  [control 同序替换] status={s1c['replace_status']} 序={s1c['seq_title']}")
        control_ok = s1c["replace_status"] == 200 and [q["seq"] for q in s1c["snapshot"]["questions"]] == [1, 2, 3]

        s1d = _run_step("s1-delete", str(data_root / "deviceA"), server)
        print(
            f"  [delete 删C保留AB] status={s1d['replace_status']} 序={s1d['seq_title']} "
            f"C_gone={s1d['removed_C_gone']} C_tomb={s1d['C_tombstoned']}"
        )
        delete_ok = s1d["replace_status"] == 200 and s1d["removed_C_gone"] and s1d["C_tombstoned"]

        if (reorder_failed or reorder_http500) and s1r["after_rollback_intact"] and control_ok and delete_ok:
            s1_verdict = "confirmed_broken"
        elif applied_correctly and control_ok and delete_ok:
            s1_verdict = "fix_works"
        elif not (reorder_failed or reorder_http500):
            s1_verdict = "inconclusive"  # 换序替换成功但库态落位不符，人工核查
        else:
            s1_verdict = "fix_incomplete"
        evidence1 = [
            f"换序替换(B,A,C)：status={s1r['replace_status']} error={s1r['replace_error']}",
            f"落位后库态 intact={s1r['after_rollback_intact']} applied_correctly={applied_correctly}（{_s1_desc(s1r)}）",
            f"同序替换对照(A,B,C)：status={s1c['replace_status']}（成功）",
            f"删题不换序对照(A,B)：status={s1d['replace_status']} C落墓碑={s1d['C_tombstoned']}",
        ]
        scenario_results.append({"scenario": "场景1 题库整库替换×(bank_id,seq)唯一索引", "verdict": s1_verdict, "evidence": evidence1})

        # ============================ 场景 2 ============================
        print("== 场景 2：P1-4 空 updated_at 回退（题目纠错 + 作答撤回）==")
        s2seed = _run_step("s2-seed", str(data_root / "deviceB"), server)
        print(
            f"  [seed] 本地updated_at全空={s2seed['local_updated_at_empty']} 推云updated_at={s2seed['pushed_question_updated_at']!r} "
            f"同进程不编辑直接pull合并正常={s2seed['self_pull_merged_ok']}"
        )
        # 云端快照确认：题目确实以 updated_at='' 落云
        cloud_q = next(q for q in _pull(server)["bank_questions"] if q["id"] == S2_Q)
        assert cloud_q.get("updated_at") == "", f"云端题目 updated_at 非空：{cloud_q.get('updated_at')!r}"

        s2edit = _run_step("s2-edit", str(data_root / "deviceB"), server)
        print(
            f"  [edit] T1={s2edit['t1']} exp={s2edit['explanation']} "
            f"回填基线T_b={s2edit['backfill_ts']} 编辑未触碰作答/对照题={s2edit['attempt_untouched_by_edit']}"
        )
        os.environ["V59_S2_T1"] = s2edit["t1"]
        os.environ["V59_S2_TB_Q2"] = s2edit["q2_ts_baseline"]

        s2pull = _run_step("s2-pull-edited", str(data_root / "deviceB"), server)
        print(
            f"  [pull-edited] 编辑保留={s2pull['local_edit_preserved']} q_exp={s2pull['q_explanation']} ts==T1={s2pull['q_updated_at'] == s2pull['expected_t1']} "
            f"对照题未被旧快照覆盖={s2pull['untouched_row_intact']} q2={s2pull['q2_state']}"
        )

        s2rev = _run_step("s2-revoke", str(data_root / "deviceB"), server)
        print(f"  [revoke] 撤回后pull保留={s2rev['after_pull_revoked_preserved']} 状态={s2rev['after_pull_state']}")

        s2new = _run_step("s2-newer-push", str(data_root / "deviceC"), server)
        print(f"  [newer-push] 设备C T2={s2new['t2']}")

        s2win = _run_step("s2-cloud-wins", str(data_root / "deviceB"), server)
        print(
            f"  [cloud-wins 对照] 云端较新合入={s2win['cloud_newer_merged']} q_exp={s2win['q_explanation_after']} "
            f"att={s2win['att_after']}"
        )

        s2_ok = (
            s2seed["local_updated_at_empty"]
            and s2seed["self_pull_merged_ok"]
            and s2edit["attempt_untouched_by_edit"]
            and s2pull["local_edit_preserved"]
            and s2pull["untouched_row_intact"]
            and s2rev["after_pull_revoked_preserved"]
        )
        s2_ctrl_ok = s2win["cloud_newer_merged"] and s2win["attempt_unrevoked"]
        s2_verdict = "fix_works" if (s2_ok and s2_ctrl_ok) else ("fix_incomplete" if s2_ok else "confirmed_broken")
        evidence2 = [
            f"存量行（题目/对照题/作答 updated_at=''）push：云端快照 updated_at=''",
            f"对照①同进程不编辑直接 pull（'' vs ''）：正常合入={s2seed['self_pull_merged_ok']}（{s2seed['self_pull_message']}）",
            f"本地纠错(update_question)→T1={s2edit['t1'][:26]}…（本步 init_db 已把存量行回填 T_b={s2edit['backfill_ts'][:26]}…，db.py P1-4 迁移）",
            f"不 push 直接 pull（云端 '' 旧快照）：本地编辑保留={s2pull['local_edit_preserved']}，对照题 q2 未被覆盖={s2pull['untouched_row_intact']}",
            f"本地撤回(revoke 端点)→直接 pull：is_revoked 仍=1={s2rev['after_pull_revoked_preserved']}（{s2rev['after_pull_state']}）",
            f"对照②云端较新(T2 > T1)：正常合入={s2win['cloud_newer_merged']}，撤回被较新快照正常解除={s2win['attempt_unrevoked']}",
        ]
        scenario_results.append({"scenario": "场景2 P1-4 空 updated_at 回退", "verdict": s2_verdict, "evidence": evidence2})

        # ============================ 场景 3 ============================
        print("== 场景 3：P1-5 导图/课程/文档新者胜护栏 ==")
        s3seed = _run_step("s3-seed", str(data_root / "deviceD"), server)
        os.environ["V59_S3_MM"] = s3seed["mm_id"]
        print(f"  [seed] mm={s3seed['mm_id']} updated_at={s3seed['mm_updated_at_seed']}")
        # 云端快照确认：导图确实以旧两节点树落云
        cloud_mm = next(m for m in _pull(server)["mindmaps"] if m["id"] == s3seed["mm_id"])
        cloud_root = cloud_mm.get("root") or cloud_mm.get("nodes") or {}
        assert len(_node_ids(cloud_root)) == 2, f"云端导图节点数异常：{_node_ids(cloud_root)}"
        s3edit = _run_step("s3-edit", str(data_root / "deviceD"), server)
        print(f"  [edit] 三节点={s3edit['node_ids_after_edit']} T1导图={s3edit['t1_mindmap'][:26]}…")

        s3pull = _run_step("s3-pull", str(data_root / "deviceD"), server)
        print(
            f"  [pull] 导图树保留={s3pull['mindmap_local_tree_preserved']} 节点={s3pull['node_ids_after_pull']}\n"
            f"  [pull] 课程保留={s3pull['course_local_title_preserved']} 文档保留={s3pull['doc_local_preserved']}"
        )

        s3pp = _run_step("s3-push-pull", str(data_root / "deviceD"), server)
        print(f"  [push→pull 对照] 三节点仍在={s3pp['still_three_nodes']} 课程={s3pp['course_title']} 文档={s3pp['doc_title']}")

        _run_step("s3-newer-push", str(data_root / "deviceE"), server)
        s3win = _run_step("s3-cloud-wins", str(data_root / "deviceD"), server)
        print(f"  [cloud-wins 对照] 云端4节点合入={s3win['cloud_newer_merged']} 节点={s3win['node_ids']} title={s3win['title']}")

        s3_ok = (
            s3pull["mindmap_local_tree_preserved"]
            and s3pull["course_local_title_preserved"]
            and s3pull["doc_local_preserved"]
            and s3pp["still_three_nodes"]
            and s3pp["course_title"] == "本地新课程名"
        )
        s3_ctrl_ok = s3win["cloud_newer_merged"]
        s3_verdict = "fix_works" if (s3_ok and s3_ctrl_ok) else ("fix_incomplete" if s3_ok else "confirmed_broken")
        evidence3 = [
            f"本地 update_mindmap 三节点（含 mn2）T1，不 push 直接 pull 云端旧两节点树",
            f"pull 后本地树保留={s3pull['mindmap_local_tree_preserved']} 节点={s3pull['node_ids_after_pull']}",
            f"课程标题保留={s3pull['course_local_title_preserved']}（{s3pull['course_title_after']}）",
            f"文档标题/磁盘正文保留={s3pull['doc_local_preserved']}（{s3pull['doc_title_after']} / {s3pull['doc_disk_after']}）",
            f"对照：push→pull 幂等无变化={s3pp['still_three_nodes']}；云端较新4节点正常合入={s3win['cloud_newer_merged']}",
        ]
        scenario_results.append({"scenario": "场景3 P1-5 导图新者胜护栏（含课程/文档同型）", "verdict": s3_verdict, "evidence": evidence3})

        print("\nSCENARIOS_RESULT " + json.dumps(scenario_results, ensure_ascii=False))
    finally:
        # 先停服务端释放 SQLite 句柄，再清理临时目录（Windows 文件锁，重试数次）
        if srv is not None:
            srv.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
            if thread.is_alive():
                print("CLEANUP_WARN uvicorn 线程 10s 未退出，继续清理尝试")
        import gc
        import sqlite3

        cleaned = False
        for _ in range(20):
            shutil.rmtree(data_root, ignore_errors=True)
            if not data_root.exists():
                cleaned = True
                break
            # 兜底：强制关闭本进程内所有残留 sqlite 连接（sqlite3 的 with 不 close）
            for obj in gc.get_objects():
                if isinstance(obj, sqlite3.Connection):
                    try:
                        obj.close()
                    except Exception:
                        pass
            gc.collect()
            time.sleep(0.5)
        print(f"CLEANUP_OK={cleaned} 临时目录: {data_root}")
        if not cleaned:
            print(f"CLEANUP_WARN 残留内容：{list(data_root.rglob('*'))[:20]}")


def _s1_desc(s1r: dict) -> str:
    return f"{s1r['after_seq_title']}（换序前 {s1r['before_seq_title']}）"


STEPS = {
    "s1-setup": step_s1_setup,
    "s1-reorder": step_s1_reorder,
    "s1-control": step_s1_control,
    "s1-delete": step_s1_delete,
    "s2-seed": step_s2_seed,
    "s2-edit": step_s2_edit,
    "s2-pull-edited": step_s2_pull_edited,
    "s2-revoke": step_s2_revoke,
    "s2-newer-push": step_s2_newer_push,
    "s2-cloud-wins": step_s2_cloud_wins,
    "s3-seed": step_s3_seed,
    "s3-edit": step_s3_edit,
    "s3-pull": step_s3_pull,
    "s3-push-pull": step_s3_push_pull,
    "s3-newer-push": step_s3_newer_push,
    "s3-cloud-wins": step_s3_cloud_wins,
}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in STEPS:
        result = STEPS[sys.argv[1]]()
        print("STEP_RESULT", json.dumps(result, ensure_ascii=False))
    else:
        main_driver()
