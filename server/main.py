"""FastAPI 入口主应用。

包含：
1. 静态文件托管（前端构建产物 / SPA 回退路由）。
2. Token 鉴权中间件（RelayAuthMiddleware）。
3. 反向隧道长连接端点 /ws/relay。
4. 数据同步端点 /api/relay/...。
5. 智能路由策略：
   - 数据读取类请求（课程、文档讲义、题库、错题、导图）：优先从云端 SQLite 读取，本地离线也能查看；
   - AI 与大模型请求：接入 dispatch_ai_request 统一调度（支持 cloud 云端直出、local 本地隧道与 auto 平滑降级）；
   - 普通非 AI 请求：本地在线时反向代理，本地离线时友好提示。
"""
import contextlib
import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from server.api_sync import router as sync_router
from server.auth import RelayAuthMiddleware
from server.config import settings
from server.db import relay_db
from server.llm import dispatch_ai_request
from server.tunnel import (
    WorkerOfflineError,
    WorkerRequestTimeoutError,
    handle_relay_websocket,
    tunnel_manager,
)

logger = logging.getLogger("server.main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """服务端生命周期管理。"""
    logger.info("LearnFlow 云端中转服务端正在启动...")
    logger.info("配置端口: %s", settings.port)
    logger.info("AI 执行模式: %s", settings.ai_mode)
    logger.info("服务端内置 LLM 配置就绪: %s (模型: %s)", settings.is_server_llm_configured(), settings.server_llm_model)
    logger.info("Token鉴权启用: %s (强制模式: %s)", settings.is_auth_enabled(), settings.relay_auth_required)
    logger.info("静态资源目录: %s", settings.static_dir)
    logger.info("数据存储目录: %s", settings.data_dir)

    # 初始化云端 SQLite 数据库
    await relay_db.init_db()
    logger.info("云端 SQLite 数据库就绪: %s", relay_db.db_path)

    yield

    logger.info("LearnFlow 云端中转服务端正在关闭...")


app = FastAPI(
    title="LearnFlow Relay Server",
    description="LearnFlow 独立的自建云端中转服务端（Web静态托管、Token鉴权、WebSocket反向隧道、云端AI模式与数据中转）",
    version="1.1.0",
    lifespan=lifespan,
)

# 挂载 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 Token 鉴权中间件
app.add_middleware(RelayAuthMiddleware)

# 挂载数据同步与状态 API 路由
app.include_router(sync_router)


# ----------------------------------------------------
# 1. 反向隧道 WebSocket 接入端点
# ----------------------------------------------------
@app.websocket("/ws/relay")
async def websocket_relay_endpoint(websocket: WebSocket):
    """本地客户端 Worker 反向连接接入点。"""
    await handle_relay_websocket(websocket)


# ----------------------------------------------------
# 2. 探针与基础状态端点
# ----------------------------------------------------
@app.get("/health")
async def health_check():
    """轻量级探针检测。"""
    return {
        "status": "ok",
        "service": "LearnFlow-Relay-Server",
        "worker_online": tunnel_manager.is_worker_online(),
        "ai_mode": settings.ai_mode,
        "auth_enabled": settings.is_auth_enabled(),
    }


# ----------------------------------------------------
# 3. 智能路由：数据优先从云端 SQLite 查询
# ----------------------------------------------------
@app.get("/api/courses")
async def get_courses_list():
    """获取课程列表：优先从云端 SQLite 返回，若为空且本地在线则穿透向本地拉取。"""
    courses = await relay_db.list_courses()
    if courses:
        return courses
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", "/api/courses")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    return []


@app.get("/api/courses/{course_id}")
async def get_course_detail(course_id: str):
    """获取课程详情与大纲章节。"""
    course = await relay_db.get_course(course_id)
    if course:
        return course
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", f"/api/courses/{course_id}")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="课程未在云端找到，且本地节点未在线")


@app.get("/api/documents/{doc_id}/content")
async def get_document_content(doc_id: str):
    """获取文档正文讲义内容。"""
    doc = await relay_db.get_document(doc_id)
    if doc and doc.get("content"):
        return {
            "content": doc["content"],
            "title": doc["title"],
            "version": doc["version"],
            "status": doc["status"],
        }
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", f"/api/documents/{doc_id}/content")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="章节文档内容不存在")


@app.get("/api/banks")
async def get_banks_list():
    """获取题库列表。"""
    banks = await relay_db.list_banks()
    if banks:
        return banks
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", "/api/banks")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    return []


@app.get("/api/banks/{bank_id}")
async def get_bank_detail(bank_id: str):
    """获取单个题库信息。"""
    bank = await relay_db.get_bank(bank_id)
    if bank:
        return bank
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", f"/api/banks/{bank_id}")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="题库不存在")


@app.get("/api/banks/{bank_id}/wrong")
async def get_bank_wrong(bank_id: str):
    """获取题库错题列表。"""
    wrongs = await relay_db.get_bank_wrong_questions(bank_id)
    if wrongs:
        return wrongs
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", f"/api/banks/{bank_id}/wrong")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    return []


@app.get("/api/mindmaps")
async def get_mindmaps_list():
    """获取思维导图列表。"""
    mindmaps = await relay_db.list_mindmaps()
    if mindmaps:
        return mindmaps
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", "/api/mindmaps")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    return []


@app.get("/api/mindmaps/{mindmap_id}")
async def get_mindmap_detail(mindmap_id: str):
    """获取思维导图详情。"""
    mm = await relay_db.get_mindmap(mindmap_id)
    if mm:
        return mm
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", f"/api/mindmaps/{mindmap_id}")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="思维导图不存在")


# ----------------------------------------------------
# 4. 智能路由：AI 生成、助教与沙箱执行（接入 dispatch_ai_request 统一调度）
# ----------------------------------------------------
_AI_KEYWORDS = (
    "ask",
    "chat",
    "tutor",
    "diagnose",
    "agent",
    "solve",
    "photo",
    "regenerate",
    "revise",
    "explain",
    "generate",
    "outline",
    "executions",
)


@app.api_route(
    "/api/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_api_catch_all(request: Request, full_path: str):
    """通用 API 路由穿透转发。

    根据请求性质智能分发：
    1. AI 生成与问答类请求（如 /ask, /chat, /diagnose, /outline 等）：
       进入 dispatch_ai_request 统一调度器（按 cloud/local/auto 模式流式直出或隧道转发）；
    2. 普通非 AI 请求：
       若本地 Worker 在线，通过 tunnel_manager.dispatch_full 反向代理；
       若本地 Worker 离线，返回 503 明确提示。
    """
    path = f"/api/{full_path}"
    accept_header = request.headers.get("accept", "")
    is_stream_expected = "text/event-stream" in accept_header or any(
        path.endswith(kw) for kw in ("ask", "diagnose", "agent", "photo", "regenerate", "detail", "qa")
    )
    is_ai_path = any(kw in path for kw in _AI_KEYWORDS)

    body = await request.body()
    query_params = dict(request.query_params)
    headers = dict(request.headers)

    # 1. AI 类的流式或生成请求：统一进入 dispatch_ai_request
    if is_stream_expected or is_ai_path:
        try:
            stream_iter = dispatch_ai_request(
                method=request.method,
                path=path,
                headers=headers,
                query_params=query_params,
                body=body,
            )
            return StreamingResponse(
                stream_iter,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        except Exception as e:
            logger.error("AI 调度转发异常: %s", e)
            return JSONResponse(status_code=500, content={"detail": f"AI 调度转发异常: {e}"})

    # 2. 普通 REST 请求
    if not tunnel_manager.is_worker_online():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "本地客户端未连接，无法执行此非云端原生操作", "worker_online": False},
        )

    try:
        status_code, resp_headers, resp_body = await tunnel_manager.dispatch_full(
            method=request.method,
            path=path,
            headers=headers,
            query_params=query_params,
            body=body,
        )
        return Response(
            content=resp_body,
            status_code=status_code,
            media_type=resp_headers.get("content-type", "application/json"),
        )
    except WorkerOfflineError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "本地 AI 节点已断开连接", "worker_online": False},
        )
    except WorkerRequestTimeoutError:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={"detail": "转发本地节点处理超时"},
        )
    except Exception as e:
        logger.error("反向代理通用请求异常: %s", e)
        return JSONResponse(status_code=500, content={"detail": f"中转转发请求异常: {e}"})


# ----------------------------------------------------
# 5. 静态文件托管与 SPA 前端路由回退
# ----------------------------------------------------
def _render_welcome_page() -> str:
    """当 static_dir 未构建前端产物时，提供友好的服务端在线欢迎页。"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LearnFlow 云端中转服务端 · 运行中</title>
    <style>
        body {
            margin: 0; padding: 24px; min-height: 100vh; display: flex;
            align-items: center; justify-content: center; background: #0f172a;
            color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .box {
            background: #1e293b; border: 1px solid #334155; border-radius: 16px;
            padding: 36px 32px; max-width: 520px; width: 100%; box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }
        h1 { margin-top: 0; font-size: 22px; color: #38bdf8; display: flex; align-items: center; gap: 10px; }
        p { color: #94a3b8; font-size: 14px; line-height: 1.6; }
        .tag { background: #0369a1; color: #e0f2fe; padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; }
        code { background: #0b1120; padding: 2px 6px; border-radius: 4px; color: #38bdf8; font-size: 13px; }
        .api-list { margin: 18px 0; background: #0b1120; border-radius: 10px; padding: 14px; font-size: 13px; }
        .api-list div { padding: 4px 0; display: flex; justify-content: space-between; }
        .api-list a { color: #38bdf8; text-decoration: none; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🚀 LearnFlow 云端中转服务 <span class="tag">正常运行中</span></h1>
        <p>自建中转服务端已就绪！支持云端大模型模式（Cloud AI）、反向隧道（Local AI）以及本地与云端数据双向同步。</p>
        <div class="api-list">
            <div><span>系统状态：</span><a href="/api/relay/status" target="_blank">/api/relay/status</a></div>
            <div><span>AI 模式状态：</span><a href="/api/relay/ai-mode" target="_blank">/api/relay/ai-mode</a></div>
            <div><span>健康探针：</span><a href="/api/relay/health" target="_blank">/api/relay/health</a></div>
            <div><span>WebSocket 隧道：</span><span>/ws/relay</span></div>
        </div>
        <p style="font-size: 12px; color: #64748b;">
            前端静态产物提示：若需在此直接访问 Web 页面，请执行 <code>cd frontend && pnpm build</code> 生成静态页面。
        </p>
    </div>
</body>
</html>"""


@app.get("/{static_file:path}")
async def serve_static_or_spa(static_file: str):
    """静态文件托管与 SPA 单页回退。"""
    static_root = settings.static_dir.resolve()
    target_path = (static_root / static_file).resolve()

    # 安全检查：防止路径遍历
    try:
        target_path.relative_to(static_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")

    # 1. 尝试直接提供具体静态文件
    if target_path.is_file():
        media_type, _ = mimetypes.guess_type(str(target_path))
        return FileResponse(target_path, media_type=media_type)

    # 2. SPA 回退：尝试返回 index.html
    index_html = static_root / "index.html"
    if index_html.is_file():
        return FileResponse(index_html, media_type="text/html")

    # 3. 若前端未构建 index.html，返回服务端在线欢迎页
    return HTMLResponse(content=_render_welcome_page())


def run():
    """CLI 启动命令入口。"""
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
