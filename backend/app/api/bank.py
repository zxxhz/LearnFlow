"""题库刷题 API：导入（analyze/confirm）、抽轮作答、错题池、统计、删除。

独立于课程体系；答案只在提交后由后端下发，抽轮列表永不含 answer/explanation；
ai_explanation 仅在该题最近一次作答已通过时随轮下发（未答/答错不预告解析）。
"""
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory, get_db
from app.models.bank import BankAttempt, BankQuestion, QuestionBank
from app.schemas.bank import (
    BankAiExplainIn,
    BankAnalysisOut,
    BankAttemptRequest,
    BankAttemptResult,
    BankAddQuestionsOut,
    BankAddQuestionsRequest,
    BankOut,
    BankPromptPolishIn,
    BankPromptPolishOut,
    BankQuestionOut,
    BankQuestionUpdateIn,
    BankQuestionUpdateOut,
    BankReplaceAnalyzeOut,
    BankRoundOut,
    BankRoundRequest,
    BankSkippedRow,
    BankStatsOut,
    BankUpdateIn,
    BankWrongQuestionOut,
    ParsedTextQuestionItem,
    PasteImportRequest,
    PasteParseRequest,
    PasteParseResponse,
)
from app.services import bank as bank_service
from app.services.bank import BankParseError
from app.services.llm import create_adapter_from_settings
from app.services.prompt import render_prompt
from app.services.profile import (
    MISCONCEPTION_SOURCE_BANK_QUESTION,
    discipline_for_text,
    format_profile_for_prompt,
    trigger_misconception_auto_resolve,
    trigger_profile_evolution,
)
from app.services.llm.errors import LLMError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/banks", tags=["bank"])


def _question_out(q: BankQuestion, include_explanation: bool = False) -> BankQuestionOut:
    """题目出参脱敏：ai_explanation 仅在明确允许时下发（抽轮只给已答对的题）。"""
    import json

    return BankQuestionOut(
        id=q.id,
        seq=q.seq,
        qtype=q.qtype,
        title=q.title,
        options=json.loads(q.options) if q.options else [],
        difficulty=q.difficulty,
        ai_explanation=(q.ai_explanation or "") if include_explanation else "",
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
        ai_prompt=bank.ai_prompt or "",
        created_at=bank.created_at,
        stats=BankStatsOut(**stats),
    )


@router.post("/paste-parse", response_model=PasteParseResponse)
async def paste_parse(body: PasteParseRequest, db: AsyncSession = Depends(get_db)):
    """剪贴板杂乱文本一键智能切题解析（§6）。"""
    raw_text = body.text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="待解析的试题文本不能为空")

    prompt = render_prompt("bank_text_parse")
    adapter = await create_adapter_from_settings(db, scene="generation")
    try:
        parsed = await adapter.chat_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请解析以下试题文本并结构化输出：\n\n{raw_text}"},
            ],
            schema=PasteParseResponse,
        )
    except LLMError as e:
        logger.error("paste parse failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"试题切分解析失败：{e.message}") from e
    except Exception as e:  # noqa: BLE001
        logger.exception("paste parse failed")
        raise HTTPException(status_code=500, detail="试题切分解析失败，请稍后重试") from e

    return parsed


def _format_parsed_questions(questions: list[ParsedTextQuestionItem]) -> list[dict]:
    formatted = []
    for i, q in enumerate(questions, 1):
        title = q.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail=f"第 {i} 题题干不能为空")

        if q.qtype == "judge":
            opts: list[str] = []
            ans = "A" if q.answer.strip().upper() in ("A", "TRUE", "T", "对", "正确", "1", "YES", "√", "是") else "B"
            ans_raw = "正确" if ans == "A" else "错误"
        else:
            raw_opts = [opt.strip() for opt in q.options if opt.strip()]
            if len(raw_opts) < 2:
                raise HTTPException(status_code=400, detail=f"第 {i} 题「{title[:20]}」至少需要提供 2 个非空选项")
            opts = (raw_opts + [""] * 8)[:8]
            # 与文件导入同口径归一化：LLM 切题可能输出 "AC"、"A."、"B，C" 等非规范答案，
            # 不归一会导致 judge_answer 永远判错
            try:
                ans = bank_service.normalize_answer(q.qtype, q.answer.strip(), i)
            except BankParseError as e:
                raise HTTPException(status_code=400, detail=f"第 {i} 题：{e}") from e
            ans_raw = ans

        formatted.append({
            "seq": i,
            "qtype": q.qtype if q.qtype in ("single", "multi", "judge") else "single",
            "title": title,
            "options": opts,
            "answer": ans,
            "answer_raw": ans_raw,
            "difficulty": q.difficulty or "普通",
            "explanation": q.explanation or "",
        })
    return formatted


@router.post("/paste-import", response_model=BankOut)
async def paste_import(body: PasteImportRequest, db: AsyncSession = Depends(get_db)):
    """将剪贴板解析/编辑后的试题列表确认落库为新题库（§6）。"""
    if not body.questions:
        raise HTTPException(status_code=400, detail="导入题目列表不能为空")

    formatted_questions = _format_parsed_questions(body.questions)
    report = {
        "name": body.name.strip() or "剪贴板切题题库",
        "source_file": "clipboard_paste.txt",
    }
    file_bytes = json.dumps([q.model_dump() for q in body.questions], ensure_ascii=False, indent=2).encode("utf-8")
    bank = await bank_service.create_bank(db, formatted_questions, report, file_bytes)
    stats = await bank_service.bank_stats(db, bank)
    return BankOut(
        id=bank.id,
        name=bank.name,
        source_file=bank.source_file,
        question_count=bank.question_count,
        ai_prompt=bank.ai_prompt or "",
        created_at=bank.created_at,
        stats=BankStatsOut(**stats),
    )


@router.post("/{bank_id}/questions", response_model=BankAddQuestionsOut)
async def add_questions(
    bank_id: str,
    body: BankAddQuestionsRequest,
    db: AsyncSession = Depends(get_db),
):
    """向指定已有题库追加一道或多道题目。"""
    bank = await _bank_or_404(db, bank_id)
    if not body.questions:
        raise HTTPException(status_code=400, detail="添加题目列表不能为空")

    formatted = _format_parsed_questions(body.questions)
    added = await bank_service.append_questions(db, bank, formatted)
    return BankAddQuestionsOut(
        ok=True,
        added=added,
        question_count=bank.question_count,
    )


@router.post("/{bank_id}/import-file", response_model=BankAddQuestionsOut)
async def import_file_to_bank(
    bank_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 .xls / .xlsx 表格向已有题库追加题目。"""
    bank = await _bank_or_404(db, bank_id)
    data, file_name = await _read_upload(file)
    try:
        questions, report = bank_service.parse_bank(data, file_name)
    except BankParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not questions:
        raise HTTPException(status_code=400, detail="文件中未解析出有效试题")

    added = await bank_service.append_questions(db, bank, questions)
    return BankAddQuestionsOut(
        ok=True,
        added=added,
        question_count=bank.question_count,
    )


@router.post("/{bank_id}/replace-analyze", response_model=BankReplaceAnalyzeOut)
async def replace_bank_analyze(
    bank_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传新表格对比分析：分析保留已答题目、移出题目与答案校准题，纯分析不写库。"""
    bank = await _bank_or_404(db, bank_id)
    data, file_name = await _read_upload(file)
    try:
        questions, report = bank_service.parse_bank(data, file_name)
    except BankParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not questions:
        raise HTTPException(status_code=400, detail="新表格中未解析出有效试题")

    analysis = await bank_service.analyze_bank_replacement(
        db, bank, questions, file_name, skipped_total=report.get("skipped_total", 0)
    )
    return BankReplaceAnalyzeOut(**analysis)


@router.post("/{bank_id}/replace", response_model=BankOut)
async def replace_bank_confirm(
    bank_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """确认使用新表格全量替换当前题库：继承历史作答记录、重排seq、清理冗余题与作答。"""
    bank = await _bank_or_404(db, bank_id)
    data, file_name = await _read_upload(file)
    try:
        questions, report = bank_service.parse_bank(data, file_name)
    except BankParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not questions:
        raise HTTPException(status_code=400, detail="新表格中未解析出有效试题")

    updated_bank = await bank_service.replace_bank_with_questions(
        db, bank, questions, file_name, data
    )
    stats = await bank_service.bank_stats(db, updated_bank)
    return BankOut(
        id=updated_bank.id,
        name=updated_bank.name,
        source_file=updated_bank.source_file,
        question_count=updated_bank.question_count,
        ai_prompt=updated_bank.ai_prompt or "",
        created_at=updated_bank.created_at,
        stats=BankStatsOut(**stats),
    )


@router.get("", response_model=list[BankOut])
async def list_banks(db: AsyncSession = Depends(get_db)):
    banks = (
        await db.scalars(select(QuestionBank).order_by(QuestionBank.created_at.desc()))
    ).all()
    # 批量统计（3 条聚合查询 + 内存组装），消除逐库 bank_stats 的 N+1
    stats_map = await bank_service.bulk_bank_stats(db, [b.id for b in banks])
    out = []
    for b in banks:
        out.append(
            BankOut(
                id=b.id,
                name=b.name,
                source_file=b.source_file,
                question_count=b.question_count,
                ai_prompt=b.ai_prompt or "",
                created_at=b.created_at,
                stats=BankStatsOut(**stats_map.get(b.id, {})),
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
    questions, pool_size = await bank_service.draw_round(db, bank, body.mode, body.size)
    if not questions:
        if body.mode == "wrong":
            detail = f"错题池为空（共 {bank.question_count} 题）"
        elif body.mode == "new":
            detail = f"新题已全部刷完（题库共 {bank.question_count} 题均已作答过，可选择【做题模式】综合复习）"
        else:
            detail = "题库为空"
        raise HTTPException(status_code=400, detail=detail)
    # 已有 AI 解析仅对"答对过"的题回带（复习时可直接看），未答/答错的不预告
    latest = await bank_service.latest_attempts(db, bank.id)
    outs = [
        _question_out(q, include_explanation=bool(latest.get(q.id) and latest[q.id].passed))
        for q in questions
    ]
    return BankRoundOut(
        bank_id=bank.id,
        mode=body.mode,
        questions=outs,
        wrong_pool_size=pool_size,
    )


@router.post("/attempts", response_model=BankAttemptResult)
async def submit_attempt(
    body: BankAttemptRequest, db: AsyncSession = Depends(get_db)
):
    q = await db.get(BankQuestion, body.question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    async with bank_service._bank_lock(q.bank_id):
        # 锁内重读题目，防止并发替换或修改删除题目导致外键报错
        fresh_q = await db.get(BankQuestion, body.question_id)
        if fresh_q is None:
            raise HTTPException(status_code=404, detail="题目不存在或已被移除")
        q = fresh_q
        passed = bank_service.judge_answer(q.qtype, q.answer, body.content)
        user_ans = ",".join(x.strip().upper() for x in body.content if x and x.strip())
        attempt = BankAttempt(
            bank_id=q.bank_id,
            question_id=q.id,
            content=user_ans,
            passed=passed,
            is_doubtful=body.is_doubtful,
        )
        db.add(attempt)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=404, detail="题目已被更新或删除")

    # 盲区证据闭环：独立做对（未存疑）时自动关闭挂在该题上的盲区
    if passed and not body.is_doubtful:
        trigger_misconception_auto_resolve(MISCONCEPTION_SOURCE_BANK_QUESTION, q.id)

    return BankAttemptResult(
        attempt_id=attempt.id,
        passed=passed,
        is_doubtful=body.is_doubtful,
        user_answer=user_ans,
        answer=q.answer,
        correct_answer=bank_service.format_correct_answer(q),
        answer_raw=q.answer_raw,
        explanation=q.explanation,
        ai_explanation=q.ai_explanation or "",
    )


@router.post("/attempts/{attempt_id}/revoke")
async def revoke_attempt(attempt_id: str, db: AsyncSession = Depends(get_db)):
    """误触撤回：撤销本题最近一次作答（软删 is_revoked=True，统计口径整体排除）。

    仅放行本题当前最近一次作答：撤回后上一条自动回到「最近」位置，可连续撤回
    逐条清掉误触历史；历史中间记录不允许跳着撤，避免「最近一次」口径被绕过。
    """
    att = await db.get(BankAttempt, attempt_id)
    if att is None or att.is_revoked:
        raise HTTPException(status_code=404, detail="作答记录不存在或已撤回")
    async with bank_service._bank_lock(att.bank_id):
        # 锁内重读，防并发撤回/题目替换交错
        fresh = await db.get(BankAttempt, attempt_id)
        if fresh is None or fresh.is_revoked:
            raise HTTPException(status_code=404, detail="作答记录不存在或已撤回")
        latest_id = await db.scalar(
            select(BankAttempt.id)
            .where(
                BankAttempt.question_id == fresh.question_id,
                BankAttempt.is_revoked.is_(False),
            )
            .order_by(BankAttempt.created_at.desc())
            .limit(1)
        )
        if latest_id != fresh.id:
            raise HTTPException(status_code=409, detail="只能撤回本题最近一次作答")
        fresh.is_revoked = True
        await db.commit()
    return {"ok": True, "question_id": fresh.question_id}


@router.get("/{bank_id}/wrong", response_model=list[BankWrongQuestionOut])
async def wrong_book(bank_id: str, db: AsyncSession = Depends(get_db)):
    """错题池浏览（含答案与解析）：最近一次作答未通过或存疑的题，seq 升序。

    与 draw_round("wrong") 同口径：按内容指纹去重，同一道重复题只出现一次。
    """
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
    wrong_id_set = set(wrong_ids)
    wrong_questions = [q for q in questions if q.id in wrong_id_set]
    # 与 services.bank.draw_round("wrong") 同款指纹去重（题库可能含完全相同的重复题）
    unique_wrong = bank_service._dedup_question_list(wrong_questions)  # noqa: SLF001
    import json

    out = []
    for q in unique_wrong:
        base = _question_out(q, include_explanation=True)
        out.append(
            BankWrongQuestionOut(
                **base.model_dump(),
                answer=q.answer,
                answer_raw=q.answer_raw,
                explanation=q.explanation,
            )
        )
    return out


@router.get("/default-prompt")
async def get_default_prompt():
    """获取系统默认的错题答疑 AI 提示词。"""
    return {"default_prompt": bank_service.DEFAULT_BANK_AI_PROMPT}


@router.post("/polish-prompt", response_model=BankPromptPolishOut)
async def polish_bank_prompt(
    body: BankPromptPolishIn, db: AsyncSession = Depends(get_db)
):
    """利用大模型对题库自定义提示词进行深度润色优化。"""
    try:
        polished = await bank_service.polish_prompt_with_llm(
            db, body.prompt, body.bank_name
        )
        return BankPromptPolishOut(polished_prompt=polished)
    except LLMError as e:
        logger.exception("Bank prompt polish failed")
        raise HTTPException(status_code=500, detail=f"AI 润色失败：{e.message}") from e
    except Exception as e:  # noqa: BLE001
        logger.exception("Bank prompt polish failed")
        raise HTTPException(status_code=500, detail="AI 润色失败，请稍后重试") from e


@router.post("/questions/{question_id}/ai-explain")
async def ai_explain_question(
    question_id: str,
    body: BankAiExplainIn,
    db: AsyncSession = Depends(get_db),
):
    """刷题错题 AI 流式深度解答（结合题库提示词、考点剖析与避坑指引）。"""
    q = await db.get(BankQuestion, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    bank = await _bank_or_404(db, q.bank_id)
    # 按题库名称判定学科域：盲区注入按学科过滤 + 证据溯源盖章
    bank_scope = discipline_for_text(bank.name)
    profile_text = await format_profile_for_prompt(db, scope=bank_scope)
    messages = bank_service.build_explain_messages(
        bank, q, body.picked, profile_text=profile_text
    )
    adapter = await create_adapter_from_settings(db, scene="chat")
    deltas = await adapter.chat(messages, stream=True)

    accumulated: list[str] = []

    async def gen():
        try:
            async for delta in deltas:
                accumulated.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        except LLMError as e:
            logger.warning(f"Bank explain LLM error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
            return
        except Exception:  # noqa: BLE001
            logger.exception("Bank explain stream error")
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请稍后重试'}, ensure_ascii=False)}\n\n"
            return
        finally:
            # 与全链路其余 9 处 SSE 释放统一防御写法（v0.5.1 体检 P3）：
            # 底层 close 异常若冒出会跳过 ai_explanation 落库与 done 事件
            try:
                await deltas.aclose()
            except Exception:
                logger.debug("bank explain deltas aclose 异常（忽略）", exc_info=True)

        # 流式顺利结束，持久化到 bank_questions.ai_explanation
        full_text = "".join(accumulated).strip()
        if full_text:
            try:
                async with bank_service._bank_lock(q.bank_id):
                    async with async_session_factory() as save_db:
                        saved_q = await save_db.get(BankQuestion, question_id)
                        # 仅当题目内容与选项未发生变更时才回写，防止陈旧解析覆盖更新后的题目
                        if saved_q and saved_q.answer == q.answer and saved_q.options == q.options:
                            saved_q.ai_explanation = full_text
                            await save_db.commit()
            except Exception as se:
                logger.warning(f"Failed to persist question ai_explanation: {se}")

            # 异步提炼错题特征到学习者画像（盖章学科域与证据来源）
            question_context = f"题库：{bank.name}；题目：{q.title}；错误作答：{'、'.join(body.picked)}"
            trigger_profile_evolution(
                context=question_context,
                interaction=f"AI 解析重点：{full_text[:300]}",
                scope=bank_scope,
                source_type=MISCONCEPTION_SOURCE_BANK_QUESTION,
                source_id=question_id,
            )

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )


@router.patch("/questions/{question_id}", response_model=BankQuestionUpdateOut)
async def update_bank_question(
    question_id: str,
    body: BankQuestionUpdateIn,
    db: AsyncSession = Depends(get_db),
):
    """修改/纠错指定题目（答案、选项、题干、解析），并自动对最新作答记录执行重新判定。"""
    q = await db.get(BankQuestion, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")

    try:
        updated_q, recalibrated_att = await bank_service.update_question(
            db,
            q,
            title=body.title,
            options=body.options,
            answer=body.answer,
            explanation=body.explanation,
            difficulty=body.difficulty,
            recalibrate_attempts=body.recalibrate_attempts,
        )
    except (ValueError, BankParseError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    question_out = BankWrongQuestionOut(
        id=updated_q.id,
        seq=updated_q.seq,
        qtype=updated_q.qtype,
        title=updated_q.title,
        options=json.loads(updated_q.options) if updated_q.options else [],
        difficulty=updated_q.difficulty,
        answer=updated_q.answer,
        answer_raw=updated_q.answer_raw,
        explanation=updated_q.explanation,
        ai_explanation=updated_q.ai_explanation or "",
    )

    recalibrated_result = None
    if recalibrated_att:
        recalibrated_result = BankAttemptResult(
            attempt_id=recalibrated_att.id,
            passed=recalibrated_att.passed,
            is_doubtful=recalibrated_att.is_doubtful,
            user_answer=recalibrated_att.content,
            answer=updated_q.answer,
            correct_answer=bank_service.format_correct_answer(updated_q),
            answer_raw=updated_q.answer_raw,
            explanation=updated_q.explanation,
            ai_explanation=updated_q.ai_explanation or "",
        )

    return BankQuestionUpdateOut(
        ok=True,
        question=question_out,
        recalibrated_result=recalibrated_result,
    )


@router.patch("/{bank_id}")
async def update_bank(
    bank_id: str, body: BankUpdateIn, db: AsyncSession = Depends(get_db)
):
    """更新题库（名称与 AI 自定义答疑提示词）。"""
    bank = await _bank_or_404(db, bank_id)
    if body.name is not None:
        bank.name = body.name
    if body.ai_prompt is not None:
        bank.ai_prompt = body.ai_prompt
    await db.commit()
    await db.refresh(bank)
    stats = await bank_service.bank_stats(db, bank)
    return BankOut(
        id=bank.id,
        name=bank.name,
        source_file=bank.source_file,
        question_count=bank.question_count,
        ai_prompt=bank.ai_prompt or "",
        created_at=bank.created_at,
        stats=BankStatsOut(**stats),
    )


@router.delete("/{bank_id}")
async def delete_bank(bank_id: str, db: AsyncSession = Depends(get_db)):
    bank = await _bank_or_404(db, bank_id)
    await bank_service.delete_bank(db, bank)
    return {"ok": True}

