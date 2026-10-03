"""题库刷题 API：导入（analyze/confirm）、抽轮作答、错题池、统计、删除。

独立于课程体系；答案只在提交后由后端下发，抽轮列表永不含 answer/explanation。
"""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.bank import BankAttempt, BankQuestion, QuestionBank
from app.schemas.bank import (
    BankAnalysisOut,
    BankAttemptRequest,
    BankAttemptResult,
    BankOut,
    BankQuestionOut,
    BankRoundOut,
    BankRoundRequest,
    BankSkippedRow,
    BankStatsOut,
    BankWrongQuestionOut,
)
from app.services import bank as bank_service
from app.services.bank import BankParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/banks", tags=["bank"])


def _question_out(q: BankQuestion) -> BankQuestionOut:
    import json

    return BankQuestionOut(
        id=q.id,
        seq=q.seq,
        qtype=q.qtype,
        title=q.title,
        options=json.loads(q.options) if q.options else [],
        difficulty=q.difficulty,
    )


async def _bank_or_404(db: AsyncSession, bank_id: str) -> QuestionBank:
    bank = await db.get(QuestionBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    name = file.filename or "bank.xlsx"
    if not name.lower().endswith(bank_service.BANK_EXTENSIONS):
        raise HTTPException(status_code=400, detail=f"仅支持 .xls / .xlsx 题库文件，收到：{name}")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    return data, name


@router.post("/import/analyze", response_model=BankAnalysisOut)
async def import_analyze(file: UploadFile = File(...)):
    """上传题库 → 解析预览（题数/分布/样题），不下发答案。"""
    data, name = await _read_upload(file)
    try:
        questions, report = bank_service.parse_bank(data, name)
    except BankParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return BankAnalysisOut(
        name=report["name"],
        source_file=report["source_file"],
        question_count=report["question_count"],
        skipped_total=report["skipped_total"],
        skipped=[BankSkippedRow(**s) for s in report["skipped"]],
        by_type=report["by_type"],
        by_difficulty=report["by_difficulty"],
        samples=[_question_out_from_dict(q) for q in questions[:5]],
    )


def _question_out_from_dict(q: dict) -> BankQuestionOut:
    return BankQuestionOut(
        id="",
        seq=q["seq"],
        qtype=q["qtype"],
        title=q["title"],
        options=q["options"],
        difficulty=q["difficulty"],
    )


@router.post("/import", response_model=BankOut)
async def import_confirm(
    file: UploadFile = File(...),
    name: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """确认导入：重新解析上传文件并落库（analyze/confirm 无状态，文件传两次）。"""
    data, file_name = await _read_upload(file)
    try:
        questions, report = bank_service.parse_bank(data, file_name)
    except BankParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if name.strip():
        report["name"] = name.strip()
    bank = await bank_service.create_bank(db, questions, report, data)
    stats = await bank_service.bank_stats(db, bank)
    return BankOut(
        id=bank.id,
        name=bank.name,
        source_file=bank.source_file,
        question_count=bank.question_count,
        created_at=bank.created_at,
        stats=BankStatsOut(**stats),
    )


@router.get("", response_model=list[BankOut])
async def list_banks(db: AsyncSession = Depends(get_db)):
    banks = (
        await db.scalars(select(QuestionBank).order_by(QuestionBank.created_at.desc()))
    ).all()
    out = []
    for b in banks:
        stats = await bank_service.bank_stats(db, b)
        out.append(
            BankOut(
                id=b.id,
                name=b.name,
                source_file=b.source_file,
                question_count=b.question_count,
                created_at=b.created_at,
                stats=BankStatsOut(**stats),
            )
        )
    return out


@router.get("/{bank_id}/stats", response_model=BankStatsOut)
async def bank_stats(bank_id: str, db: AsyncSession = Depends(get_db)):
    bank = await _bank_or_404(db, bank_id)
    return BankStatsOut(**(await bank_service.bank_stats(db, bank)))


@router.post("/{bank_id}/round", response_model=BankRoundOut)
async def draw_round(
    bank_id: str, body: BankRoundRequest, db: AsyncSession = Depends(get_db)
):
    bank = await _bank_or_404(db, bank_id)
    questions, wrong_pool = await bank_service.draw_round(db, bank, body.mode, body.size)
    if not questions:
        detail = (
            f"错题池为空（共 {bank.question_count} 题）"
            if body.mode == "wrong"
            else "题库为空"
        )
        raise HTTPException(status_code=400, detail=detail)
    return BankRoundOut(
        bank_id=bank.id,
        mode=body.mode,
        questions=[_question_out(q) for q in questions],
        wrong_pool_size=wrong_pool,
    )


@router.post("/attempts", response_model=BankAttemptResult)
async def submit_attempt(
    body: BankAttemptRequest, db: AsyncSession = Depends(get_db)
):
    q = await db.get(BankQuestion, body.question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    passed = bank_service.judge_answer(q.qtype, q.answer, body.content)
    attempt = BankAttempt(
        bank_id=q.bank_id,
        question_id=q.id,
        content=",".join(x.strip().upper() for x in body.content if x and x.strip()),
        passed=passed,
    )
    db.add(attempt)
    await db.commit()
    return BankAttemptResult(
        attempt_id=attempt.id,
        passed=passed,
        answer=q.answer,
        correct_answer=bank_service.format_correct_answer(q),
        answer_raw=q.answer_raw,
        explanation=q.explanation,
    )


@router.get("/{bank_id}/wrong", response_model=list[BankWrongQuestionOut])
async def wrong_book(bank_id: str, db: AsyncSession = Depends(get_db)):
    """错题池浏览（含答案与解析）：最近一次作答未通过的题，seq 升序。"""
    bank = await _bank_or_404(db, bank_id)
    wrong_ids = await bank_service.wrong_question_ids(db, bank.id)
    if not wrong_ids:
        return []
    questions = (
        await db.scalars(
            select(BankQuestion)
            .where(BankQuestion.bank_id == bank.id)
            .order_by(BankQuestion.seq)
        )
    ).all()
    import json

    out = []
    for q in questions:
        if q.id not in set(wrong_ids):
            continue
        base = _question_out(q)
        out.append(
            BankWrongQuestionOut(
                **base.model_dump(),
                answer=q.answer,
                answer_raw=q.answer_raw,
                explanation=q.explanation,
            )
        )
    return out


@router.delete("/{bank_id}")
async def delete_bank(bank_id: str, db: AsyncSession = Depends(get_db)):
    bank = await _bank_or_404(db, bank_id)
    await bank_service.delete_bank(db, bank)
    return {"ok": True}
