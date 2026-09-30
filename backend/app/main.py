"""应用入口。

- 生产模式：uv run python -m app.main  → 托管 API + 前端构建产物，自动打开浏览器
- 开发模式：uv run uvicorn app.main:app --reload（前端另起 vite dev server）
"""
import contextlib
import logging
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

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    # 恢复上次中断的生成任务（PRD FR-1.3 断点续生成）
    with contextlib.suppress(ImportError):
        from app.services.generation.pipeline import resume_pending_generations

        await resume_pending_generations()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="LearnFlow", lifespan=lifespan)
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
    import socket
    import threading
    import webbrowser

    import uvicorn

    if settings.host == "0.0.0.0":
        # 平板/局域网访问（PRD §5.9）：打印本机局域网地址
        ips: set[str] = set()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127."):
                    ips.add(ip)
        except OSError:
            pass
        print(f"\n>>> 局域网访问地址（平板需与电脑同一网络，或走内网穿透）：" )
        for ip in sorted(ips):
            print(f">>>   http://{ip}:{settings.port}")
        print(">>> 安全提示：0.0.0.0 会将服务暴露给局域网，建议仅配 Tailscale 等私网使用。\n")

    if settings.open_browser:
        url = f"http://{'127.0.0.1' if settings.host == '0.0.0.0' else settings.host}:{settings.port}"
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
