"""助教伴学 API：针对练习作答与卡点提供启发式诊断与点拨（SSE 流式）。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Exercise
from app.services.llm import create_adapter_from_settings
from app.services.llm.errors import LLMError
from app.services.tutor import stream_exercise_diagnosis

router = APIRouter(prefix="/tutor", tags=["tutor"])


class ExerciseDiagnoseRequest(BaseModel):
    exercise_id: str
    content: str
    question: str = ""
    mode: str = "socratic"  # socratic / direct


@router.post("/diagnose")
async def diagnose(body: ExerciseDiagnoseRequest, db: AsyncSession = Depends(get_db)):
    if not body.exercise_id:
        raise HTTPException(status_code=400, detail="exercise_id 不能为空")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="作答代码/内容不能为空")

    exercise = await db.get(Exercise, body.exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="练习题不存在")

    adapter = await create_adapter_from_settings(db, scene="chat")

    gen = stream_exercise_diagnosis(
        db,
        exercise=exercise,
        adapter=adapter,
        content=body.content,
        question=body.question,
        mode=body.mode,
    )
    return StreamingResponse(gen, media_type="text/event-stream")


