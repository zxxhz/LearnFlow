"""题库刷题服务：解析 15 列题库表格（.xls/.xlsx）、判分、导入落库、统计派生。

表格布局对齐《浙江省大学生网络与信息安全竞赛题库》（原刷题应用 bank.py 实测验证）：
0 题型 | 1 题干 | 2-9 选项A-H | 10 正确答案 | 11 备用 | 12 解析 | 13 难度
"""
import asyncio
import json
import logging
import random
import re
import shutil
import uuid
from io import BytesIO

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.bank import (
    JUDGE_OPTIONS,
    QUESTION_JUDGE,
    QUESTION_MULTI,
    QUESTION_SINGLE,
    BankAttempt,
    BankQuestion,
    QuestionBank,
)
from app.services.llm import create_adapter_from_settings
from app.services.prompt import load_prompt, render_prompt

logger = logging.getLogger(__name__)

BANK_EXTENSIONS = (".xls", ".xlsx")
MAX_BANK_BYTES = 20 * 1024 * 1024

# 表格列位（0 起）
COL_TYPE = 0
COL_TITLE = 1
COL_OPT_A = 2
COL_OPT_H = 9
COL_ANSWER = 10
COL_EXPLANATION = 12
COL_DIFFICULTY = 13
N_COLS = 14  # 只读前 14 列（第 15 列存在于错题表，原题库无）

TYPE_MAP = {
    "单选题": QUESTION_SINGLE,
    "单选": QUESTION_SINGLE,
    "多选题": QUESTION_MULTI,
    "多选": QUESTION_MULTI,
    "判断题": QUESTION_JUDGE,
    "判断": QUESTION_JUDGE,
}

_JUDGE_TRUE = {"正确", "对", "√", "是", "T", "TRUE", "true"}
_JUDGE_FALSE = {"错误", "错", "×", "x", "X", "否", "F", "FALSE", "false"}


class BankParseError(ValueError):
    """题库文件无法解析（格式不符 / 空文件等），API 层转 400。"""


def _clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("\xa0", " ").replace("&nbsp;", " ").strip()


def _iter_rows(data: bytes, filename: str):
    """按行产出前 14 列原始单元格；跳过首行表头。

    损坏/伪装的表格文件（扩展名对但内容不是表格）统一包装成 BankParseError，
    API 层转 400，而不是把 xlrd/openpyxl 的原始异常漏成 500。
    """
    name = filename.lower()
    if name.endswith(".xls"):
        import xlrd

        try:
            sh = xlrd.open_workbook(file_contents=data, on_demand=True).sheet_by_index(0)
            for r in range(1, sh.nrows):
                yield r + 1, [sh.cell_value(r, c) for c in range(min(N_COLS, sh.ncols))]
        except BankParseError:
            raise
        except Exception as e:
            raise BankParseError(f"题库文件无法解析（{e}）：请确认是有效的 .xls 表格") from e
    elif name.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
            ws = wb[wb.sheetnames[0]]
            rows = ws.iter_rows(values_only=True)
            next(rows, None)  # 表头
            for rno, row in enumerate(rows, start=2):
                yield rno, list(row[:N_COLS])
            wb.close()
        except BankParseError:
            raise
        except Exception as e:  # noqa: BLE001
            raise BankParseError(f"题库文件无法解析（{e}）：请确认是有效的 .xlsx 表格") from e
    else:
        raise BankParseError("仅支持 .xls / .xlsx 题库文件")


def normalize_answer(qtype: str, raw: str, excel_row: int) -> str:
    """答案归一化：single/judge → 单字母；multi → 排序去重大写字母串。

    兼容中文题库常见的全角逗号「，」、顿号「、」与尾点「A.」写法。
    """
    raw = (raw or "").replace("，", ",").replace("、", ",").replace("．", ".")
    if qtype == QUESTION_JUDGE:
        if raw.strip() in _JUDGE_TRUE:
            return JUDGE_OPTIONS[0][0]
        if raw.strip() in _JUDGE_FALSE:
            return JUDGE_OPTIONS[1][0]
        raise BankParseError(f"第 {excel_row} 行判断题答案无法识别：{raw!r}")
    letters = sorted({x.strip().rstrip(".").upper() for x in raw.split(",") if x.strip()})
    if not letters:
        raise BankParseError(f"第 {excel_row} 行答案为空")
    for ch in letters:
        if not ("A" <= ch <= "H"):
            raise BankParseError(f"第 {excel_row} 行答案含未知选项字母：{ch}")
    if qtype == QUESTION_SINGLE and len(letters) != 1:
        raise BankParseError(f"第 {excel_row} 行单选题答案不止一个：{raw!r}")
    return ",".join(letters)


def parse_bank(data: bytes, filename: str) -> tuple[list[dict], dict]:
    """解析题库文件 → (questions, report)。questions 为落库字典列表，report 供预览。

    坏行（题型/题干为空）跳过并计入 skipped；题型/答案无法识别的行视为坏行不中断整体导入。
    """
    if len(data) > MAX_BANK_BYTES:
        raise BankParseError("题库文件过大（上限 20MB）")

    questions: list[dict] = []
    skipped: list[dict] = []

    for excel_row, raw in _iter_rows(data, filename):
        row = list(raw) + [""] * (N_COLS - len(raw))
        qtype_raw = _clean(row[COL_TYPE])
        title = _clean(row[COL_TITLE])
        if not title or not qtype_raw:
            if any(_clean(c) for c in row):
                skipped.append({"row": excel_row, "reason": "题目标题或题型为空"})
            continue
        qtype = TYPE_MAP.get(qtype_raw)
        if qtype is None:
            skipped.append({"row": excel_row, "reason": f"未知题型：{qtype_raw}"})
            continue
        try:
            answer = normalize_answer(qtype, _clean(row[COL_ANSWER]), excel_row)
        except BankParseError as e:
            skipped.append({"row": excel_row, "reason": str(e)})
            continue

        options = [_clean(row[c]) for c in range(COL_OPT_A, COL_OPT_H + 1)]
        answer_raw = (
            ("正确" if answer == "A" else "错误")
            if qtype == QUESTION_JUDGE
            else answer.replace(",", "、")
        )
        questions.append(
            {
                "seq": len(questions) + 1,
                "qtype": qtype,
                "title": title,
                "options": options,
                "answer": answer,
                "answer_raw": answer_raw,
                "difficulty": _clean(row[COL_DIFFICULTY]),
                "explanation": _clean(row[COL_EXPLANATION]),
            }
        )

    if not questions:
        raise BankParseError("未能从文件中解析出任何题目，请检查表格列布局")
    report = {
        "name": filename.rsplit(".", 1)[0] if "." in filename else filename,
        "source_file": filename,
        "question_count": len(questions),
        "skipped": skipped[:20],
        "skipped_total": len(skipped),
        "by_type": _count_by(questions, "qtype"),
        "by_difficulty": _count_by(questions, "difficulty"),
    }
    return questions, report


def _count_by(questions: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for q in questions:
        k = q[key] or "（未标注）"
        out[k] = out.get(k, 0) + 1
    return out


def judge_answer(qtype: str, answer: str, submitted: list[str]) -> bool:
    """判分纯函数：提交字母集合与正确答案集合比对（single/judge/multi 统一）。"""
    picks = {s.strip().upper() for s in submitted if s and s.strip()}
    if not picks:
        return False
    return picks == set(answer.split(","))


def format_correct_answer(q: BankQuestion) -> str:
    """提交结果里的「正确答案」展示串：判断题给 正确/错误，选择题给字母（多选顿号连接）。"""
    if q.qtype == QUESTION_JUDGE:
        return "正确" if q.answer == "A" else "错误"
    return q.answer.replace(",", "、")


async def create_bank(
    db: AsyncSession, questions: list[dict], report: dict, file_bytes: bytes
) -> QuestionBank:
    """落库：题库 + 全部题目，原件归档到 data/banks/{bank_id}/original.{ext}。"""
    bank = QuestionBank(
        name=report["name"] or "导入题库",
        source_file=report["source_file"],
        question_count=len(questions),
    )
    db.add(bank)
    await db.flush()

    # 归档先于 commit：写盘失败时整体回滚（不留"有题库记录但无原件归档"的半截数据）
    ext = "." + report["source_file"].rsplit(".", 1)[-1].lower()
    bank_dir = settings.data_dir / "banks" / bank.id
    bank_dir.mkdir(parents=True, exist_ok=True)
    (bank_dir / f"original{ext}").write_bytes(file_bytes)

    for q in questions:
        db.add(
            BankQuestion(
                bank_id=bank.id,
                seq=q["seq"],
                qtype=q["qtype"],
                title=q["title"],
                options=json.dumps(q["options"], ensure_ascii=False),
                answer=q["answer"],
                answer_raw=q["answer_raw"],
                difficulty=q["difficulty"],
                explanation=q["explanation"],
            )
        )
    try:
        await db.commit()
    except Exception:
        # 落库失败：回滚并清掉已写的归档目录，不留无主孤儿
        await db.rollback()
        shutil.rmtree(bank_dir, ignore_errors=True)
        raise
    return bank


# 按题库 id 的进程内写锁：append/replace 的「读 max_seq/count → 写 → commit」全程串行，
# 防局域网多端并发追加时 seq 撞号与 question_count 丢更新
_bank_locks: dict[str, asyncio.Lock] = {}


def _bank_lock(bank_id: str) -> asyncio.Lock:
    lock = _bank_locks.get(bank_id)
    if lock is None:
        lock = asyncio.Lock()
        _bank_locks[bank_id] = lock
    return lock


async def append_questions(
    db: AsyncSession, bank: QuestionBank, formatted_questions: list[dict]
) -> int:
    """向已有题库追加题目：自动计算 seq 递增、批量落库并同步更新 question_count。"""
    if not formatted_questions:
        return 0

    async with _bank_lock(bank.id):
        count_and_seq = (
            await db.execute(
                select(
                    func.count(BankQuestion.id).label("cnt"),
                    func.coalesce(func.max(BankQuestion.seq), 0).label("max_seq"),
                ).where(BankQuestion.bank_id == bank.id)
            )
        ).one()
        max_seq = int(count_and_seq.max_seq or 0)

        for i, q in enumerate(formatted_questions, 1):
            db.add(
                BankQuestion(
                    bank_id=bank.id,
                    seq=max_seq + i,
                    qtype=q["qtype"],
                    title=q["title"],
                    options=json.dumps(q["options"], ensure_ascii=False),
                    answer=q["answer"],
                    answer_raw=q["answer_raw"],
                    difficulty=q["difficulty"],
                    explanation=q["explanation"],
                )
            )
        # flush 后按真实行数回填 count（消除读改写竞态的丢失更新）
        await db.flush()
        bank.question_count = int(
            (
                await db.execute(
                    select(func.count(BankQuestion.id)).where(BankQuestion.bank_id == bank.id)
                )
            ).scalar_one()
        )
        await db.commit()
    return len(formatted_questions)


async def update_question(
    db: AsyncSession,
    q: BankQuestion,
    title: str | None = None,
    options: list[str] | None = None,
    answer: str | None = None,
    explanation: str | None = None,
    difficulty: str | None = None,
    recalibrate_attempts: bool = True,
) -> tuple[BankQuestion, BankAttempt | None]:
    """更新题目内容/选项/答案，并可选按新答案自动重判最新作答记录（若改错为对则自动移出错题池）。

    选项内容/顺序变更也触发重判：旧作答字母按新选项位置解释，语义可能漂移。
    全程持有 _bank_lock，并在锁内重查题目防与 replace 并发导致 StaleDataError。
    """
    async with _bank_lock(q.bank_id):
        # populate_existing 必须加：同一 Session 此前已加载过该题时，裸 get 命中 identity map
        # 不再发 SQL，「锁内重查」沦为空操作 → 用陈旧答案判分 / 并发删题 commit 时 StaleDataError
        # / 陈旧基线覆盖 replace 校准（lost update）。（v0.5.1 体检 P1，venv 实跑复刻实证）
        fresh_q = await db.get(BankQuestion, q.id, populate_existing=True)
        if fresh_q is None:
            raise ValueError("题目不存在或已被移除")
        q = fresh_q

        if title is not None and title.strip():
            q.title = title.strip()

        content_changed = False
        if q.qtype == QUESTION_JUDGE:
            q.options = "[]"
            if answer is not None and answer.strip():
                clean = answer.strip().upper()
                if clean in ("A", "TRUE", "T", "对", "正确", "1", "YES", "√", "是"):
                    ans_clean = "A"
                elif clean in ("B", "FALSE", "F", "错", "错误", "0", "NO", "×", "否"):
                    ans_clean = "B"
                else:
                    raise ValueError("判断题答案只能是正确(A)或错误(B)")
                if ans_clean != q.answer:
                    content_changed = True
                q.answer = ans_clean
                q.answer_raw = "正确" if ans_clean == "A" else "错误"
        else:
            if options is not None:
                raw_opts = [opt.strip() for opt in options if opt.strip()]
                if len(raw_opts) < 2:
                    raise ValueError("选择题至少需要保留 2 个有效选项")
                opts = (raw_opts + [""] * 8)[:8]
                new_options_json = json.dumps(opts, ensure_ascii=False)
                if new_options_json != q.options:
                    content_changed = True
                q.options = new_options_json
            if answer is not None and answer.strip():
                ans_norm = normalize_answer(q.qtype, answer.strip(), q.seq)
                if ans_norm != q.answer:
                    content_changed = True
                q.answer = ans_norm
                q.answer_raw = ans_norm.replace(",", "、")

        if explanation is not None:
            q.explanation = explanation.strip()

        if difficulty is not None and difficulty.strip():
            q.difficulty = difficulty.strip()

        # 仅在题目内容/参考答案实际变化时清空旧 AI 解析（只改难度/解析不清，省一次重新生成）
        if content_changed:
            q.ai_explanation = ""

        recalibrated_attempt = None
        if recalibrate_attempts and content_changed:
            latest_att = (
                await db.scalars(
                    select(BankAttempt)
                    .where(BankAttempt.question_id == q.id)
                    .order_by(BankAttempt.created_at.desc())
                    .limit(1)
                )
            ).first()

            if latest_att:
                submitted = [x.strip() for x in latest_att.content.split(",") if x.strip()]
                new_passed = judge_answer(q.qtype, q.answer, submitted)
                if latest_att.passed != new_passed:
                    latest_att.passed = new_passed
                recalibrated_attempt = latest_att

        await db.commit()
        return q, recalibrated_attempt


def _normalize_title_for_match(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    return t.replace("(", "（").replace(")", "）")


def _normalize_options_for_match(options: list[str]) -> frozenset[str]:
    return frozenset(re.sub(r"\s+", " ", opt.strip()) for opt in options if opt and opt.strip())


def align_questions_for_replacement(
    old_questions: list[BankQuestion], new_questions: list[dict]
) -> tuple[list[tuple[BankQuestion, dict]], list[dict], list[BankQuestion]]:
    """将新表格题目与已有题目按内容指纹对齐，区分出：匹配题对（继承旧ID）、新增题、淘汰题。"""
    lvl1_pool: dict[tuple[str, str, frozenset[str]], list[BankQuestion]] = {}
    lvl2_pool: dict[tuple[str, str], list[BankQuestion]] = {}

    for q in old_questions:
        norm_t = _normalize_title_for_match(q.title)
        raw_opts = json.loads(q.options) if q.options else []
        norm_o = _normalize_options_for_match(raw_opts) if q.qtype != QUESTION_JUDGE else frozenset()

        k1 = (q.qtype, norm_t, norm_o)
        lvl1_pool.setdefault(k1, []).append(q)

        k2 = (q.qtype, norm_t)
        lvl2_pool.setdefault(k2, []).append(q)

    matched: list[tuple[BankQuestion, dict]] = []
    unmatched_new: list[dict] = []
    used_old_ids: set[str] = set()

    # 第一轮：Level 1 严格匹配（题型 + 规范化题干 + 规范化选项集合完全一致）
    for nq in new_questions:
        norm_t = _normalize_title_for_match(nq["title"])
        norm_o = _normalize_options_for_match(nq.get("options", [])) if nq["qtype"] != QUESTION_JUDGE else frozenset()
        k1 = (nq["qtype"], norm_t, norm_o)

        candidates = lvl1_pool.get(k1, [])
        found_old = None
        while candidates:
            cand = candidates.pop(0)
            if cand.id not in used_old_ids:
                found_old = cand
                break

        if found_old:
            used_old_ids.add(found_old.id)
            matched.append((found_old, nq))
        else:
            unmatched_new.append(nq)

    # 第二轮：Level 2 题干唯一回退匹配（针对选项文字修正或增减选项场景，双方题干均唯一）。
    # len(norm_t) >= 2 兼容短题干（如 "1+1=?"），并追加选项集合 Jaccard 相似度 ≥0.5 护栏防误匹配。
    added: list[dict] = []
    for nq in unmatched_new:
        norm_t = _normalize_title_for_match(nq["title"])
        k2 = (nq["qtype"], norm_t)

        candidates = [c for c in lvl2_pool.get(k2, []) if c.id not in used_old_ids]
        if len(norm_t) >= 2 and len(candidates) == 1:
            found_old = candidates[0]
            old_opts = json.loads(found_old.options) if found_old.options else []
            old_set = (
                _normalize_options_for_match(old_opts)
                if found_old.qtype != QUESTION_JUDGE
                else frozenset()
            )
            new_set = (
                _normalize_options_for_match(nq.get("options", []))
                if nq["qtype"] != QUESTION_JUDGE
                else frozenset()
            )
            if found_old.qtype == QUESTION_JUDGE:
                similar = True
            else:
                union = old_set | new_set
                # 修复原 not union 短路：选择题必须有有效选项并要求交并比 ≥0.5
                similar = bool(union) and (len(old_set & new_set) / len(union) >= 0.5)
            if similar:
                used_old_ids.add(found_old.id)
                matched.append((found_old, nq))
                continue
        added.append(nq)

    removed = [q for q in old_questions if q.id not in used_old_ids]
    return matched, added, removed


async def analyze_bank_replacement(
    db: AsyncSession,
    bank: QuestionBank,
    new_questions: list[dict],
    new_file_name: str,
    skipped_total: int = 0,
) -> dict:
    """对比当前题库与新表格题目，计算保留、新增、移出以及答案校准指标，纯分析不写库。"""
    old_questions = (
        await db.scalars(
            select(BankQuestion).where(BankQuestion.bank_id == bank.id).order_by(BankQuestion.seq)
        )
    ).all()

    latest_atts = await latest_attempts(db, bank.id)
    matched, added, removed = align_questions_for_replacement(old_questions, new_questions)

    answered_retained = 0
    unanswered_retained = 0
    recalibrated_count = 0
    samples_recalibrated = []

    for old_q, new_q in matched:
        att = latest_atts.get(old_q.id)
        if att:
            answered_retained += 1
        else:
            unanswered_retained += 1

        if new_q["answer"] != old_q.answer:
            recalibrated_count += 1
            if len(samples_recalibrated) < 5:
                sample_item = {
                    "title": new_q["title"],
                    "qtype": new_q["qtype"],
                    "old_answer": old_q.answer_raw or old_q.answer,
                    "new_answer": new_q["answer_raw"] or new_q["answer"],
                    "user_answer": None,
                    "recalibrated_passed": None,
                }
                if att:
                    submitted = [x.strip() for x in att.content.split(",") if x.strip()]
                    new_passed = judge_answer(new_q["qtype"], new_q["answer"], submitted)
                    sample_item["user_answer"] = att.content
                    sample_item["recalibrated_passed"] = new_passed
                samples_recalibrated.append(sample_item)

    return {
        "bank_id": bank.id,
        "bank_name": bank.name,
        "new_source_file": new_file_name,
        "current_total": len(old_questions),
        "new_total": len(new_questions),
        "matched_count": len(matched),
        "answered_retained": answered_retained,
        "unanswered_retained": unanswered_retained,
        "recalibrated_count": recalibrated_count,
        "removed_count": len(removed),
        "added_count": len(added),
        "skipped_total": skipped_total,
        "samples_recalibrated": samples_recalibrated,
        "samples_removed": [q.title for q in removed[:5]],
        "samples_added": [q["title"] for q in added[:5]],
    }


async def replace_bank_with_questions(
    db: AsyncSession,
    bank: QuestionBank,
    new_questions: list[dict],
    new_file_name: str,
    file_bytes: bytes,
) -> QuestionBank:
    """全量替换题库题目并继承历史作答记录：对齐保留旧ID、重排seq、重判改对错题、清理移出题。"""
    async with _bank_lock(bank.id):
        return await _replace_bank_locked(db, bank, new_questions, new_file_name, file_bytes)


async def _replace_bank_locked(
    db: AsyncSession,
    bank: QuestionBank,
    new_questions: list[dict],
    new_file_name: str,
    file_bytes: bytes,
) -> QuestionBank:
    old_questions = (
        await db.scalars(
            select(BankQuestion).where(BankQuestion.bank_id == bank.id).order_by(BankQuestion.seq)
        )
    ).all()

    latest_atts = await latest_attempts(db, bank.id)
    matched, added, removed = align_questions_for_replacement(old_questions, new_questions)

    matched_old_lookup: dict[int, BankQuestion] = {}
    for old_q, nq in matched:
        matched_old_lookup[id(nq)] = old_q

    # 1. 清理被移除的题目（先清理关联作答流水，防外键错误与孤儿脏数据）；
    #    分批 in_（SQLite 绑定变量上限 32766，超大题库一次绑定会 500）
    if removed:
        removed_ids = [q.id for q in removed]
        for i in range(0, len(removed_ids), 500):
            chunk = removed_ids[i : i + 500]
            await db.execute(delete(BankAttempt).where(BankAttempt.question_id.in_(chunk)))
            await db.execute(delete(BankQuestion).where(BankQuestion.id.in_(chunk)))

    # 2. 按新表格顺序更新对齐题目并插入新题目。
    #    选项内容/顺序变化同样触发重判：旧作答字母按新选项位置解释，语义可能漂移
    for seq_idx, nq in enumerate(new_questions, 1):
        old_q = matched_old_lookup.get(id(nq))
        if old_q:
            old_options_json = json.dumps(nq["options"], ensure_ascii=False)
            content_changed = old_q.answer != nq["answer"] or old_options_json != old_q.options
            old_q.seq = seq_idx
            old_q.title = nq["title"]
            old_q.options = old_options_json
            old_q.difficulty = nq["difficulty"]
            old_q.explanation = nq["explanation"]

            if content_changed:
                old_q.answer = nq["answer"]
                old_q.answer_raw = nq["answer_raw"]
                old_q.ai_explanation = ""

                att = latest_atts.get(old_q.id)
                if att:
                    submitted = [x.strip() for x in att.content.split(",") if x.strip()]
                    new_passed = judge_answer(old_q.qtype, old_q.answer, submitted)
                    if att.passed != new_passed:
                        att.passed = new_passed
        else:
            db.add(
                BankQuestion(
                    bank_id=bank.id,
                    seq=seq_idx,
                    qtype=nq["qtype"],
                    title=nq["title"],
                    options=json.dumps(nq["options"], ensure_ascii=False),
                    answer=nq["answer"],
                    answer_raw=nq["answer_raw"],
                    difficulty=nq["difficulty"],
                    explanation=nq["explanation"],
                )
            )

    # 3. 更新题库元信息
    bank.question_count = len(new_questions)
    if new_file_name:
        bank.source_file = new_file_name

    # 4. 安全两阶段替换原件归档文件；顺手清理历史遗留的孤儿临时归档（>1h）
    ext = "." + new_file_name.rsplit(".", 1)[-1].lower() if "." in new_file_name else ".xlsx"
    bank_dir = settings.data_dir / "banks" / bank.id
    bank_dir.mkdir(parents=True, exist_ok=True)
    import time as _time

    now_ts = _time.time()
    for stale_tmp in bank_dir.glob(".replace_tmp_*"):
        try:
            if now_ts - stale_tmp.stat().st_mtime > 3600:
                stale_tmp.unlink(missing_ok=True)
        except OSError:
            pass
    temp_archive = bank_dir / f".replace_tmp_{uuid.uuid4().hex[:8]}{ext}"
    temp_archive.write_bytes(file_bytes)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        temp_archive.unlink(missing_ok=True)
        raise

    try:
        for old_orig in bank_dir.glob("original.*"):
            old_orig.unlink(missing_ok=True)
        temp_archive.replace(bank_dir / f"original{ext}")
    except Exception as e:
        logger.warning("归档文件重命名异常（不影响数据库正常使用）：%s", e)

    return bank


async def latest_attempts(db: AsyncSession, bank_id: str) -> dict[str, BankAttempt]:
    """每题最近一次作答（created_at 升序遍历，后者覆盖）。"""
    attempts = (
        await db.scalars(
            select(BankAttempt)
            .where(BankAttempt.bank_id == bank_id)
            .order_by(BankAttempt.created_at)
        )
    ).all()
    latest: dict[str, BankAttempt] = {}
    for a in attempts:
        latest[a.question_id] = a
    return latest


async def wrong_question_ids(db: AsyncSession, bank_id: str) -> list[str]:
    """错题池：最近一次作答未通过或存疑的题目 id（seq 升序由调用方保证，§2）。"""
    latest = await latest_attempts(db, bank_id)
    return [qid for qid, a in latest.items() if not a.passed or getattr(a, "is_doubtful", False)]


async def bank_stats(db: AsyncSession, bank: QuestionBank) -> dict:
    """题库统计：已答/正确率/错题数/按题型分布（错题池口径 = 最近一次作答未过或存疑）。

    全部在 SQL 内聚合（最近一次作答窗口函数 + GROUP BY），不再把题目全文与全部作答拉入内存。
    """
    # 每题最近一次作答（窗口函数取 rn=1，按时间倒序保证是"最近"而非"最早"）
    rn = func.row_number().over(
        partition_by=BankAttempt.question_id, order_by=BankAttempt.created_at.desc()
    ).label("rn")
    ranked = (
        select(
            BankAttempt.question_id.label("qid"),
            BankAttempt.passed.label("ok"),
            BankAttempt.is_doubtful.label("is_doubtful"),
            rn,
        )
        .where(BankAttempt.bank_id == bank.id)
        .subquery()
    )
    latest = (
        select(ranked.c.qid, ranked.c.ok, ranked.c.is_doubtful).where(ranked.c.rn == 1).subquery().alias("latest")
    )

    # 总作答次数与正确次数（全量 attempt 聚合）
    totals = (
        await db.execute(
            select(
                func.count().label("n"),
                func.sum(case((BankAttempt.passed.is_(True), 1), else_=0)).label("ok"),
            ).where(BankAttempt.bank_id == bank.id)
        )
    ).one()
    total_attempts = int(totals.n or 0)
    correct_attempts = int(totals.ok or 0)

    # 按题聚合最近一次作答结果，再与题目 join 得到统计分布（未通过或存疑计入需重练错题池）
    stats_rows = (
        await db.execute(
            select(
                BankQuestion.qtype.label("qtype"),
                func.count().label("total"),
                func.sum(case((latest.c.qid.isnot(None), 1), else_=0)).label("answered_n"),
                func.sum(
                    case(
                        (or_(latest.c.ok.is_(False), latest.c.is_doubtful.is_(True)), 1),
                        else_=0,
                    )
                ).label("wrong_n"),
                func.sum(
                    case(
                        (and_(latest.c.ok.is_(True), latest.c.is_doubtful.is_(False)), 1),
                        else_=0,
                    )
                ).label("correct_n"),
            )
            .outerjoin(latest, latest.c.qid == BankQuestion.id)
            .where(BankQuestion.bank_id == bank.id)
            .group_by(BankQuestion.qtype)
        )
    ).all()

    question_count = answered = correct_latest = wrong_count = 0
    by_type: dict[str, dict] = {}
    for r in stats_rows:
        qtotal = int(r.total or 0)
        q_answered = int(r.answered_n or 0)
        q_wrong = int(r.wrong_n or 0)
        q_correct = int(r.correct_n or 0)
        question_count += qtotal
        answered += q_answered
        correct_latest += q_correct
        wrong_count += q_wrong
        by_type[r.qtype] = {"total": qtotal, "wrong": q_wrong}

    # new_count 与 draw_round(mode="new") 同口径：指纹去重后从未作答的题数。
    # 否则含重复题的库会出现"看板显示有新题、点击却提示已刷完"的口径分叉
    new_count = question_count
    if question_count and answered:
        # 已作答题 id（来自最近一次作答子查询）
        ans_ids = set(
            (await db.execute(select(latest.c.qid).where(latest.c.qid.isnot(None)))).scalars()
        )
        # 只查指纹所需的轻量列（不拉解析/AI 解析长文本）
        rows2 = (
            await db.execute(
                select(
                    BankQuestion.id,
                    BankQuestion.qtype,
                    BankQuestion.title,
                    BankQuestion.options,
                    BankQuestion.answer,
                ).where(BankQuestion.bank_id == bank.id)
            )
        ).all()
        fp_by_id = {r.id: _question_dedup_key(r) for r in rows2}
        answered_fp = {fp_by_id[q] for q in ans_ids if q in fp_by_id}
        # 按指纹去重计数：与 draw_round("new") 的候选池口径一致（重复题算 1 道）
        new_count = len({key for key in fp_by_id.values() if key not in answered_fp})

    return {
        "question_count": question_count,
        "answered": answered,
        "new_count": new_count,
        "attempts": total_attempts,
        "correct": correct_latest,
        "accuracy": round(correct_attempts / total_attempts * 100, 1) if total_attempts else 0,
        "wrong_count": wrong_count,
        "by_type": by_type,
    }


async def bulk_bank_stats(db: AsyncSession, bank_ids: list[str]) -> dict[str, dict]:
    """批量统计（list_banks 用）：固定 3 条聚合查询 + 内存组装，消除逐库 bank_stats 的 N+1。

    返回 {bank_id: 与 bank_stats 同构的 dict}，口径与单库版一致。
    """
    out: dict[str, dict] = {
        bid: {
            "question_count": 0,
            "answered": 0,
            "new_count": 0,
            "attempts": 0,
            "correct": 0,
            "accuracy": 0,
            "wrong_count": 0,
            "by_type": {},
        }
        for bid in bank_ids
    }
    if not bank_ids:
        return out

    # 1) 全量作答次数/正确次数（GROUP BY bank_id 单条聚合）
    totals = (
        await db.execute(
            select(
                BankAttempt.bank_id.label("bid"),
                func.count().label("n"),
                func.sum(case((BankAttempt.passed.is_(True), 1), else_=0)).label("ok"),
            )
            .where(BankAttempt.bank_id.in_(bank_ids))
            .group_by(BankAttempt.bank_id)
        )
    ).all()
    attempts_by_bank = {r.bid: (int(r.n or 0), int(r.ok or 0)) for r in totals}

    # 2) 每题最近一次作答（窗口函数 rn=1，一次取全部库）
    rn = func.row_number().over(
        partition_by=BankAttempt.question_id, order_by=BankAttempt.created_at.desc()
    ).label("rn")
    ranked = (
        select(
            BankAttempt.bank_id.label("bid"),
            BankAttempt.question_id.label("qid"),
            BankAttempt.passed.label("ok"),
            BankAttempt.is_doubtful.label("is_doubtful"),
            rn,
        )
        .where(BankAttempt.bank_id.in_(bank_ids))
        .subquery()
    )
    latest_rows = (
        await db.execute(
            select(ranked.c.bid, ranked.c.qid, ranked.c.ok, ranked.c.is_doubtful).where(
                ranked.c.rn == 1
            )
        )
    ).all()
    latest_by_bank: dict[str, dict[str, object]] = {}
    for r in latest_rows:
        latest_by_bank.setdefault(r.bid, {})[r.qid] = r

    # 3) 题目轻量列一次拉全（分布/指纹均在内存计算，不拉解析长文本）
    q_rows = (
        await db.execute(
            select(
                BankQuestion.bank_id.label("bid"),
                BankQuestion.id.label("qid"),
                BankQuestion.qtype.label("qtype"),
                BankQuestion.title.label("title"),
                BankQuestion.options.label("options"),
                BankQuestion.answer.label("answer"),
            ).where(BankQuestion.bank_id.in_(bank_ids))
        )
    ).all()
    qs_by_bank: dict[str, list] = {}
    for r in q_rows:
        qs_by_bank.setdefault(r.bid, []).append(r)

    for bid, stats in out.items():
        qs = qs_by_bank.get(bid, [])
        latest = latest_by_bank.get(bid, {})
        stats["question_count"] = len(qs)
        stats["answered"] = len(latest)
        stats["wrong_count"] = sum(
            1 for r in latest.values() if (not r.ok) or getattr(r, "is_doubtful", False)
        )
        stats["correct"] = sum(
            1 for r in latest.values() if r.ok is True and not r.is_doubtful
        )
        by_type: dict[str, dict] = {}
        wrong_ids = {qid for qid, r in latest.items() if (not r.ok) or r.is_doubtful}
        for r in qs:
            slot = by_type.setdefault(r.qtype, {"total": 0, "wrong": 0})
            slot["total"] += 1
            if r.qid in wrong_ids:
                slot["wrong"] += 1
        stats["by_type"] = by_type

        total_attempts, correct_attempts = attempts_by_bank.get(bid, (0, 0))
        stats["attempts"] = total_attempts
        stats["accuracy"] = (
            round(correct_attempts / total_attempts * 100, 1) if total_attempts else 0
        )

        # new_count 与 draw_round("new") 同口径：指纹去重后从未作答的题数
        new_count = len(qs)
        if qs and latest:
            fp_by_id = {r.qid: _question_dedup_key(r) for r in qs}
            answered_fp = {fp_by_id[qid] for qid in latest if qid in fp_by_id}
            new_count = len({key for key in fp_by_id.values() if key not in answered_fp})
        stats["new_count"] = new_count
    return out


def _question_dedup_key(q: BankQuestion) -> tuple:
    """提取题目内容归一化指纹，用于识别完全相同的题目。

    含 answer：题干/选项相同但正确答案不同的变体是不同题目（做新题模式不能跳过）。
    """
    norm_title = " ".join((q.title or "").split())
    norm_opts = ()
    if q.qtype != QUESTION_JUDGE and q.options:
        try:
            raw_opts = json.loads(q.options)
            if isinstance(raw_opts, list):
                norm_opts = tuple(" ".join(str(o).split()) for o in raw_opts if str(o).strip())
        except Exception:
            norm_opts = (" ".join(q.options.split()),)
    return (q.qtype, norm_title, norm_opts, " ".join((q.answer or "").split()))


def _dedup_question_list(questions: list[BankQuestion]) -> list[BankQuestion]:
    """对题目列表按内容指纹去重，保留首次出现的题目，保证同一套题内无重复题。"""
    seen = set()
    unique = []
    for q in questions:
        key = _question_dedup_key(q)
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


async def draw_round(
    db: AsyncSession, bank: QuestionBank, mode: str, size: int
) -> tuple[list[BankQuestion], int]:
    """抽一轮题：(题目列表, 当前模式候选池大小)。

    模式说明：
    - "new": 做新题模式（仅包含从未作答过的新题）
    - "wrong": 错题重刷模式（仅包含当前错题池中的题目）
    - "all" / "random": 做题模式（全量题库随机抽取，含新题与复习题）

    去重保障：
    同一套题内部通过 _dedup_question_list 严格去重，绝不出现完全相同的重复题目。
    """
    all_questions = (
        await db.scalars(
            select(BankQuestion)
            .where(BankQuestion.bank_id == bank.id)
            .order_by(BankQuestion.seq)
        )
    ).all()

    if mode == "wrong":
        wrong_ids = await wrong_question_ids(db, bank.id)
        wrong_id_set = set(wrong_ids)
        wrong_candidates = [q for q in all_questions if q.id in wrong_id_set]
        unique_candidates = _dedup_question_list(wrong_candidates)
    elif mode == "new":
        latest = await latest_attempts(db, bank.id)
        attempted_ids = set(latest.keys())
        attempted_keys = {_question_dedup_key(q) for q in all_questions if q.id in attempted_ids}
        new_candidates = [
            q for q in all_questions
            if q.id not in attempted_ids and _question_dedup_key(q) not in attempted_keys
        ]
        unique_candidates = _dedup_question_list(new_candidates)
    else:  # "all" or "random" 做题模式
        unique_candidates = _dedup_question_list(all_questions)

    pool_size = len(unique_candidates)
    if not unique_candidates:
        return [], 0

    if size and pool_size > size:
        picked = random.sample(unique_candidates, size)
    else:
        picked = list(unique_candidates)
        random.shuffle(picked)

    return picked, pool_size


async def delete_bank(db: AsyncSession, bank: QuestionBank) -> None:
    """级联删除：作答流水 → 题目 → 题库 → 归档目录。

    目录先改名 banks/.trash-{id} 再删：rmtree 中途崩溃不会留下"看似完好"的半删目录。
    全程持写锁防止与并发追加、替换或作答提交冲突。
    """
    async with _bank_lock(bank.id):
        await db.execute(
            BankAttempt.__table__.delete().where(BankAttempt.bank_id == bank.id)
        )
        await db.execute(
            BankQuestion.__table__.delete().where(BankQuestion.bank_id == bank.id)
        )
        await db.delete(bank)
        await db.commit()
        _bank_locks.pop(bank.id, None)

    bank_dir = settings.data_dir / "banks" / bank.id
    trash_dir = settings.data_dir / "banks" / f".trash-{bank.id}"
    if not bank_dir.exists():
        return
    try:
        shutil.rmtree(trash_dir, ignore_errors=True)  # 清掉历史残留的同名回收目录
        bank_dir.rename(trash_dir)
    except OSError as e:
        # 改名失败（如归档被占用）仅记录，直接兜底原地删除，不阻断删除请求
        logger.warning("bank %s archive rename to trash failed: %r", bank.id, e)
        shutil.rmtree(bank_dir, ignore_errors=True)
        return
    shutil.rmtree(trash_dir, ignore_errors=True)


DEFAULT_BANK_AI_PROMPT = load_prompt("bank_default_ai")


def build_explain_messages(
    bank: QuestionBank,
    question: BankQuestion,
    picked_letters: list[str],
    profile_text: str = "",
) -> list[dict]:
    sys_prompt = (bank.ai_prompt or "").strip() or DEFAULT_BANK_AI_PROMPT
    if profile_text and profile_text.strip():
        sys_prompt = f"{sys_prompt}\n\n{profile_text.strip()}"

    options = json.loads(question.options) if question.options else []
    LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"]
    if question.qtype == QUESTION_JUDGE:
        opts_formatted = "A. 正确\nB. 错误"
    else:
        opts_formatted = "\n".join(
            f"{LETTERS[i]}. {opt}" for i, opt in enumerate(options) if opt and opt.strip()
        ) or "（无选项列表）"

    correct_display = format_correct_answer(question)
    type_display = {
        QUESTION_SINGLE: "单选题",
        QUESTION_MULTI: "多选题",
        QUESTION_JUDGE: "判断题",
    }.get(question.qtype, question.qtype)

    if question.qtype == QUESTION_JUDGE:
        student_display = "、".join(
            "正确" if x.upper() == "A" else "错误" if x.upper() == "B" else x
            for x in picked_letters
        ) or "（未选）"
    else:
        student_display = "、".join(sorted(x.upper() for x in picked_letters)) or "（未选）"

    user_content = render_prompt(
        "bank_explain",
        TYPE=type_display,
        TITLE=question.title,
        OPTIONS=opts_formatted,
        CORRECT=correct_display,
        EXPLANATION=question.explanation or "（暂无原题解析）",
        PICKED=student_display,
    )

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]


POLISH_SYSTEM_PROMPT = load_prompt("bank_polish")


async def polish_prompt_with_llm(
    db: AsyncSession, prompt: str, bank_name: str = ""
) -> str:
    source_prompt = prompt.strip() or DEFAULT_BANK_AI_PROMPT
    user_msg = f"题库名称：{bank_name or '综合题库'}\n\n待润色的原提示词：\n{source_prompt}"
    adapter = await create_adapter_from_settings(db, scene="generation")
    result = await adapter.chat([
        {"role": "system", "content": POLISH_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    return result.strip()

