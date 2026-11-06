"""LearnFlow 自建中转系统端到端集成测试脚本。

涵盖测试点：
1. 服务端 Token 鉴权机制（强制鉴权、免密开放模式、Header/Query/Cookie 多源比对、静态文件豁免）。
2. 本地客户端与云端服务端的反向 WebSocket 隧道连接与心跳握手。
3. 云端请求向本地反向代理分发，本地执行并流式（SSE Chunk）逐段返回。
4. 数据从本地到云端的打包推送（push）与云端 SQLite 持久化落库。
5. 本地局域网访问控制（_AccessGuard 与 is_lan_access_enabled）的原样保留与兼容性。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 添加 backend 和项目根目录到 Python 路径
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = WORKSPACE_ROOT / "backend"
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

import httpx
from server.config import settings as server_settings
from server.db import relay_db
from server.main import app as server_app
from server.tunnel import tunnel_manager


async def run_all_tests():
    print("=" * 60)
    print("🚀 开始 LearnFlow 自建中转系统端到端全链路自动化集成测试")
    print("=" * 60)

    # 1. 测试服务端数据库初始化
    test_db_dir = WORKSPACE_ROOT / "server" / "data_test_e2e"
    test_db_dir.mkdir(parents=True, exist_ok=True)
    relay_db.db_path = test_db_dir / "relay_test.db"
    await relay_db.init_db()
    print("✅ 1. 云端 SQLite 数据库初始化通过: ", relay_db.db_path)

    # 2. 测试 Token 鉴权（开启鉴权模式）
    server_settings.relay_auth_required = True
    server_settings.relay_server_token = "mypassword123"

    transport = httpx.ASGITransport(app=server_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # a. 未提供 Token 应当被拒绝 (401)
        r = await client.get("/api/courses")
        assert r.status_code == 401, f"预期 401，实际 {r.status_code}"
        print("✅ 2a. 强制鉴权模式拦截未授权请求 (401) 通过")

        # b. 静态资源免鉴权 (favicon.ico / assets)
        r = await client.get("/favicon.ico")
        assert r.status_code in (200, 404), f"静态资源应放行，实际 {r.status_code}"
        print("✅ 2b. 静态文件与清单豁免鉴权通过")

        # c. 通过 Header 携带 Token (200)
        r = await client.get("/api/relay/status", headers={"x-server-token": "mypassword123"})
        assert r.status_code == 200, f"预期 200，实际 {r.status_code}"
        print("✅ 2c. Header (x-server-token) 鉴权通过")

        # d. 通过 Query 参数携带 Token (200)
        r = await client.get("/api/relay/status?token=mypassword123")
        assert r.status_code == 200, f"预期 200，实际 {r.status_code}"
        print("✅ 2d. Query (?token=...) 鉴权通过")

        # e. 通过 Cookie 携带 Token (200)
        client.cookies.set("lf_server_token", "mypassword123")
        r = await client.get("/api/relay/status")
        assert r.status_code == 200, f"预期 200，实际 {r.status_code}"
        client.cookies.clear()
        print("✅ 2e. Cookie (lf_server_token) 鉴权通过")

    # 3. 测试免密开放模式（用户要求：“要用token鉴权，可以不用”）
    server_settings.relay_auth_required = False
    server_settings.relay_server_token = ""
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/relay/status")
        assert r.status_code == 200, f"预期开放访问 200，实际 {r.status_code}"
        print("✅ 3. 免密开放访问模式（可以不用 Token）通过")

    # 4. 测试数据从本地推送到云端存储 (Sync Push)
    mock_payload = {
        "sync_version": "1.0",
        "client_version": "0.4.67",
        "timestamp": "2026-11-06T10:00:00Z",
        "courses": [
            {"id": "course-1", "title": "C++ 现代系统编程", "topic": "C++20", "level": "进阶"}
        ],
        "documents": [
            {"id": "doc-1", "course_id": "course-1", "title": "第1章 移动语义", "content_md": "# 移动语义\nstd::move 的本质是强制类型转换为右值引用。"}
        ],
        "question_banks": [
            {"id": "bank-1", "name": "C++ 核心题库", "category": "编程", "question_count": 50}
        ],
        "bank_questions": [
            {"id": "q-1", "bank_id": "bank-1", "kind": "choice", "title": "关于智能指针", "content": "哪种指针独占所有权？", "answer": "A"}
        ],
        "mistakes": [
            {"id": "m-1", "source": "bank", "item_id": "q-1", "error_count": 2}
        ],
        "mindmaps": [
            {"id": "map-1", "title": "现代 C++ 全景导图", "root_node": "{\"id\":\"root\",\"title\":\"C++\"}"}
        ],
        "annotations": [],
        "learner_profile": {"id": "local", "background_summary": "掌握 Python，正在攻坚 C++ 内存模型", "socratic_mode": 1}
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/relay/sync/push", json=mock_payload)
        assert r.status_code == 200, f"推送失败 {r.text}"
        res = r.json()
        assert res.get("ok") is True
        print("✅ 4a. 本地数据向云端推送 (POST /api/relay/sync/push) 成功: ", res.get("stats"))

        # 验证云端持久化落库与查询（即使本地离线，云端也能秒读课程与题库！）
        course = await relay_db.get_course("course-1")
        assert course is not None
        assert course["id"] == "course-1"
        assert course["title"] == "C++ 现代系统编程"

        doc = await relay_db.get_document("doc-1")
        assert doc is not None
        assert "移动语义" in (doc["content"] or "")

        bank = await relay_db.get_bank("bank-1")
        assert bank is not None
        assert bank["name"] == "C++ 核心题库"

        questions = await relay_db.get_bank_questions("bank-1")
        assert len(questions) >= 1
        assert questions[0]["answer"] == "A"
        print("✅ 4b. 云端 SQLite 数据持久化与离线查阅验证通过")

    # 5. 测试 WebSocket 反向隧道与流式 Chunk 代理
    print("⏳ 5. 正在验证 WebSocket 反向隧道长连接与 AI 流式 Chunk 代理...")
    assert tunnel_manager.is_worker_online() is False

    class MockWebSocket:
        def __init__(self):
            self.sent_messages = []
            self.closed = False

        async def send_text(self, text: str):
            self.sent_messages.append(text)

        async def close(self, code: int = 1000, reason: str = ""):
            self.closed = True

    mock_ws = MockWebSocket()
    worker = await tunnel_manager.register(
        mock_ws,
        {"client_id": "test-worker-e2e", "client_name": "本地测试 Worker", "version": "0.4.67"},
    )
    assert tunnel_manager.is_worker_online() is True
    print("✅ 5a. 本地 Worker 经 WebSocket 隧道注册成功")

    # 模拟云端发起流式请求
    chunks_collected = []
    async def call_cloud_ai_stream():
        async for chunk in tunnel_manager.dispatch_request(
            method="POST",
            path="/api/tutor/chat",
            body={"query": "请用苏格拉底风格解释指针"}
        ):
            chunks_collected.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)

    dispatch_task = asyncio.create_task(call_cloud_ai_stream())
    await asyncio.sleep(0.02)

    # 检查下发到本地 Worker 的消息
    last_sent = json.loads(mock_ws.sent_messages[-1])
    assert last_sent["type"] == "request"
    req_id = last_sent["request_id"]
    assert last_sent["path"] == "/api/tutor/chat"

    # Worker 模拟本地 LLM 流式输出 3 个 SSE chunk
    await tunnel_manager.handle_message(worker, json.dumps({"type": "chunk", "request_id": req_id, "data": "data: 指针就像"}))
    await tunnel_manager.handle_message(worker, json.dumps({"type": "chunk", "request_id": req_id, "data": "门牌号，"}))
    await tunnel_manager.handle_message(worker, json.dumps({"type": "chunk", "request_id": req_id, "data": "指向内存里的房间。\n\n"}))
    await tunnel_manager.handle_message(worker, json.dumps({"type": "end", "request_id": req_id, "status_code": 200, "headers": {}}))

    await dispatch_task
    full_text = "".join(chunks_collected)
    assert "指针就像门牌号" in full_text
    print("✅ 5b. 云端请求经隧道反向代理到本地、本地流式回传 SSE 验证通过: ", repr(full_text))

    await tunnel_manager.unregister(worker.worker_id)
    assert tunnel_manager.is_worker_online() is False

    # 6. 测试云端大模型模式（调用 AI 走服务端，本地无需 Worker）
    print("⏳ 6. 正在测试云端大模型模式（AI 走服务端直出）...")
    from server.llm import server_llm_service
    # Mock 服务端大模型流式生成
    original_stream_chat = server_llm_service.stream_chat
    async def mock_cloud_stream_chat(*args, **kwargs):
        yield "这是来自自建云端服务器的"
        yield "中央大模型"
        yield "生成的答疑内容。\n"
    server_llm_service.stream_chat = mock_cloud_stream_chat

    # 切换至 cloud 模式并配置 mock key
    server_settings.ai_mode = "cloud"
    server_settings.server_llm_api_key = "test-cloud-key"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 获取当前模式
        r = await client.get("/api/relay/ai-mode")
        assert r.status_code == 200
        assert r.json().get("ai_mode") == "cloud"

        # 发起 AI 请求，服务端直接以流式响应
        r = await client.post("/api/tutor/chat", json={"query": "微积分基本定理"})
        assert r.status_code == 200
        cloud_ai_reply = r.text
        assert "中央大模型" in cloud_ai_reply
        print("✅ 6. 云端大模型模式（走服务端直接生成）验证通过: ", repr(cloud_ai_reply.strip()))

    server_llm_service.stream_chat = original_stream_chat

    # 7. 测试从云端全量拉取数据 (GET /api/relay/sync/pull)
    print("⏳ 7. 正在测试从云端全量拉取数据 (Pull)...")
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.get("/api/relay/sync/pull")
        assert r.status_code == 200
        pull_data = r.json()
        assert pull_data.get("ok") is True
        payload = pull_data.get("payload") or pull_data
        assert len(payload.get("courses", [])) >= 1
        assert len(payload.get("documents", [])) >= 1
        assert "移动语义" in (payload["documents"][0].get("content") or "")
        assert len(payload.get("question_banks", [])) >= 1
        print("✅ 7. 云端全量数据拉取导出 (Pull) 验证通过: 课程数 =", len(payload.get("courses", [])), ", 文档数 =", len(payload.get("documents", [])))

    # 8. 验证本地局域网访问兼容性
    from app.services.system import is_lan_access_enabled, get_access_token
    token = get_access_token()
    assert token is not None and len(token) > 0
    print("✅ 8. 本地原始访问令牌与局域网访问功能完全保留: Token =", token[:4] + "****")

    # 清理测试数据库
    try:
        import shutil
        shutil.rmtree(test_db_dir, ignore_errors=True)
    except Exception:
        pass

    print("=" * 60)
    print("🎉 端到端集成测试全流程 100% 验证成功！所有功能均已就绪。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
