"""全局搜索 API（FTS5）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services import search as search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(q: str = Query(min_length=1, max_length=100), db: AsyncSession = Depends(get_db)):
    results = await search_service.search(db, q)
    return {"query": q, "results": results}
