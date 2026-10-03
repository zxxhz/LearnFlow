"""应用入口。

- 生产模式：uv run python -m app.main  → 托管 API + 前端构建产物，自动打开浏览器
- 桌面打包：PyInstaller（run_backend.py 入口）→ 同上，路径按冻结模式解析
- 开发模式：uv run uvicorn app.main:app --reload（前端另起 vite dev server）
"""
import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import settings
from app.core.db import init_db
from app.services.llm.errors import LLMError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _static_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller onedir：datas 进入 _internal（sys._MEIPASS），spec 里映射为 app/static
        return Path(sys._MEIPASS) / "app" / "static"  # noqa: SLF001
    return Path(__file__).parent / "static"


STATIC_DIR = _static_dir()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.services.system import apply_pending_restore

    apply_pending_restore()  # 待恢复备份在连接数据库前生效
    await init_db()

    from app.sample_course import seed_sample_course
    from app.services.search import backfill_fts

    async with _db_session() as db:
        await backfill_fts(db)  # 老库升级回填全文索引
        await seed_sample_course(db)  # 首跑示例课程（无 LLM 也能体验）
    # 恢复上次中断的生成任务（PRD FR-1.3 断点续生成）
    with contextlib.suppress(ImportError):
        from app.services.generation.pipeline import resume_pending_generations

        await resume_pending_generations()
    yield


def _db_session():
    from app.core.db import async_session_factory

    return async_session_factory()


class _AccessGuard:
    """纯 ASGI 中间件：非回环来源（局域网/平板）必须携带访问令牌；本机与桌面壳直通。

    不用 BaseHTTPMiddleware：避免对流式响应（SSE）引入缓冲层。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            client = scope.get("client")
            host = client[0] if client else ""
            if host not in ("127.0.0.1", "::1"):
                import urllib.parse

                token = ""
                for chunk in scope.get("query_string", b"").decode().split("&"):
                    if chunk.startswith("token="):
                        token = urllib.parse.unquote(chunk[6:])
                        break
                for k, v in scope.get("headers", []):
                    if k == b"x-access-token":
                        token = v.decode("latin-1")
                        break
                from app.services.system import get_access_token

                if not token or token != get_access_token():
                    resp = JSONResponse(
                        status_code=401,
                        content={"detail": "需要访问令牌：请用设置页「局域网访问」里带 token 的完整地址打开。"},
                    )
                    await resp(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(title="LearnFlow", lifespan=lifespan)
    app.add_middleware(_AccessGuard)
    app.include_router(api_router)

    @app.exception_handler(LLMError)
    async def llm_error_handler(_: Request, exc: LLMError):
        return JSONResponse(status_code=400, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # 统一转成 400 + 中文平铺消息（pydantic v2 会把 ValueError 包成 "Value error, xxx"）
        msgs = []
        for err in exc.errors():
            msg = str(err.get("msg", ""))
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            msgs.append(msg)
        return JSONResponse(
            status_code=400,
            content={"detail": "；".join(msgs) if msgs else "参数错误"},
        )

    if (STATIC_DIR / "index.html").exists():
        if (STATIC_DIR / "assets").exists():
            app.mount(
                "/assets",
                StaticFiles(directory=STATIC_DIR / "assets"),
                name="assets",
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file() and candidate.resolve().is_relative_to(STATIC_DIR.resolve()):
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def main() -> None:
    import threading
    import webbrowser

    import uvicorn

    if settings.host == "0.0.0.0":
        # 平板/局域网访问（PRD §5.9）：打印本机局域网地址（带访问令牌）
        from app.services.system import get_access_token, lan_urls

        print("\n>>> 局域网访问地址（平板需与电脑同一网络，或走内网穿透）：")
        token = get_access_token()
        for url in lan_urls():
            print(f">>>   {url}/?token={token}")
        print(">>> 安全提示：已启用访问令牌保护，完整地址（含 token）可在设置页查看。\n")

    if settings.open_browser:
        url = f"http://{'127.0.0.1' if settings.host == '0.0.0.0' else settings.host}:{settings.port}"
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
