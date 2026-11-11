# -*- coding: utf-8 -*-
"""SSE 流式响应的统一响应头。

全站所有 text/event-stream 端点共用：缺 charset 会在中文 payload 下产生编码歧义，
缺 X-Accel-Buffering 过 nginx 等缓冲代理时流式变阻塞（v0.5.1 体检 P3 收口）。
"""

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Type": "text/event-stream; charset=utf-8",
}
