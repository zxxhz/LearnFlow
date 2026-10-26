"""题库刷题服务：解析 15 列题库表格（.xls/.xlsx）、判分、导入落库、统计派生。

表格布局对齐《浙江省大学生网络与信息安全竞赛题库》（原刷题应用 bank.py 实测验证）：
0 题型 | 1 题干 | 2-9 选项A-H | 10 正确答案 | 11 备用 | 12 解析 | 13 难度
"""
import json
import random
import shutil
from io import BytesIO

from sqlalchemy import and_, case, func, or_, select
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
    """按行产出前 14 列原始单元格；跳过首行表头。"""
    name = filename.lower()
    if name.endswith(".xls"):
        import xlrd

        sh = xlrd.open_workbook(file_contents=data, on_demand=True).sheet_by_index(0)
        for r in range(1, sh.nrows):
            yield r + 1, [sh.cell_value(r, c) for c in range(min(N_COLS, sh.ncols))]
    elif name.endswith(".xlsx"):
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)
        next(rows, None)  # 表头
        for rno, row in enumerate(rows, start=2):
            yield rno, list(row[:N_COLS])
        wb.close()
    else:
        raise BankParseError("仅支持 .xls / .xlsx 题库文件")


def normalize_answer(qtype: str, raw: str, excel_row: int) -> str:
    """答案归一化：single/judge → 单字母；multi → 排序去重大写字母串。"""
    if qtype == QUESTION_JUDGE:
        if raw in _JUDGE_TRUE:
            return JUDGE_OPTIONS[0][0]
        if raw in _JUDGE_FALSE:
            return JUDGE_OPTIONS[1][0]
        raise BankParseError(f"第 {excel_row} 行判断题答案无法识别：{raw!r}")
    letters = sorted({x.strip().upper() for x in raw.split(",") if x.strip()})
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
    await db.commit()

    ext = "." + report["source_file"].rsplit(".", 1)[-1].lower()
    bank_dir = settings.data_dir / "banks" / bank.id
    bank_dir.mkdir(parents=True, exist_ok=True)
    (bank_dir / f"original{ext}").write_bytes(file_bytes)
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
        new_count = sum(1 for key in fp_by_id.values() if key not in answered_fp)

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
    """级联删除：作答流水 → 题目 → 题库 → 归档目录。"""
    await db.execute(
        BankAttempt.__table__.delete().where(BankAttempt.bank_id == bank.id)
    )
    await db.execute(
        BankQuestion.__table__.delete().where(BankQuestion.bank_id == bank.id)
    )
    await db.delete(bank)
    await db.commit()
    shutil.rmtree(settings.data_dir / "banks" / bank.id, ignore_errors=True)


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

