import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import FeynmanSession, Message
from app.schemas.feynman import FeynmanSessionDetailOut, FeynmanSessionOut
from app.services import feynman as feynman_service
from app.services.llm.errors import LLMError

router = APIRouter(prefix="/feynman", tags=["feynman"])


def _session_out(s: FeynmanSession) -> FeynmanSessionOut:
    return FeynmanSessionOut.model_validate(s)


async def _detail_out(db: AsyncSession, s: FeynmanSession) -> FeynmanSessionDetailOut:
    messages = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == s.conversation_id)
            .order_by(Message.created_at)
        )
    ).all()
    out = FeynmanSessionDetailOut.model_validate(s)
    from app.schemas.conversation import MessageOut

    out.messages = [MessageOut.model_validate(m) for m in messages]
    return out


@router.post("/sessions", response_model=FeynmanSessionDetailOut)
async def create_session(body: dict, db: AsyncSession = Depends(get_db)):
    kp_id = body.get("knowledge_point_id")
    explanation = (body.get("explanation") or "").strip()
    if not kp_id or not explanation:
        raise HTTPException(status_code=400, detail="请填写要讲解的内容")
    try:
        session = await feynman_service.start_session(db, kp_id, explanation)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMError:
        raise
    return await _detail_out(db, session)


@router.get("/sessions", response_model=list[FeynmanSessionOut])
async def list_sessions(
    knowledge_point_id: str | None = None, db: AsyncSession = Depends(get_db)
):
    stmt = select(FeynmanSession).order_by(FeynmanSession.updated_at.desc())
    if knowledge_point_id:
        stmt = stmt.where(FeynmanSession.knowledge_point_id == knowledge_point_id)
    sessions = (await db.scalars(stmt)).all()
    return [_session_out(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=FeynmanSessionDetailOut)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await db.get(FeynmanSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="费曼会话不存在")
    return await _detail_out(db, session)


@router.post("/sessions/{session_id}/evaluate", response_model=FeynmanSessionDetailOut)
async def evaluate(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        session = await feynman_service.evaluate_session(db, session_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMError:
        raise
    return await _detail_out(db, session)


@router.get("/kp-context/{kp_id}")
async def kp_context(kp_id: str, db: AsyncSession = Depends(get_db)):
    try:
        ctx = await feynman_service.kp_context(db, kp_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    kp = ctx["knowledge_point"]
    return {
        "knowledge_point": {
            "id": kp.id,
            "document_id": kp.document_id,
            "title": kp.title,
            "summary": kp.summary,
            "section_ids": json.loads(kp.section_ids) if kp.section_ids else [],
            "tags": json.loads(kp.tags) if kp.tags else [],
            "created_at": kp.created_at,
        },
        "document_id": ctx["document_id"],
        "document_title": ctx["document_title"],
        "course_id": ctx["course_id"],
        "course_title": ctx["course_title"],
    }
