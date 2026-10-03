"""随堂小测 API：跨知识点组卷 / 查看得分 / 删除。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.exercise import QuizGenerateRequest, QuizOut
from app.services import quiz as quiz_service
from app.services.llm.errors import LLMError

router = APIRouter(prefix="/quizzes", tags=["quiz"])


@router.post("/generate", response_model=QuizOut)
async def generate(body: QuizGenerateRequest, db: AsyncSession = Depends(get_db)):
    try:
        quiz = await quiz_service.generate_quiz(
            db, body.document_id, body.kp_ids, body.language, body.per_kp
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except LLMError:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    quizzes = await quiz_service.list_quizzes(db, body.document_id)
    return next(q for q in quizzes if q.id == quiz.id)


@router.get("", response_model=list[QuizOut])
async def list_quizzes(document_id: str, db: AsyncSession = Depends(get_db)):
    return await quiz_service.list_quizzes(db, document_id)


@router.delete("/{quiz_id}")
async def remove(quiz_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await quiz_service.delete_quiz(db, quiz_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}
