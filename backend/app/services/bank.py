"""题库刷题服务：解析 15 列题库表格（.xls/.xlsx）、判分、导入落库、统计派生。

表格布局对齐《浙江省大学生网络与信息安全竞赛题库》（原刷题应用 bank.py 实测验证）：
0 题型 | 1 题干 | 2-9 选项A-H | 10 正确答案 | 11 备用 | 12 解析 | 13 难度
"""
import json
import random
import shutil
from io import BytesIO

from sqlalchemy import select
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
    """错题池：最近一次作答未通过的题目 id（seq 升序由调用方保证）。"""
    latest = await latest_attempts(db, bank_id)
    return [qid for qid, a in latest.items() if not a.passed]


async def bank_stats(db: AsyncSession, bank: QuestionBank) -> dict:
    """题库统计：已答/正确率/错题数/按题型分布（错题池口径 = 最近一次作答）。"""
    questions = (
        await db.scalars(select(BankQuestion).where(BankQuestion.bank_id == bank.id))
    ).all()
    qmap = {q.id: q for q in questions}
    attempts = (
        await db.scalars(select(BankAttempt).where(BankAttempt.bank_id == bank.id))
    ).all()
    latest = {}
    for a in sorted(attempts, key=lambda x: x.created_at):
        latest[a.question_id] = a

    wrong_ids = {qid for qid, a in latest.items() if not a.passed}
    by_type: dict[str, dict] = {}
    for q in questions:
        slot = by_type.setdefault(q.qtype, {"total": 0, "wrong": 0})
        slot["total"] += 1
        if q.id in wrong_ids:
            slot["wrong"] += 1

    total_attempts = len(attempts)
    correct_attempts = sum(1 for a in attempts if a.passed)
    return {
        "question_count": len(questions),
        "answered": len(latest),
        "attempts": total_attempts,
        "correct": sum(1 for a in latest.values() if a.passed),
        "accuracy": round(correct_attempts / total_attempts * 100, 1) if total_attempts else 0,
        "wrong_count": len(wrong_ids),
        "by_type": by_type,
    }


async def draw_round(
    db: AsyncSession, bank: QuestionBank, mode: str, size: int
) -> tuple[list[BankQuestion], int]:
    """抽一轮题：(题目列表, 错题池大小)。mode = random | wrong。"""
    if mode == "wrong":
        wrong_ids = await wrong_question_ids(db, bank.id)
        pool_size = len(wrong_ids)
        id_set = set(wrong_ids[:size]) if size else set(wrong_ids)
        questions = (
            await db.scalars(
                select(BankQuestion)
                .where(BankQuestion.bank_id == bank.id)
                .order_by(BankQuestion.seq)
            )
        ).all()
        picked = [q for q in questions if q.id in id_set]
    else:
        all_questions = (
            await db.scalars(
                select(BankQuestion)
                .where(BankQuestion.bank_id == bank.id)
                .order_by(BankQuestion.seq)
            )
        ).all()
        pool_size = len(all_questions)
        picked = random.sample(all_questions, min(size, len(all_questions)))
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


DEFAULT_BANK_AI_PROMPT = """你是一位资深、启发式且富有耐心的金牌名师。学生在刷题练习中做错了这道题，请针对该题提供循序渐进、透彻清晰的错题解析与答疑辅导。

请按以下结构进行输出：
1. 【核心考点】：简明扼要指出本题考查的核心知识点与概念定义。
2. 【错因诊断】：深入分析学生选择错误选项的思维误区与常见思维陷阱。
3. 【详解推导】：一步步严密推导正确答案的得出过程，逻辑清晰通俗易懂。
4. 【举一反三】：总结解题口诀或同类题目的秒杀与避坑技巧。

要求：
- 语言生动亲切，富有鼓励性；
- 数学/物理/化学公式使用规范的 LaTeX 语法（行内 $...$，行间 $$...$$）；
- 使用清晰的 Markdown 结构与分级标题。"""


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

    user_content = f"""【题目信息】
- 题型：{type_display}
- 题干：{question.title}
- 选项列表：
{opts_formatted}
- 正确答案：{correct_display}
- 原题参考解析：{question.explanation or "（暂无原题解析）"}

【学生作答情况】
- 学生选了：{student_display}（回答错误）

请根据系统设定的指导原则与角色，针对本题及学生的做错情况进行详细解析和思维辅导。"""

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]


POLISH_SYSTEM_PROMPT = """你是一位顶尖的 AI 提示词工程专家（Prompt Engineer）和资深教学督导。
你的任务是将用户提供的「题库 AI 错题解答提示词」进行深度润色与结构化优化。

优化目标：
1. 明确名师角色定位与答疑教学风格（耐心、启发式、通俗严谨）；
2. 规范输出模块结构（如：核心考点、错因诊断、详解推导、避坑与举一反三技巧等）；
3. 规范数学/科学公式（必须要求 LaTeX 格式 $...$ 与 $$...$$）和清晰的 Markdown 排版；
4. 保持语言精炼、直指核心，指令清晰明确，便于大语言模型严格遵循。

注意：
- 只输出润色优化后的 Prompt 正文内容；
- 严禁包含任何前缀、附带说明或外层引号（例如不要输出“以下是润色后的内容：”）。"""


async def polish_prompt_with_llm(
    db: AsyncSession, prompt: str, bank_name: str = ""
) -> str:
    from app.services.llm import create_adapter_from_settings

    source_prompt = prompt.strip() or DEFAULT_BANK_AI_PROMPT
    user_msg = f"题库名称：{bank_name or '综合题库'}\n\n待润色的原提示词：\n{source_prompt}"
    adapter = await create_adapter_from_settings(db, scene="generation")
    result = await adapter.chat([
        {"role": "system", "content": POLISH_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    return result.strip()

