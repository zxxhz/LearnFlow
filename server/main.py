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
import json
import logging
import mimetypes
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from server.api_sync import router as sync_router
from server.api_system import router as system_router
from server.auth import RelayAuthMiddleware, extract_token_from_scope, verify_token
from server.config import settings
from server.db import relay_db
from server.llm import dispatch_ai_request, server_llm_service
from server.prompt import DEFAULT_BANK_AI_PROMPT, build_server_explain_messages
from server.tunnel import (
    WorkerOfflineError,
    WorkerRequestTimeoutError,
    handle_relay_websocket,
    tunnel_manager,
)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Type": "text/event-stream; charset=utf-8",
}


class BankRoundRequest(BaseModel):
    mode: str = "all"
    size: int = 20


class BankAttemptRequest(BaseModel):
    question_id: str
    content: list[str] = Field(default_factory=list)
    is_doubtful: bool = False


class BankExplainRequest(BaseModel):
    picked: list[str] = Field(default_factory=list)

logger = logging.getLogger("server.main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class _TokenLogFilter(logging.Filter):
    """访问日志 token 脱敏（v0.5.8 全量体检 P1-2）：对齐本地后端 _TokenLogFilter。

    旧客户端兼容路径仍接受 ?token=...，该共享令牌此前会完整落 uvicorn access log /
    反代 / Docker 日志——任何能读到日志的一方即获得云端全部读写权。"""
    _TOKEN_RE = re.compile(r"([?&])token=[^&\s]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if "token=" in msg:
                record.msg = self._TOKEN_RE.sub(r"\1token=***", msg)
                record.args = None
        except Exception:  # noqa: BLE001
            pass
        return True


logging.getLogger("uvicorn.access").addFilter(_TokenLogFilter())


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

# 挂载 CORS 中间件（v0.5.8 全量体检 P3-1）：allow_origins=['*'] 与
# allow_credentials=True 组合是反模式——cookie 一旦调整为 SameSite=None 或关闭
# 鉴权，任意网页即可携带凭据跨源读写全部 API。本服务只被自家 SPA 同源访问，
# 默认不放开任何跨源；确有需要经 CORS_ORIGINS 环境变量显式白名单
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=bool(settings.cors_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["x-server-token", "x-access-token", "content-type"],
)

# 挂载 Token 鉴权中间件
app.add_middleware(RelayAuthMiddleware)


class SecurityHeadersMiddleware:
    """安全响应头（v0.5.8 全量体检 P3-2）：对齐本地后端 _SecurityHeaders 基线。

    SPA 为 Vite 产物（无内联脚本），script-src 'self' 收紧；auth 录入页含内联
    JS 且自行携带宽松 CSP，此处对已有 CSP 的响应不覆盖。最后 add（最外层），
    使鉴权页短路响应同样经过这里。"""

    _CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}

                def _add(name: bytes, value: bytes) -> None:
                    if name not in existing:
                        headers.append((name, value))

                _add(b"x-content-type-options", b"nosniff")
                _add(b"referrer-policy", b"no-referrer")
                _add(b"x-frame-options", b"DENY")
                content_type = next(
                    (v for k, v in headers if k.lower() == b"content-type"), b""
                )
                if b"text/html" in content_type.lower():
                    _add(b"content-security-policy", self._CSP.encode("latin-1"))
                    _add(b"permissions-policy", b"camera=(), microphone=(), geolocation=()")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# 最后挂载 = 最外层：鉴权页 / SPA / API 全部响应都带上安全头
app.add_middleware(SecurityHeadersMiddleware)

# 挂载数据同步与状态 API 路由
app.include_router(sync_router)
app.include_router(system_router)


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


@app.post("/auth/verify")
async def auth_verify(request: Request):
    """鉴权表单校验成功后由服务端下发 HttpOnly Cookie。

    A3（v0.5.10 体检）：JS 的 document.cookie 无法覆盖 query 兼容路径此前落下的
    同名 HttpOnly Cookie——令牌轮换后旧 Cookie 失效，新令牌经 JS 写入被静默拒绝，
    用户死循环卡在录入页。现由本端点（经 x-server-token 头携带候选令牌，由
    鉴权中间件先行校验）以 Set-Cookie 服务端覆盖，再由前端 reload。
    """
    token, _source = extract_token_from_scope(request.scope)
    if not verify_token(token):
        # 中间件已拦 401，防御性兜底
        raise HTTPException(status_code=401, detail="访问令牌错误或已失效")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        "lf_server_token",
        token,
        max_age=2592000,
        path="/",
        samesite="lax",
        httponly=True,
        secure=request.url.scheme == "https",
    )
    return resp


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
    """获取文档正文讲义内容。

    返回结构与桌面端 DocumentContentOut 严格对齐：
    { document: {...}, markdown: str, blocks: [] }，
    否则纯 Web 阅读器读 document.* / blocks.length 会直接崩溃。
    """
    doc = await relay_db.get_document(doc_id)
    if doc and doc.get("content"):
        return {
            "document": {
                "id": doc["id"],
                "course_id": doc.get("course_id", ""),
                "chapter_index": doc.get("chapter_index", 0),
                "title": doc.get("title", ""),
                "version": doc.get("version", 1),
                "status": doc.get("status", "done"),
                "source": doc.get("source", "generated"),
                "summary": doc.get("summary"),
                "updated_at": doc.get("updated_at", ""),
            },
            "markdown": doc["content"],
            "blocks": [],  # 云端未存逐段索引，阅读器按整篇 markdown 渲染
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


@app.get("/api/banks/default-prompt")
async def get_default_bank_prompt():
    """获取系统默认的错题答疑 AI 提示词（须先于 /api/banks/{bank_id} 静态注册防路由截断）。"""
    return {"default_prompt": DEFAULT_BANK_AI_PROMPT}


@app.post("/api/banks/polish-prompt")
async def polish_bank_prompt(request: Request):
    """润色题库 AI 提示词。"""
    body = await request.json()
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "POST", "/api/banks/polish-prompt", body=json.dumps(body).encode("utf-8")
            )
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception as e:
            # P1-1：吞异常会让「隧道转发本地」分支静默失效且无任何告警，必须留痕
            logger.warning("polish-prompt 隧道转发本地失败，回退云端: %s", e)

    if not settings.is_server_llm_configured():
        raise HTTPException(status_code=400, detail="服务端尚未配置大模型，请在设置中配置 SERVER_LLM_API_KEY")

    prompt = (body.get("prompt") or "").strip() or DEFAULT_BANK_AI_PROMPT
    bank_name = (body.get("bank_name") or "").strip()
    system_prompt = "你是一位精通教学大纲与试题解析的资深教研专家，擅长优化大模型题库解析提示词。"
    user_msg = f"题库名称：{bank_name or '综合题库'}\n\n待润色的原提示词：\n{prompt}\n\n请输出一段结构严密、去AI腔且富含针对性教学引导规则的高质量题库解析系统提示词。"
    accumulated = []
    async for delta in server_llm_service.stream_chat([{"role": "user", "content": user_msg}], system_prompt=system_prompt):
        accumulated.append(delta)
    return {"polished_prompt": "".join(accumulated).strip()}


@app.post("/api/banks/attempts")
async def submit_bank_attempt(body: BankAttemptRequest):
    """提交作答并即时判分（服务端独立运行直接判题落库，离线与多端同步全闭环）。"""
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "POST", "/api/banks/attempts", body=json.dumps(body.model_dump()).encode("utf-8")
            )
            # 本地成功后云端也备份落库（保证离线与双向同步数据一致）
            try:
                await relay_db.submit_bank_attempt(body.question_id, body.content, body.is_doubtful)
            except Exception as e:
                logger.warning("作答云端备份落库失败（不影响本地结果）: %s", e)
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception as e:
            logger.warning("作答隧道转发本地失败，回退云端判分: %s", e)

    try:
        result = await relay_db.submit_bank_attempt(body.question_id, body.content, body.is_doubtful)
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


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


@app.get("/api/banks/{bank_id}/stats")
async def get_bank_stats(bank_id: str):
    """获取单个题库做题统计数据。"""
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "GET", f"/api/banks/{bank_id}/stats"
            )
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception:
            pass

    stats = await relay_db.get_bank_stats(bank_id)
    if stats is not None:
        return stats
    raise HTTPException(status_code=404, detail="题库不存在")


@app.post("/api/banks/{bank_id}/round")
async def draw_bank_round(bank_id: str, body: BankRoundRequest):
    """题库抽题组轮（支持做新题、做题、错题重刷、随机模式；服务端独立运行可直接开刷）。"""
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "POST", f"/api/banks/{bank_id}/round", body=json.dumps(body.model_dump()).encode("utf-8")
            )
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception as e:
            logger.warning("抽题轮隧道转发本地失败，回退云端原生抽题: %s", e)

    questions, pool_size, bank = await relay_db.draw_bank_round(bank_id, body.mode, body.size)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")
    if not questions:
        if body.mode == "wrong":
            detail = f"错题池为空（共 {bank.get('question_count', 0)} 题）"
        elif body.mode == "new":
            detail = f"新题已全部刷完（题库共 {bank.get('question_count', 0)} 题均已作答过，可选择【做题模式】综合复习）"
        else:
            detail = "题库为空"
        raise HTTPException(status_code=400, detail=detail)

    return {
        "bank_id": bank_id,
        "mode": body.mode,
        "questions": questions,
        "wrong_pool_size": pool_size,
    }


@app.post("/api/banks/questions/{question_id}/ai-explain")
async def ai_explain_bank_question(question_id: str, body: BankExplainRequest, request: Request):
    """刷题错题 AI 流式深度解答（服务端独立运行时利用服务端配置的 LLM 直出）。"""
    mode = (settings.ai_mode or "auto").lower()
    body_bytes = json.dumps(body.model_dump()).encode("utf-8")

    if mode in ("local", "auto") and tunnel_manager.is_worker_online():
        try:
            stream_iter = tunnel_manager.dispatch_request(
                method="POST",
                path=f"/api/banks/questions/{question_id}/ai-explain",
                headers=dict(request.headers),
                body=body_bytes,
            )
            return StreamingResponse(
                stream_iter,
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )
        except Exception as e:
            if mode == "local":
                raise HTTPException(status_code=503, detail=f"本地节点调用失败: {e}")
            logger.warning("本地 Worker 异常，回退云端 LLM: %s", e)

    if not settings.is_server_llm_configured():
        raise HTTPException(status_code=400, detail="服务端尚未配置大模型，请在设置中配置 SERVER_LLM_API_KEY")

    q = await relay_db.get_question_by_id(question_id)
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    bank = await relay_db.get_bank(q["bank_id"]) or {}

    sys_prompt, messages = build_server_explain_messages(bank, q, body.picked)
    accumulated: list[str] = []

    async def gen():
        try:
            async for delta in server_llm_service.stream_chat(messages, system_prompt=sys_prompt):
                accumulated.append(delta)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"
            return

        full_text = "".join(accumulated).strip()
        if full_text:
            try:
                await relay_db.save_question_ai_explanation(question_id, full_text)
            except Exception as e:
                logger.warning("缓存云端 AI 解析失败: %s", e)

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.patch("/api/banks/questions/{question_id}")
async def update_bank_question(question_id: str, request: Request):
    """更新题目内容或答案（纠错改题）。"""
    body = await request.json()
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "PATCH", f"/api/banks/questions/{question_id}", body=json.dumps(body).encode("utf-8")
            )
            try:
                await relay_db.update_bank_question(question_id, body)
            except Exception as e:
                logger.warning("改题云端备份失败（不影响本地结果）: %s", e)
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception as e:
            logger.warning("改题隧道转发本地失败，回退云端原生改题: %s", e)

    try:
        return await relay_db.update_bank_question(question_id, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.patch("/api/banks/{bank_id}")
async def update_bank(bank_id: str, request: Request):
    """更新题库名称或自定义 AI 提示词。"""
    body = await request.json()
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "PATCH", f"/api/banks/{bank_id}", body=json.dumps(body).encode("utf-8")
            )
            if "ai_prompt" in body:
                try:
                    await relay_db.update_bank_prompt(bank_id, str(body["ai_prompt"]))
                except Exception as e:
                    logger.warning("题库提示词云端备份失败（不影响本地结果）: %s", e)
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception as e:
            logger.warning("题库更新隧道转发本地失败，回退云端: %s", e)

    if "ai_prompt" in body:
        ok = await relay_db.update_bank_prompt(bank_id, str(body["ai_prompt"]))
        if not ok:
            raise HTTPException(status_code=404, detail="题库不存在")
    bank = await relay_db.get_bank(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


@app.post("/api/study/ping")
async def study_ping(request: Request):
    """记录学习打点时长（在线/离线通用）。"""
    try:
        body = await request.json()
        sec = int(body.get("seconds", 30))
        if 0 < sec <= 300:
            await relay_db.record_study_ping(sec)
    except Exception:
        pass
    if tunnel_manager.is_worker_online():
        try:
            await tunnel_manager.dispatch_full("POST", "/api/study/ping", body=await request.body())
        except Exception:
            pass
    return {"ok": True}


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


@app.get("/api/settings")
async def get_server_settings():
    """获取系统设置。

    若本地 Worker 在线优先代理获取；
    若本地 Worker 离线，安全降级返回云端服务端当前配置，避免纯 Web 模式下设置页 503 报错。
    """
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", "/api/settings")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass

    return {
        "llm": {
            "base_url": settings.server_llm_base_url,
            "model": settings.server_llm_model,
        },
        "scenes": {},
        "preferences": {
            "chapter_length": 3000,
            "exercises_per_kp": 3,
            "highlight_colors": {},
            "auto_highlight": False,
            "adhd_mode": "off",
        },
    }


# ----------------------------------------------------
# 3.1 学习者认知画像与学情中枢（支持云端 SQLite 离线直读与双向同步）
# ----------------------------------------------------
@app.get("/api/study/profile")
async def get_study_profile():
    """获取学习者认知画像与认知盲区。

    若本地 Worker 在线优先代理获取最新数据；
    若 Worker 离线，直接从云端 SQLite 读取已同步的画像与盲区，避免纯 Web 模式下 503 报错。
    """
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", "/api/study/profile")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass

    return await relay_db.get_learner_profile()


@app.put("/api/study/profile")
async def update_study_profile(request: Request):
    """更新学习者画像（背景描述与苏格拉底模式）。"""
    try:
        data = await request.json()
    except Exception as e:
        logger.warning("解析画像请求体异常: %s", e)
        data = {}

    bg = data.get("background_summary")
    sm = data.get("socratic_mode")

    if tunnel_manager.is_worker_online():
        try:
            body_bytes = json.dumps(data).encode("utf-8")
            status_code, _, resp_body = await tunnel_manager.dispatch_full(
                "PUT", "/api/study/profile", body=body_bytes
            )
            # 本地更新成功后，也同步更新云端数据库
            await relay_db.update_learner_profile(background_summary=bg, socratic_mode=sm)
            return Response(content=resp_body, status_code=status_code, media_type="application/json")
        except Exception as e:
            logger.warning("画像更新隧道转发本地失败，回退云端独立执行: %s", e)

    # 云端独立执行
    return await relay_db.update_learner_profile(background_summary=bg, socratic_mode=sm)


@app.post("/api/study/profile/reset")
@app.delete("/api/study/profile/reset")
async def reset_study_profile():
    """重置学习者画像与认知盲区。"""
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("POST", "/api/study/profile/reset")
            await relay_db.reset_learner_profile()
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass

    return await relay_db.reset_learner_profile()


@app.delete("/api/study/profile/misconceptions/{misconception_id}")
async def delete_study_misconception(misconception_id: str):
    """移除单个认知盲区。"""
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full(
                "DELETE", f"/api/study/profile/misconceptions/{misconception_id}"
            )
            await relay_db.delete_misconception(misconception_id)
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass

    await relay_db.delete_misconception(misconception_id)
    return {"ok": True}


@app.get("/api/study/today")
async def get_study_today():
    """获取今日学情行动中枢数据。"""
    if tunnel_manager.is_worker_online():
        try:
            status_code, _, body = await tunnel_manager.dispatch_full("GET", "/api/study/today")
            return Response(content=body, status_code=status_code, media_type="application/json")
        except Exception:
            pass

    # 云端独立模式下的学情中枢
    profile = await relay_db.get_learner_profile()
    misconceptions = profile.get("misconceptions", [])
    active_mis = [
        {"id": m.get("id", ""), "topic": m.get("topic", ""), "tag": m.get("tag")}
        for m in misconceptions
        if m.get("status", "active") == "active"
    ][:5]

    courses = await relay_db.list_courses()
    last_read = None
    if courses:
        c = courses[0]
        docs = c.get("documents", [])
        if docs:
            d = docs[0]
            last_read = {
                "course_id": c["id"],
                "course_title": c["title"],
                "document_id": d.get("id") or d.get("document_id", ""),
                "chapter_index": d.get("chapter_index", 0),
                "chapter_title": d.get("title", ""),
            }

    # 错题数与错题池同口径现算（v0.5.3 体检 P3）：mistakes 表从不清理且 exercise
    # 来源塌缩为 None_None，行数不代表真实错题量
    bank_wrong_count = await relay_db.count_bank_wrong_questions()
    return {
        "last_read": last_read,
        "hard_bones": [],
        "bank_wrong_count": bank_wrong_count,
        "active_misconceptions": active_mis,
    }


# ----------------------------------------------------
# 4. 智能路由：AI 生成、助教与沙箱执行（接入 dispatch_ai_request 统一调度）
# ----------------------------------------------------
# 真 LLM 问答端点白名单（v0.5.8 全量体检 P2-1）：此前按 ask/chat/conversations/
# executions/stream 等关键词子串判定「AI 路径」，Worker 离线且云端配了 LLM 时，
# GET /api/conversations/{id}/messages、开会话等普通 JSON 接口全被劫持为伪造
# SSE 问答流（extract_prompt 兜底甚至把空 body 序列化成 "{}" 喂模型）。
# 白名单只收「确由 LLM 流式生成回答」的端点；其余请求一律走普通反向代理
_LLM_QA_PATH_RE = re.compile(r"^/api/conversations/[^/]+/messages$")
_LLM_QA_SUFFIXES = ("ask", "agent", "photo", "qa", "detail", "diagnose", "tutor", "chat")


@app.api_route(
    "/api/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_api_catch_all(request: Request, full_path: str):
    """通用 API 路由穿透转发。

    根据请求性质智能分发：
    1. 真 LLM 问答/生成的 POST 流式请求（P2-1 白名单口径）：
       进入 dispatch_ai_request 统一调度器（按 cloud/local/auto 模式流式直出或隧道转发）；
    2. GET 的 SSE 读流（如章节生成进度）：仅本地隧道透传，离线 503；
    3. 普通非 AI 请求：
       若本地 Worker 在线，通过 tunnel_manager.dispatch_full 反向代理；
       若本地 Worker 离线，返回 503 明确提示。
    """
    path = f"/api/{full_path}"
    accept_header = request.headers.get("accept", "")
    is_stream_expected = "text/event-stream" in accept_header

    body = await request.body()
    query_params = dict(request.query_params)
    headers = dict(request.headers)

    # 0. GET 的 SSE 读流（如 /progress）：仅本地隧道透传——Worker 离线时应 503，
    #    绝不被云端 LLM 伪造流（P2-1）；旧逻辑经 AI 调度透传，这里直连隧道等价
    if request.method == "GET" and is_stream_expected:
        if not tunnel_manager.is_worker_online():
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "本地客户端未连接，无法读取该实时流", "worker_online": False},
            )
        try:
            stream_iter = tunnel_manager.dispatch_request(
                method=request.method,
                path=path,
                headers=headers,
                query_params=query_params,
                body=b"",
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
            logger.error("SSE 读流隧道透传异常: %s", e)
            return JSONResponse(status_code=500, content={"detail": f"实时流传透异常: {e}"})

    # 1. 真 LLM 问答/生成的流式请求：统一进入 dispatch_ai_request
    is_llm_qa = request.method == "POST" and (
        is_stream_expected
        or _LLM_QA_PATH_RE.match(path) is not None
        or path.endswith(_LLM_QA_SUFFIXES)
    )
    if is_llm_qa:
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
