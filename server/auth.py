"""Token 鉴权中间件与依赖项。

鉴权逻辑：
1. 若 settings.is_auth_enabled() 为 False（即未强制鉴权且 Token 为空），完全跳过鉴权，开放访问。
2. 静态资源（/assets/, /icons/, /favicon.ico 等）一律免鉴权。
3. 若开启鉴权，按优先级从以下位置提取 Token：
   a. Header: x-server-token 或 x-access-token
   b. Query 参数: ?token=...
   c. Cookie: lf_server_token=... 或 lf_token=...
4. 使用 secrets.compare_digest 进行安全比对。
5. 若鉴权未通过：
   - HTML 请求：返回美观友好的 Token 录入界面；
   - API / 数据请求：返回 HTTP 401 JSON；
   - WebSocket 请求：拒绝连接。
6. 若通过 Query 携带合法 Token 访问网页，自动植入 Cookie 便于后续无缝通行。
"""
import secrets
import urllib.parse
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from server.config import settings

# 免除鉴权的静态资源路径前缀与白名单文件
STATIC_EXEMPT_PREFIXES = (
    "/assets/",
    "/icons/",
    "/static/",
)

STATIC_EXEMPT_FILES = {
    "/favicon.ico",
    "/favicon.svg",
    "/apple-touch-icon.png",
    "/manifest.webmanifest",
    "/manifest.json",
    "/sw.js",
    "/robots.txt",
}


def render_token_entry_html(title: str = "访问鉴权 · LearnFlow 云端中转", error_msg: Optional[str] = None) -> str:
    """渲染美观自适应暗色/亮色的 Token 录入表单页面。"""
    error_html = (
        f'<div class="error-banner">⚠️ {error_msg}</div>'
        if error_msg
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            color-scheme: light dark;
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-sub: #64748b;
            --border-color: #e2e8f0;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --input-bg: #ffffff;
            --error-bg: #fef2f2;
            --error-border: #fecaca;
            --error-text: #dc2626;
            --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-color: #0b1120;
                --card-bg: #1e293b;
                --text-main: #f8fafc;
                --text-sub: #94a3b8;
                --border-color: #334155;
                --primary: #3b82f6;
                --primary-hover: #60a5fa;
                --input-bg: #0f172a;
                --error-bg: #450a0a;
                --error-border: #7f1d1d;
                --error-text: #f87171;
                --shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.2);
            }}
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg-color);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            box-shadow: var(--shadow);
            width: 100%;
            max-width: 440px;
            padding: 36px 30px;
            text-align: center;
        }}
        .icon-circle {{
            width: 56px;
            height: 56px;
            border-radius: 16px;
            background: linear-gradient(135deg, #3b82f6, #6366f1);
            color: #ffffff;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 26px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
        }}
        h1 {{
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 8px;
            letter-spacing: -0.02em;
        }}
        p.subtitle {{
            font-size: 13.5px;
            color: var(--text-sub);
            line-height: 1.5;
            margin-bottom: 24px;
        }}
        .error-banner {{
            background: var(--error-bg);
            border: 1px solid var(--error-border);
            color: var(--error-text);
            padding: 10px 14px;
            border-radius: 10px;
            font-size: 13px;
            margin-bottom: 18px;
            text-align: left;
        }}
        .form-group {{
            margin-bottom: 20px;
            text-align: left;
        }}
        label {{
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
            margin-bottom: 6px;
        }}
        input[type="password"], input[type="text"] {{
            width: 100%;
            padding: 12px 14px;
            border: 1px solid var(--border-color);
            background: var(--input-bg);
            color: var(--text-main);
            border-radius: 10px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.15s, box-shadow 0.15s;
        }}
        input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
        }}
        button.btn-submit {{
            width: 100%;
            padding: 12px;
            background: var(--primary);
            color: #ffffff;
            border: none;
            border-radius: 10px;
            font-size: 14.5px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.15s;
        }}
        button.btn-submit:hover {{
            background: var(--primary-hover);
        }}
        .footer-tips {{
            margin-top: 22px;
            font-size: 12px;
            color: var(--text-sub);
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon-circle">🔐</div>
        <h1>中转服务访问验证</h1>
        <p class="subtitle">该 LearnFlow 云端中转服务端已启用安全令牌验证，请输入访问 Token 授权此设备。</p>
        {error_html}
        <form id="token-form" onsubmit="handleTokenSubmit(event)">
            <div class="form-group">
                <label for="token-input">访问令牌 (Server Token)</label>
                <input id="token-input" type="password" placeholder="粘贴 RELAY_SERVER_TOKEN..." autofocus autocomplete="off" />
            </div>
            <button type="submit" class="btn-submit">立即验证并进入</button>
        </form>
        <p class="footer-tips">
            提示：Token 在中转服务部署环境变量中设置。<br/>验证通过后将在此浏览器保持免密会话。
        </p>
    </div>
    <script>
        function handleTokenSubmit(e) {{
            e.preventDefault();
            var token = document.getElementById('token-input').value.trim();
            if (!token) return;
            // 将 Token 存入 cookie 并以 query 参数重定向验证
            document.cookie = "lf_server_token=" + encodeURIComponent(token) + "; path=/; max-age=2592000; SameSite=Lax";
            try {{
                localStorage.setItem("lf_access_token", token);
            }} catch(e) {{}}
            var url = new URL(window.location.href);
            url.searchParams.set('token', token);
            window.location.href = url.toString();
        }}
    </script>
</body>
</html>"""


def extract_token_from_scope(scope: dict) -> tuple[str, str]:
    """从 ASGI scope 提取 token。
    返回 (token, source)，source 为 'header', 'query', 'cookie' 或 ''。
    """
    headers = {k.lower(): v for k, v in scope.get("headers", [])}

    # a. Header: x-server-token 或 x-access-token
    for h_name in (b"x-server-token", b"x-access-token"):
        if h_name in headers:
            try:
                t = headers[h_name].decode("latin-1").strip()
                if t:
                    return t, "header"
            except Exception:
                pass

    # b. Query 参数: ?token=...
    query_string = scope.get("query_string", b"").decode("latin-1")
    if query_string:
        for chunk in query_string.split("&"):
            if chunk.startswith("token="):
                try:
                    val = urllib.parse.unquote(chunk[6:]).strip()
                    if val:
                        return val, "query"
                except Exception:
                    pass

    # c. Cookie: lf_server_token=... 或 lf_token=...
    cookie_header = headers.get(b"cookie", b"").decode("latin-1")
    if cookie_header:
        for item in cookie_header.split(";"):
            item = item.strip()
            for prefix in ("lf_server_token=", "lf_token="):
                if item.startswith(prefix):
                    try:
                        val = urllib.parse.unquote(item[len(prefix):]).strip()
                        if val:
                            return val, "cookie"
                    except Exception:
                        pass

    return "", ""


def verify_token(token: str) -> bool:
    """比对 Token。"""
    configured_token = settings.relay_server_token
    if not settings.is_auth_enabled():
        return True
    if not token or not configured_token:
        return False
    if not token.isascii():
        return False
    return secrets.compare_digest(token, configured_token)


class RelayAuthMiddleware:
    """纯 ASGI Token 鉴权中间件。

    不采用 BaseHTTPMiddleware，保障流式响应（SSE、WebSocket）无缓冲损耗。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # 1. 若未启用鉴权，直接放行
        if not settings.is_auth_enabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # 2. 静态文件免鉴权
        if (
            path in STATIC_EXEMPT_FILES
            or any(path.startswith(prefix) for prefix in STATIC_EXEMPT_PREFIXES)
        ):
            await self.app(scope, receive, send)
            return

        # 3. 提取 Token
        token, source = extract_token_from_scope(scope)
        is_valid = verify_token(token)

        # 4. WebSocket 鉴权
        if scope["type"] == "websocket":
            if not is_valid:
                # 拒绝连接
                async def fake_receive():
                    return {"type": "websocket.disconnect", "code": 4401}
                # 发送关闭帧 4401 (Unauthorized)
                await send({"type": "websocket.close", "code": 4401, "reason": "Unauthorized token"})
                return
            await self.app(scope, receive, send)
            return

        # 5. HTTP 请求鉴权判断
        is_html_req = not path.startswith("/api/") and any(
            k.lower() == b"accept" and b"text/html" in v.lower()
            for k, v in scope.get("headers", [])
        )

        if not is_valid:
            error_reason = "访问令牌错误或已失效" if token else "请提供访问令牌"
            if is_html_req:
                resp = HTMLResponse(
                    status_code=401,
                    content=render_token_entry_html(error_msg=error_reason),
                )
            else:
                resp = JSONResponse(
                    status_code=401,
                    content={"detail": f"{error_reason}，未通过中转鉴权", "authenticated": False},
                )
            await resp(scope, receive, send)
            return

        # 6. 若通过 Query 携带有效 Token 访问页面，自动植入 Cookie
        if source == "query" and is_html_req:
            async def send_with_cookie(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    cookie_val = f"lf_server_token={urllib.parse.quote(token)}; Path=/; SameSite=Lax; Max-Age=2592000; HttpOnly"
                    headers.append((b"set-cookie", cookie_val.encode("latin-1")))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_with_cookie)
            return

        await self.app(scope, receive, send)


def require_token(request: Request) -> bool:
    """FastAPI 依赖项：供单个路由按需调用校验。"""
    if not settings.is_auth_enabled():
        return True

    token, _ = extract_token_from_scope(request.scope)
    if not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的访问令牌 (Invalid Relay Token)",
        )
    return True
