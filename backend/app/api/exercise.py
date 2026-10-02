from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.exercise import (
    ExerciseAttemptOut,
    ExerciseGenerateRequest,
    ExerciseOut,
    ExerciseSubmitRequest,
)
from app.services import exercise as exercise_service
from app.services.llm.errors import LLMError

router = APIRouter(prefix="/exercises", tags=["exercise"])


@router.post("/generate", response_model=list[ExerciseOut])
async def generate(body: ExerciseGenerateRequest, db: AsyncSession = Depends(get_db)):
    try:
        rows = await exercise_service.generate_for_kp(
            db, body.knowledge_point_id, body.language, body.count
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMError:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [ExerciseOut.model_validate(r) for r in rows]


@router.get("", response_model=list[ExerciseOut])
async def list_exercises(document_id: str, db: AsyncSession = Depends(get_db)):
    return await exercise_service.list_for_document(db, document_id)


@router.post("/{exercise_id}/submit", response_model=ExerciseAttemptOut)
async def submit(exercise_id: str, body: ExerciseSubmitRequest, db: AsyncSession = Depends(get_db)):
    try:
        attempt = await exercise_service.submit(db, exercise_id, body.content)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMError:
        raise
    return ExerciseAttemptOut.model_validate(attempt)


@router.delete("/{exercise_id}")
async def remove(exercise_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await exercise_service.delete_exercise(db, exercise_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}
