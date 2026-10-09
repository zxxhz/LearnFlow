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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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


def _render_lan_auth_html(title: str, reason: str, show_input: bool = True) -> str:
    input_section = """
        <form onsubmit="handleEnter(event)" style="margin-top: 24px;">
            <div style="display: flex; gap: 8px;">
                <input id="token-input" type="text" placeholder="在此粘贴最新访问令牌 (Token)" style="flex: 1; padding: 10px 14px; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; outline: none; background: #fff; color: #111827;" autocomplete="off" />
                <button type="submit" style="padding: 10px 18px; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; white-space: nowrap;">立即进入</button>
            </div>
            <p style="margin-top: 10px; font-size: 12px; color: #6b7280;">提示：电脑端打开 LearnFlow，在「设置」→「数据与安全」中点击“复制局域网访问链接”即可获取最新令牌。</p>
        </form>
        <script>
            function handleEnter(e) {
                e.preventDefault();
                var val = document.getElementById('token-input').value.trim();
                if (!val) return;
                var url = new URL(window.location.href);
                url.searchParams.set('token', val);
                window.location.href = url.toString();
            }
        </script>
    """ if show_input else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} · LearnFlow</title>
    <style>
        :root {{ color-scheme: light dark; }}
        body {{
            margin: 0;
            padding: 24px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #f9fafb;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            color: #1f2937;
            box-sizing: border-box;
        }}
        .card {{
            width: 100%;
            max-width: 480px;
            background: #ffffff;
            border-radius: 16px;
            padding: 32px 28px;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.08);
            border: 1px solid #e5e7eb;
        }}
        .icon-wrap {{
            width: 52px;
            height: 52px;
            border-radius: 12px;
            background: #fee2e2;
            color: #ef4444;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 26px;
            margin-bottom: 20px;
        }}
        h1 {{
            margin: 0 0 10px 0;
            font-size: 20px;
            font-weight: 700;
            color: #111827;
        }}
        p.desc {{
            margin: 0;
            font-size: 14px;
            line-height: 1.6;
            color: #4b5563;
        }}
        @media (prefers-color-scheme: dark) {{
            body {{ background: #111827; color: #f3f4f6; }}
            .card {{ background: #1f2937; border-color: #374151; box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.4); }}
            h1 {{ color: #f9fafb; }}
            p.desc {{ color: #9ca3af; }}
            input {{ background: #111827 !important; color: #f3f4f6 !important; border-color: #4b5563 !important; }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon-wrap">🔒</div>
        <h1>{title}</h1>
        <p class="desc">{reason}</p>
        {input_section}
    </div>
</body>
</html>"""


class _AccessGuard:
    """纯 ASGI 中间件：非回环来源（局域网）必须携带访问令牌；本机与桌面壳直通。

    不用 BaseHTTPMiddleware：避免对流式响应（SSE）引入缓冲层。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            client = scope.get("client")
            host = client[0] if client else ""
            if host.startswith("::ffff:"):  # IPv4-mapped IPv6 归一化（双栈绑定下的本机回环）
                host = host[7:]
            if host not in ("127.0.0.1", "::1"):
                from app.services.system import get_access_token, is_lan_access_enabled

                path = scope.get("path", "")
                is_html_req = not path.startswith("/api/") and any(
                    k.lower() == b"accept" and b"text/html" in v.lower()
                    for k, v in scope.get("headers", [])
                )

                if not is_lan_access_enabled():
                    detail_msg = "局域网访问已在设置中关闭。如需从其他设备访问，请在设置中开启「局域网访问」。"
                    if is_html_req:
                        resp = HTMLResponse(
                            status_code=403,
                            content=_render_lan_auth_html("局域网访问未开启", detail_msg, show_input=False),
                        )
                    else:
                        resp = JSONResponse(
                            status_code=403,
                            content={"detail": detail_msg},
                        )
                    await resp(scope, receive, send)
                    return

                # 静态打包资产（JS/CSS/图标/PWA 清单/Service Worker 等）无敏感数据，豁免 token 校验，防止未就绪的浏览器白屏
                if (
                    path.startswith("/assets/")
                    or path.startswith("/icons/")
                    or path
                    in (
                        "/favicon.ico",
                        "/favicon.svg",
                        "/apple-touch-icon.png",
                        "/manifest.webmanifest",
                        "/manifest.json",
                        "/sw.js",
                    )
                ):
                    await self.app(scope, receive, send)
                    return

                import secrets
                import urllib.parse

                server_token = get_access_token()
                token = ""
                found_in_query = False

                # 1. 优先尝试从 query_string 获取 token
                query_str = scope.get("query_string", b"").decode("latin-1")
                for chunk in query_str.split("&"):
                    if chunk.startswith("token="):
                        token = urllib.parse.unquote(chunk[6:])
                        found_in_query = True
                        break

                # 2. 尝试从 Header 获取 x-access-token
                if not token:
                    for k, v in scope.get("headers", []):
                        if k.lower() == b"x-access-token":
                            token = v.decode("latin-1")
                            break

                # 3. 尝试从 Cookie 获取 lf_token
                if not token:
                    for k, v in scope.get("headers", []):
                        if k.lower() == b"cookie":
                            cookie_header = v.decode("latin-1")
                            for item in cookie_header.split(";"):
                                item = item.strip()
                                if item.startswith("lf_token="):
                                    token = urllib.parse.unquote(item[9:])
                                    break
                            if token:
                                break

                if not token:
                    detail_msg = "未提供访问令牌：请用设置页「局域网访问」里带 token 的完整地址打开。"
                    if is_html_req:
                        resp = HTMLResponse(
                            status_code=401,
                            content=_render_lan_auth_html("未提供访问令牌", detail_msg, show_input=True),
                        )
                    else:
                        resp = JSONResponse(status_code=401, content={"detail": detail_msg})
                    await resp(scope, receive, send)
                    return

                if not secrets.compare_digest(token, server_token):
                    detail_msg = "访问令牌错误或已失效：请在电脑端设置页重新复制最新的局域网访问地址。"
                    if is_html_req:
                        resp = HTMLResponse(
                            status_code=401,
                            content=_render_lan_auth_html("访问令牌错误或已失效", detail_msg, show_input=True),
                        )
                    else:
                        resp = JSONResponse(status_code=401, content={"detail": detail_msg})
                    await resp(scope, receive, send)
                    return

                # 若是通过 query_string 带有效 token 访问，自动下发 Set-Cookie 便于后续请求无缝通行
                if found_in_query and secrets.compare_digest(token, server_token):
                    async def send_with_cookie(message):
                        if message["type"] == "http.response.start":
                            headers = list(message.get("headers", []))
                            cookie_val = f"lf_token={urllib.parse.quote(token)}; Path=/; SameSite=Lax; Max-Age=2592000"
                            headers.append((b"set-cookie", cookie_val.encode("latin-1")))
                            message["headers"] = headers
                        await send(message)

                    await self.app(scope, receive, send_with_cookie)
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
                if full_path == "sw.js":
                    return FileResponse(
                        candidate,
                        media_type="application/javascript",
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Service-Worker-Allowed": "/",
                        },
                    )
                if full_path == "manifest.webmanifest":
                    return FileResponse(
                        candidate,
                        media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"},
                    )
                return FileResponse(candidate)
            return FileResponse(
                STATIC_DIR / "index.html",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

    return app


app = create_app()


def main() -> None:
    import threading
    import webbrowser

    import uvicorn

    if settings.host == "0.0.0.0":
        # 局域网访问（PRD §5.9）：若开启则打印本机局域网地址（带访问令牌），默认关闭时给出引导
        from app.services.system import get_access_token, lan_urls, is_lan_access_enabled

        if is_lan_access_enabled():
            print("\n>>> 局域网访问地址（需与电脑同一网络，或走内网穿透）：")
            token = get_access_token()
            for url in lan_urls():
                print(f">>>   {url}/?token={token}")
            print(">>> 安全提示：已启用访问令牌保护，完整地址（含 token）可在设置页查看。\n")
        else:
            print("\n>>> 局域网访问当前处于关闭状态（仅限本机 127.0.0.1 访问）。")
            print(">>> 如需在平板或手机浏览器中使用，请在设置页「数据与安全」开启「局域网访问」。\n")

    if settings.open_browser:
        url = f"http://{'127.0.0.1' if settings.host == '0.0.0.0' else settings.host}:{settings.port}"
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
