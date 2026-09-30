from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import CodeExecution, Document, Section
from app.models.base import utcnow_iso
from app.schemas.execution import CodeExecutionOut, CodeRunRequest
from app.services.execution.runner import run_code

router = APIRouter(tags=["execution"])


@router.post("/executions", response_model=CodeExecutionOut)
async def run(body: CodeRunRequest, db: AsyncSession = Depends(get_db)):
    """运行文档代码块并持久化结果（PRD FR-5.8：结果与文档位置绑定）。"""
    doc = await db.get(Document, body.document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    sec = (
        await db.scalars(
            select(Section).where(
                Section.document_id == body.document_id, Section.id == body.section_id
            )
        )
    ).first()
    if sec is None:
        raise HTTPException(status_code=400, detail="代码块位置无效，请刷新页面后重试")

    result = await run_code(body.language, body.code)
    row = CodeExecution(
        document_id=body.document_id,
        section_id=body.section_id,
        document_version=doc.version,
        language=body.language,
        code=body.code,
        created_at=utcnow_iso(),
        **result,
    )
    db.add(row)
    await db.commit()
    return CodeExecutionOut.model_validate(row)


@router.get("/documents/{document_id}/executions", response_model=list[CodeExecutionOut])
async def list_executions(document_id: str, db: AsyncSession = Depends(get_db)):
    """该文档的执行历史（每块返回最新一条，供阅读器回显）。"""
    rows = (
        await db.scalars(
            select(CodeExecution)
            .where(CodeExecution.document_id == document_id)
            .order_by(CodeExecution.created_at.desc())
            .limit(200)
        )
    ).all()
    latest: dict[str, CodeExecution] = {}
    for r in rows:
        latest.setdefault(r.section_id, r)  # 已按时间倒序，首个即最新
    return [CodeExecutionOut.model_validate(r) for r in latest.values()]
