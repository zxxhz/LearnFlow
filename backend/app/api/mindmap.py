"""思维导图 RESTful API 与 Agent 流式交互端点。"""
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.mindmap import (    MindMapAgentChatRequest,
    MindMapCreate,
    MindMapDetail,
    MindMapGenerateRequest,
    MindMapImportRequest,
    MindMapNodeDetailRequest,
    MindMapNodeQARequest,
    MindMapSummary,
    MindMapUpdate,
)
from app.services import mindmap as mindmap_service
from app.services.llm.errors import LLMError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mindmaps", tags=["mindmap"])


def _to_detail(m: Any) -> MindMapDetail:
    return MindMapDetail(
        id=m.id,
        title=m.title,
        topic=m.topic,
        root=m.root,
        settings=m.settings,
        source=getattr(m, "source", None) or "manual",
        course_id=getattr(m, "course_id", None),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=list[MindMapSummary])
async def list_mindmaps(db: AsyncSession = Depends(get_db)):
    """获取所有思维导图列表概览。"""
    return await mindmap_service.list_mindmaps(db)


@router.post("", response_model=MindMapDetail)
async def create_mindmap(data: MindMapCreate, db: AsyncSession = Depends(get_db)):
    """新建空白思维导图。"""
    try:
        mm = await mindmap_service.create_mindmap(db, data)
    except ValueError as e:
        # 树深度超限等结构不合法 → 422
        raise HTTPException(status_code=422, detail=str(e))
    return _to_detail(mm)


@router.post("/import", response_model=MindMapDetail)
async def import_mindmap(data: MindMapImportRequest, db: AsyncSession = Depends(get_db)):
    """从 Markdown 大纲或 JSON 字符串导入生成思维导图。"""
    if len(data.content) > 2_000_000:
        raise HTTPException(status_code=422, detail="导入内容过长（上限 200 万字符）")
    raw_content = data.content.strip()
    if not raw_content:
        raise HTTPException(status_code=400, detail="导入内容不可为空")

    tree: dict[str, Any]
    detected_title = data.title.strip()

    is_json = False
    if data.format == "json" or (data.format == "auto" and raw_content.startswith("{")):
        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, dict):
                tree = mindmap_service.normalize_node(
                    parsed.get("root") if "root" in parsed else parsed,
                    detected_title or "导入思维导图"
                )
                if not detected_title and parsed.get("title"):
                    detected_title = str(parsed["title"]).strip()
                is_json = True
        except ValueError:
            raise HTTPException(status_code=422, detail="导入的导图层级超过上限（最多 30 层）")
        except Exception:
            pass

    if not is_json:
        # 按 Markdown 层级大纲解析
        try:
            tree = mindmap_service.parse_markdown_to_tree(raw_content, detected_title)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    final_title = detected_title or tree.get("title") or "导入思维导图"
    tree["title"] = final_title

    create_data = MindMapCreate(
        title=final_title,
        topic="导入知识体系",
        root=tree,
        source="import",
    )
    try:
        mm = await mindmap_service.create_mindmap(db, create_data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_detail(mm)


@router.post("/generate", response_model=MindMapDetail)
async def generate_mindmap(data: MindMapGenerateRequest, db: AsyncSession = Depends(get_db)):
    """通过 AI Agent 根据主题/长文材料/课程内容生成结构化思维导图。

    提供 course_id 时走课程链路（大纲+章节摘要+知识点，材料上限 16000 字符），
    否则要求 prompt 非空走通用主题链路。
    """
    try:
        if data.course_id:
            # 课程生成链路：prompt 可留空，标题/材料均取自课程
            res = await mindmap_service.generate_mindmap_from_course(
                db,
                course_id=data.course_id,
                depth=data.depth,
                include_details=data.include_details,
            )
            course = res["course"]
            create_data = MindMapCreate(
                title=res["title"],
                topic=course.title[:40],
                root=res["root"],
                source="course",
                course_id=course.id,
            )
            mm = await mindmap_service.create_mindmap(db, create_data)
            return _to_detail(mm)

        if not data.prompt.strip():
            raise HTTPException(status_code=400, detail="生成主题提示不可为空")

        res = await mindmap_service.generate_mindmap_tree(
            prompt=data.prompt,
            depth=data.depth,
            import_content=data.import_content,
            db=db,
        )
        create_data = MindMapCreate(
            title=res["title"],
            topic=data.prompt.strip()[:40],
            root=res["root"],
            source="generate",
        )
        mm = await mindmap_service.create_mindmap(db, create_data)
        return _to_detail(mm)
    except HTTPException:
        # 直接上抛（如空 prompt 的 400），避免被下方兜底转成 500
        raise
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMError:
        # 交给全局 llm_error_handler（400 + 中文提示），不得吞掉转 500
        raise
    except ValueError as e:
        # 树深度超限等结构不合法 → 422
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("生成思维导图异常")
        raise HTTPException(status_code=500, detail="AI 生成思维导图失败，请稍后重试")


@router.get("/{mindmap_id}", response_model=MindMapDetail)
async def get_mindmap(mindmap_id: str, db: AsyncSession = Depends(get_db)):
    """获取单张思维导图详情。"""
    mm = await mindmap_service.get_mindmap(db, mindmap_id)
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")
    return _to_detail(mm)


@router.put("/{mindmap_id}", response_model=MindMapDetail)
async def update_mindmap(mindmap_id: str, data: MindMapUpdate, db: AsyncSession = Depends(get_db)):
    """更新思维导图（重命名、保存树修改、视图偏好）。"""
    try:
        mm = await mindmap_service.update_mindmap(db, mindmap_id, data)
    except ValueError as e:
        # 树深度超限等结构不合法 → 422
        raise HTTPException(status_code=422, detail=str(e))
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")
    return _to_detail(mm)


@router.delete("/{mindmap_id}")
async def delete_mindmap(mindmap_id: str, db: AsyncSession = Depends(get_db)):
    """删除思维导图。"""
    ok = await mindmap_service.delete_mindmap(db, mindmap_id)
    if not ok:
        raise HTTPException(status_code=404, detail="思维导图不存在")
    return {"ok": True}


@router.get("/{mindmap_id}/export.json")
async def export_mindmap_json(mindmap_id: str, db: AsyncSession = Depends(get_db)):
    """导出思维导图为 JSON 结构（与导入格式一致，README 承诺的双向 JSON）。"""
    mm = await mindmap_service.get_mindmap(db, mindmap_id)
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")
    import json as _json

    from fastapi.responses import Response

    payload = _json.dumps({"title": mm.title, "topic": mm.topic, "root": mm.root}, ensure_ascii=False, indent=2)
    from urllib.parse import quote

    return Response(
        content=payload,
        media_type="application/json",
    headers={
        # RFC 5987：filename* 值内不允许裸空格，整名一起编码
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{mm.title} mindmap.json')}",
    },
    )


@router.get("/{mindmap_id}/export")
async def export_mindmap_markdown(mindmap_id: str, db: AsyncSession = Depends(get_db)):
    """导出思维导图为格式化 Markdown 大纲文本。"""
    mm = await mindmap_service.get_mindmap(db, mindmap_id)
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")
    md_text = mindmap_service.export_tree_to_markdown(mm.root)
    return {"title": mm.title, "markdown": md_text}


@router.post("/{mindmap_id}/agent")
async def chat_with_mindmap_agent(
    mindmap_id: str,
    data: MindMapAgentChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """思维导图伴学 Agent：自然语言下发增删改查指令，流式返回工具执行过程与解析。"""
    mm = await mindmap_service.get_mindmap(db, mindmap_id)
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")

    async def event_generator():
        try:
            async for ev in mindmap_service.stream_mindmap_agent(
                mindmap=mm,
                user_message=data.message,
                selected_node_id=data.selected_node_id,
                history=data.history,
                db=db,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except LLMError as e:
            # 业务可展示的 LLM 错误：透传中文提示
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("MindMap agent stream error")
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{mindmap_id}/nodes/{node_id}/detail")
async def generate_node_detail_stream(
    mindmap_id: str,
    node_id: str,
    data: MindMapNodeDetailRequest,
    db: AsyncSession = Depends(get_db),
):
    """针对思维导图中的特定节点，流式生成详尽的深度知识剖析。"""
    mm = await mindmap_service.get_mindmap(db, mindmap_id)
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")

    async def event_generator():
        try:
            async for ev in mindmap_service.stream_node_detail(
                mindmap=mm,
                node_id=node_id,
                instruction=data.instruction,
                db=db,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except LLMError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Node detail stream error")
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{mindmap_id}/nodes/{node_id}/qa")
async def node_qa_stream(
    mindmap_id: str,
    node_id: str,
    data: MindMapNodeQARequest,
    db: AsyncSession = Depends(get_db),
):
    """围绕当前节点的上下文展开专属追问问答。"""
    mm = await mindmap_service.get_mindmap(db, mindmap_id)
    if not mm:
        raise HTTPException(status_code=404, detail="思维导图不存在")

    async def event_generator():
        try:
            async for ev in mindmap_service.stream_node_qa(
                mindmap=mm,
                node_id=node_id,
                question=data.question,
                history=data.history,
                db=db,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except LLMError as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': e.message}, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Node QA stream error")
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务异常，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
