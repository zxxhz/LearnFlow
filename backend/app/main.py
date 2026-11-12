"""应用入口。

- 生产模式：uv run python -m app.main  → 托管 API + 前端构建产物，自动打开浏览器
- 桌面打包：PyInstaller（run_backend.py 入口）→ 同上，路径按冻结模式解析
- 开发模式：uv run uvicorn app.main:app --reload（前端另起 vite dev server）
"""
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import contextlib
import ipaddress
import logging
import re
import socket
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
    from app.services.mindmap import seed_sample_mindmap
    from app.services.search import backfill_fts

    async with _db_session() as db:
        await backfill_fts(db)  # 老库升级回填全文索引
        await seed_sample_course(db)  # 首跑示例课程（无 LLM 也能体验）
        await seed_sample_mindmap(db)  # 首跑示例思维导图（开箱即用体验导图画布与 Agent）
    # 恢复上次中断的生成任务（PRD FR-1.3 断点续生成）
    with contextlib.suppress(ImportError):
        from app.services.generation.pipeline import resume_pending_generations

        await resume_pending_generations()

    # 启动自建云端中转长连接（若已配置启用）
    from app.services.relay import get_relay_config, relay_client

    if get_relay_config().enabled:
        await relay_client.start()

    try:
        yield
    finally:
        await relay_client.stop()


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


_TRUSTED_HOSTS: set[str] = {"127.0.0.1", "localhost", "::1", "testclient"}
try:
    _hn = socket.gethostname().lower()
    if _hn:
        _TRUSTED_HOSTS.add(_hn)
        _TRUSTED_HOSTS.add(f"{_hn}.local")
except Exception:
    pass


class _TokenLogFilter(logging.Filter):
    """uvicorn access log 过滤：把 query 里的 token 值替换为 ***（令牌不落访问日志/终端回滚）。"""

    _TOKEN_RE = re.compile(r"([?&])token=[^&\s]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if "token=" in msg:
                record.msg = self._TOKEN_RE.sub(r"\1token=***", msg)
                record.args = None
        except Exception:
            pass
        return True


logging.getLogger("uvicorn.access").addFilter(_TokenLogFilter())


def _parse_host_header(host_header: str) -> tuple[str, int] | None:
    """解析 Host 头的 host 与 port（支持 IPv6 [::1]:8420 形式）。

    畸形端口（如 1.2.3.4:abc）返回 None：调用方按非法 Host 一律 403 拒绝，
    而不是让 ValueError 穿透中间件变每请求 500（v0.5.1 体检 P2）。
    """
    try:
        if host_header.startswith("["):
            end = host_header.find("]")
            if end != -1:
                h_host = host_header[1:end].lower()
                rest = host_header[end + 1 :]
                # v0.5.8 体检 P2：RFC 3986——']' 之后只允许空串或 ':port'；
                # '[::1]junk' 一类的尾随垃圾此前被宽松解析为 (::1, 80) 放行
                if rest and not (rest.startswith(":") and rest[1:].isdigit()):
                    return None
                host_port = int(rest[1:]) if rest.startswith(":") else 80
            else:
                h_host, host_port = host_header, 80
        else:
            h_host_raw, _, h_port = host_header.partition(":")
            h_host = h_host_raw.lower()
            host_port = int(h_port) if h_port else 80
        return h_host, host_port
    except ValueError:
        return None


def _is_trusted_host(h_host: str) -> bool:
    """防 DNS rebinding 攻击：校验 Host 头是否属于合法受信任地址。"""
    if not h_host:
        return False
    if h_host in _TRUSTED_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(h_host)
    except ValueError:
        return False
    # 收紧（v0.5.2 体检 P3）：只放行回环/私网/链路本地，公网 IP 字面量（8.8.8.8 等）
    # 不再天然受信；正常访问面 = 本机回环 + 局域网私网地址，不受影响
    return ip.is_loopback or ip.is_private or ip.is_link_local


class _AccessGuard:
    """纯 ASGI 中间件：非回环来源（局域网）必须携带访问令牌；本机与桌面壳直通。

    不用 BaseHTTPMiddleware：避免对流式响应（SSE）引入缓冲层。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            host_header = headers.get(b"host", b"").decode("latin-1").strip().lower()
            parsed_host = _parse_host_header(host_header) if host_header else ("", 80)
            h_host, host_port = parsed_host if parsed_host else (None, 80)

            # 1. Host 头合法性校验（防 DNS rebinding 攻击）：
            # 攻击者通过公共域名绑定 127.0.0.1 试图 drive-by 绕过回环免令牌限制，
            # 任何 Host 头非本机回环/机器名/合法 IP 的请求一律拒绝
            if host_header and (parsed_host is None or not _is_trusted_host(h_host or "")):
                res = JSONResponse(status_code=403, content={"detail": "非法的 Host 请求头，拒绝访问"})
                await res(scope, receive, send)
                return

            # 2. 变更类 /api 请求的同源校验（对回环与局域网一视同仁）：
            # multipart/form-data 与 form 编码属 CORS simple request，无 preflight，
            # 回环免令牌端口上本机浏览器恶意页面可 drive-by 提交（如视觉调用烧额度）。
            # 浏览器对 POST 必带 Origin；合法客户端（桌面壳/手机 PWA）Origin 与 Host 同源，
            # 非浏览器客户端（curl）不带 Origin → 放行，不影响任何正常用法。
            if scope.get("method") not in ("GET", "HEAD", "OPTIONS") and scope.get("path", "").startswith("/api/"):
                origin = headers.get(b"origin", b"").decode("latin-1").strip()
                sec_fetch_site = headers.get(b"sec-fetch-site", b"").decode("latin-1").strip().lower()

                def _reject() -> JSONResponse:
                    return JSONResponse(status_code=403, content={"detail": "跨站请求已被拒绝"})

                # Sec-Fetch-Site 由现代浏览器强制携带，非同源直接拒
                if sec_fetch_site and sec_fetch_site not in ("same-origin", "none"):
                    await _reject()(scope, receive, send)
                    return
                if origin:
                    try:
                        from urllib.parse import urlsplit

                        o = urlsplit(origin)
                        origin_host = (o.hostname or "").lower()
                        origin_port = o.port or (443 if o.scheme == "https" else 80)

                        if origin_host != h_host or origin_port != host_port:
                            await _reject()(scope, receive, send)
                            return
                    except Exception:  # noqa: BLE001  Origin 畸形按拒绝处理
                        await _reject()(scope, receive, send)
                        return

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

                # compare_digest 仅接受 ASCII 字符串：非 ASCII 令牌（手输污染等）先拦下，避免 TypeError 500
                if not token or not token.isascii() or not secrets.compare_digest(token, server_token):
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
                            # HttpOnly：前端只从 localStorage/query 取 token 走 x-access-token 头，不读 cookie
                            cookie_val = f"lf_token={urllib.parse.quote(token)}; Path=/; SameSite=Lax; Max-Age=2592000; HttpOnly"
                            headers.append((b"set-cookie", cookie_val.encode("latin-1")))
                            message["headers"] = headers
                        await send(message)

                    await self.app(scope, receive, send_with_cookie)
                    return

        await self.app(scope, receive, send)


class _SecurityHeaders:
    """纯 ASGI 中间件：仅给 text/html 响应追加 Content-Security-Policy。

    只覆盖 HTML 页面（SPA 入口与局域网认证页）；SSE（text/event-stream）与 API JSON
    不加头、也不经手响应体（无缓冲层，不影响流式）。回环（桌面壳 webview）保留
    script-src 'unsafe-inline'：webview 依赖注入内联脚本桥接 IPC，前端主题初始化也是内联
    脚本，收紧到 nonce 会破坏桌面壳与认证页表单。局域网浏览器（非回环客户端）用
    _CSP_LAN 收紧版：无内联 script，防单令牌应用的 XSS 窃取访问令牌。
    """

    _CSP = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    # v0.5.8 体检 P2：局域网浏览器访问用收紧版——单令牌应用一旦出现 XSS，
    # 内联脚本可执行并窃取 localStorage/query 中的访问令牌。Vite 构建产物
    # 无内联 script（index.html 仅外链 module），收紧不破坏 LAN 页面；
    # 桌面壳（回环访问）保持原 CSP：webview 依赖内联脚本桥接 IPC
    _CSP_LAN = _CSP.replace("script-src 'self' 'unsafe-inline'", "script-src 'self'")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client") or ("", 0)
        client_host = str(client[0] or "")
        is_loopback_client = client_host in ("127.0.0.1", "::1", "")

        async def send_with_csp(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if any(
                    k.lower() == b"content-type" and v.lower().startswith(b"text/html")
                    for k, v in headers
                ):
                    csp = self._CSP if is_loopback_client else self._CSP_LAN
                    headers.append((b"content-security-policy", csp.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_csp)


def create_app() -> FastAPI:
    app = FastAPI(title="LearnFlow", lifespan=lifespan)
    app.add_middleware(_AccessGuard)
    # 后添加的中间件在外层：CSP 包住门禁生成的 401/403 HTML 认证页一并加头
    app.add_middleware(_SecurityHeaders)
    app.include_router(api_router)

    @app.exception_handler(LLMError)
    async def llm_error_handler(_: Request, exc: LLMError):
        # 上游故障映射到合适的状态码：连接问题 502、限流 429，其余（配置/参数类）400
        from app.services.llm.errors import (
            LLMConnectionError,
            LLMRateLimitError,
        )

        status = 400
        if isinstance(exc, LLMConnectionError):
            status = 502
        elif isinstance(exc, LLMRateLimitError):
            status = 429
        return JSONResponse(status_code=status, content={"detail": exc.message})

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

    # v0.5.8 体检 P2：绑定面收窄——默认只监听回环；用户开启「局域网访问」才绑全部
    # 网卡（开关改动重启应用后生效）。原先恒绑 0.0.0.0，局域网与 API 之间只隔
    # _AccessGuard 一层应用门禁，防线一旦回归即直接暴露
    from app.services.system import is_lan_access_enabled, lan_urls

    if is_lan_access_enabled():
        settings.host = "0.0.0.0"
        # 局域网访问（PRD §5.9）：打印本机局域网地址（不含 token：终端回滚/截图即泄漏）
        print("\n>>> 局域网访问地址（需与电脑同一网络，或走内网穿透）：")
        for url in lan_urls():
            print(f">>>   {url}")
        print(">>> 安全提示：已启用访问令牌保护，完整地址（含 token）请在设置页「局域网访问」一键复制。\n")
    else:
        settings.host = "127.0.0.1"
        print("\n>>> 局域网访问当前处于关闭状态（仅限本机 127.0.0.1 访问）。")
        print(">>> 如需在平板或手机浏览器中使用，请在设置页「数据与安全」开启「局域网访问」并重启应用。\n")

    if settings.open_browser:
        url = f"http://127.0.0.1:{settings.port}"
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
