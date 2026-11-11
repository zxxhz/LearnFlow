"""针对 server 服务端各模块的完整自动化测试套件。"""
import asyncio
import gc
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from starlette.testclient import TestClient

# 1. 测试 DB 模块
def test_database():
    print(">>> 正在测试 server.db 模块...")
    from server.db import RelayDatabase

    test_db_path = Path("server/data/test_run_relay.db").resolve()
    if test_db_path.exists():
        test_db_path.unlink()

    try:
        db = RelayDatabase(db_path=test_db_path)
        db.init_db_sync()

        # 测试批量同步数据
        mock_payload = {
            "courses": [
                {
                    "id": "c1",
                    "title": "测试 Python 进阶课程",
                    "topic": "Python 高级语法",
                    "level": "中级",
                    "outline": [{"index": 1, "title": "异步编程与协程"}],
                    "status": "ready",
                }
            ],
            "documents": [
                {
                    "id": "d1",
                    "course_id": "c1",
                    "chapter_index": 1,
                    "title": "第一章：asyncio 原理",
                    "version": 1,
                    "content": "# 协程原理\n\n通过事件循环调度...",
                    "summary": "asyncio 核心事件循环",
                }
            ],
            "banks": [
                {
                    "id": "b1",
                    "name": "Python 基础知识试卷",
                    "question_count": 1,
                }
            ],
            "bank_questions": [
                {
                    "id": "q1",
                    "bank_id": "b1",
                    "seq": 1,
                    "qtype": "single",
                    "title": "Python 中哪个关键字用于定义协程函数？",
                    "options": ["A. async def", "B. def", "C. coroutine", "D. thread"],
                    "answer": "A",
                    "analysis": "async def 用于声明协程函数",
                }
            ],
            "mistakes": [
                {
                    "id": "m1",
                    "bank_id": "b1",
                    "question_id": "q1",
                    "wrong_count": 2,
                }
            ],
            "mindmaps": [
                {
                    "id": "mm1",
                    "title": "Python 知识大纲",
                    "topic": "Python",
                    "nodes": [{"id": "n1", "text": "基础语法"}],
                }
            ],
            "learner_profile": {
                "preferred_style": "实战驱动",
            },
        }

        res = db.save_sync_payload_sync(mock_payload)
        assert res["ok"] is True
        assert res["counts"]["courses"] == 1
        assert res["counts"]["documents"] == 1
        assert res["counts"]["banks"] == 1
        assert res["counts"]["bank_questions"] == 1
        assert res["counts"]["mistakes"] == 1
        assert res["counts"]["mindmaps"] == 1

        # 测试业务查询
        courses = db.list_courses_sync()
        assert len(courses) == 1
        assert courses[0]["id"] == "c1"

        course_detail = db.get_course_sync("c1")
        assert course_detail is not None
        assert len(course_detail["documents"]) == 1

        doc = db.get_document_sync("d1")
        assert doc is not None
        assert "协程原理" in doc["content"]

        banks = db.list_banks_sync()
        assert len(banks) == 1
        questions = db.get_bank_questions_sync("b1")
        assert len(questions) == 1
        assert questions[0]["answer"] == "A"

        wrongs = db.get_bank_wrong_questions_sync("b1")
        assert len(wrongs) == 1
        assert wrongs[0]["wrong_count"] == 2

        mindmaps = db.list_mindmaps_sync()
        assert len(mindmaps) == 1
        mm = db.get_mindmap_sync("mm1")
        assert mm is not None
        assert len(mm["nodes"]) == 1

        stats = db.get_db_stats_sync()
        assert stats["courses"] == 1
        assert stats["documents"] == 1

        pull_data = db.get_sync_payload_sync()
        assert len(pull_data["courses"]) == 1
        assert pull_data["learner_profile"]["preferred_style"] == "实战驱动"
    finally:
        for p in (test_db_path, Path(str(test_db_path) + "-wal"), Path(str(test_db_path) + "-shm")):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    print("✅ server.db 模块测试全部通过！")


# 2. 测试 Auth 与 HTTP API 模块
def test_auth_and_api():
    print(">>> 正在测试 server.auth 与 API 路由模块...")
    from server.config import settings
    from server.db import relay_db
    from server.main import app

    client = TestClient(app)
    # 裸 TestClient 不触发 lifespan（内含 relay_db.init_db），需显式建表；
    # 否则依赖本地残留 relay.db 的表结构，在新环境必挂 no such table
    relay_db.init_db_sync()

    # 1. 默认开放模式测试 (RELAY_AUTH_REQUIRED=False 且 Token 为空)
    settings.relay_auth_required = False
    settings.relay_server_token = ""

    # 测试 /health
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # 测试 /api/relay/status
    r = client.get("/api/relay/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "running"
    assert data["is_relay_server"] is True
    assert data["auth"]["enabled"] is False

    # 测试 /api/relay/config
    r_cfg = client.get("/api/relay/config")
    assert r_cfg.status_code == 200
    cfg_data = r_cfg.json()
    assert cfg_data["is_relay_server"] is True
    assert cfg_data["status"] == "running"
    assert cfg_data["worker_online"] is False

    # 2. 测试开启鉴权模式
    settings.relay_auth_required = True
    settings.relay_server_token = "secret-token-123"

    # 未携带 Token 访问受限 API -> 应返回 401 JSON
    r = client.get("/api/courses")
    assert r.status_code == 401
    assert "未通过中转鉴权" in r.json()["detail"]

    # 未携带 Token 访问 HTML 页面 -> 应返回 401 并包含友好 Token 录入界面
    r = client.get("/", headers={"accept": "text/html"})
    assert r.status_code == 401
    assert "中转服务访问验证" in r.text
    assert "token-input" in r.text

    # 静态资源免除鉴权
    r = client.get("/favicon.ico")
    # 静态文件或 404/200，但绝不是 401
    assert r.status_code != 401

    # a. Header 鉴权: x-server-token
    r = client.get("/api/relay/status", headers={"x-server-token": "secret-token-123"})
    assert r.status_code == 200

    # a2. Header 鉴权: x-access-token
    r = client.get("/api/relay/status", headers={"x-access-token": "secret-token-123"})
    assert r.status_code == 200

    # b. Query 参数鉴权: ?token=...
    r = client.get("/api/relay/status?token=secret-token-123")
    assert r.status_code == 200

    # c. Cookie 鉴权: lf_server_token=...
    r = client.get("/api/relay/status", cookies={"lf_server_token": "secret-token-123"})
    assert r.status_code == 200

    # c2. Cookie 鉴权: lf_token=...
    r = client.get("/api/relay/status", cookies={"lf_token": "secret-token-123"})
    assert r.status_code == 200

    # 错误 Token -> 401
    r = client.get("/api/relay/status", headers={"x-server-token": "wrong-token"})
    assert r.status_code == 401

    # 恢复配置
    settings.relay_auth_required = False
    settings.relay_server_token = ""
    print("✅ server.auth 与 API 鉴权测试全部通过！")


# 3. 测试 WebSocket 反向隧道与流式转发
def test_tunnel():
    print(">>> 正在测试 server.tunnel 反向隧道与流式调度...")
    from server.tunnel import (
        WorkerOfflineError,
        WorkerRequestTimeoutError,
        tunnel_manager,
    )

    class MockWebSocket:
        def __init__(self):
            self.sent_messages = []
            self.closed = False
            self.close_code = None

        async def send_text(self, text: str):
            self.sent_messages.append(text)

        async def close(self, code: int = 1000, reason: str = ""):
            self.closed = True
            self.close_code = code

    async def async_tunnel_tests():
        # 1. 测试 Worker 离线状态感知
        assert tunnel_manager.is_worker_online() is False

        # 离线时调用 dispatch_request 应抛出 WorkerOfflineError
        try:
            async for _ in tunnel_manager.dispatch_request("POST", "/api/test"):
                pass
            assert False, "离线时应抛出 WorkerOfflineError"
        except WorkerOfflineError:
            pass

        # 2. 模拟本地 Worker 注册
        mock_ws = MockWebSocket()
        worker = await tunnel_manager.register(
            mock_ws,
            {"client_id": "local-node-1", "client_name": "本地测试 Worker", "version": "1.0.0"},
        )
        assert tunnel_manager.is_worker_online() is True
        active_w = tunnel_manager.get_active_worker()
        assert active_w is not None
        assert active_w.worker_id == worker.worker_id

        # 3. 心跳检测测试
        await tunnel_manager.handle_message(worker, json.dumps({"type": "ping"}))
        assert len(mock_ws.sent_messages) > 0
        pong_frame = json.loads(mock_ws.sent_messages[-1])
        assert pong_frame["type"] == "pong"

        # 4. 请求派发与流式 Chunk 回传测试
        chunks_collected = []

        async def do_client_dispatch():
            async for chunk in tunnel_manager.dispatch_request(
                method="POST",
                path="/api/tutor/chat",
                headers={"content-type": "application/json"},
                query_params={"mode": "socratic"},
                body={"message": "请解释什么是递归"},
                timeout=5.0,
            ):
                chunks_collected.append(chunk.decode("utf-8"))

        dispatch_task = asyncio.create_task(do_client_dispatch())
        await asyncio.sleep(0.02)

        # 检验下发给 Worker 的 RPC 帧
        last_sent = json.loads(mock_ws.sent_messages[-1])
        assert last_sent["type"] == "request"
        assert last_sent["path"] == "/api/tutor/chat"
        assert last_sent["method"] == "POST"
        assert last_sent["query_params"]["mode"] == "socratic"
        req_id = last_sent["request_id"]

        # Worker 模拟回写流式 Chunk 和 End 帧
        await tunnel_manager.handle_message(
            worker,
            json.dumps({"type": "chunk", "request_id": req_id, "data": "data: 递归是指"}),
        )
        await tunnel_manager.handle_message(
            worker,
            json.dumps({"type": "chunk", "request_id": req_id, "data": "函数调用自身的过程。\n\n"}),
        )
        await tunnel_manager.handle_message(
            worker,
            json.dumps({"type": "end", "request_id": req_id, "status_code": 200}),
        )

        await dispatch_task
        full_res = "".join(chunks_collected)
        assert "递归是指函数调用自身的过程" in full_res

        # 5. Worker 注销测试
        await tunnel_manager.unregister(worker.worker_id)
        assert tunnel_manager.is_worker_online() is False

    asyncio.run(async_tunnel_tests())
    print("✅ server.tunnel 反向隧道与流式转发测试全部通过！")


# 3.5 隧道状态码透传与 forwarded 头剥离回归（修复纯 Web 经云端转发必崩问题）
def test_tunnel_status_and_forwarded_headers():
    print(">>> 正在测试 dispatch_full 状态码透传与 forwarded 头剥离...")
    from server.tunnel import tunnel_manager

    class MockWebSocket:
        def __init__(self):
            self.sent_messages = []
            self.closed = False
            self.close_code = None

        async def send_text(self, text: str):
            self.sent_messages.append(text)

        async def close(self, code: int = 1000, reason: str = ""):
            self.closed = True
            self.close_code = code

    async def async_status_tests():
        mock_ws = MockWebSocket()
        worker = await tunnel_manager.register(mock_ws, {"client_id": "local-node-2"})

        # A. dispatch_request 必须剥离 forwarded 头族（VPS 前置注入的 XFF 透传会让
        #    本地 _AccessGuard 把回环 worker 误判为局域网设备而 403）
        chunks: list[bytes] = []

        async def do_dispatch():
            async for chunk in tunnel_manager.dispatch_request(
                method="GET",
                path="/api/study/today",
                headers={
                    "x-forwarded-for": "203.0.113.9",
                    "x-real-ip": "203.0.113.9",
                    "forwarded": "for=203.0.113.9",
                    "x-access-token": "business-token",
                    "content-type": "application/json",
                },
                timeout=5.0,
            ):
                chunks.append(chunk)

        task = asyncio.create_task(do_dispatch())
        await asyncio.sleep(0.02)
        frame = json.loads(mock_ws.sent_messages[-1])
        assert frame["type"] == "request"
        hdrs = {k.lower(): v for k, v in frame["headers"].items()}
        assert "x-forwarded-for" not in hdrs, f"XFF 泄漏: {hdrs}"
        assert "x-real-ip" not in hdrs
        assert "forwarded" not in hdrs
        assert hdrs.get("x-access-token") == "business-token"  # 业务头保留
        req_id = frame["request_id"]
        # 本地 403 错误体回传
        await tunnel_manager.handle_message(
            worker,
            json.dumps({"type": "chunk", "request_id": req_id, "data": json.dumps({"detail": "局域网访问已在设置中关闭"}, ensure_ascii=False)}),
        )
        await tunnel_manager.handle_message(
            worker,
            json.dumps({"type": "end", "request_id": req_id, "status_code": 403, "headers": {"content-type": "application/json"}}),
        )
        await task
        assert "局域网访问" in b"".join(chunks).decode("utf-8", errors="replace")

        # B. dispatch_full 必须还原本地真实状态码（此前硬编码 200，403 错误体被 200 包裹）
        async def do_full():
            return await tunnel_manager.dispatch_full(
                method="GET",
                path="/api/dashboard/summary",
                headers={"x-forwarded-for": "198.51.100.7"},
                timeout=5.0,
            )

        task2 = asyncio.create_task(do_full())
        await asyncio.sleep(0.02)
        frame2 = json.loads(mock_ws.sent_messages[-1])
        hdrs2 = {k.lower(): v for k, v in frame2["headers"].items()}
        assert "x-forwarded-for" not in hdrs2, f"XFF 泄漏: {hdrs2}"
        rid = frame2["request_id"]
        await tunnel_manager.handle_message(
            worker,
            json.dumps({"type": "chunk", "request_id": rid, "data": "部分数据"}),
        )
        await tunnel_manager.handle_message(
            worker,
            json.dumps({
                "type": "end",
                "request_id": rid,
                "status_code": 403,
                "headers": {"content-type": "application/json", "transfer-encoding": "chunked"},
            }),
        )
        status, resp_headers, body = await task2
        assert status == 403, f"应透传本地 403，实际 {status}"
        assert body.decode("utf-8") == "部分数据"
        assert "transfer-encoding" not in {k.lower() for k in resp_headers}
        assert resp_headers.get("content-type") == "application/json"

        await tunnel_manager.unregister(worker.worker_id)
        assert tunnel_manager.is_worker_online() is False

    asyncio.run(async_status_tests())
    print("✅ 隧道状态码透传与 forwarded 头剥离测试全部通过！")


# 3.6 云端直答题库 stats 聚合回归（此前缺 stats 致题库页 reading 'question_count' 崩溃）
def test_database_banks_stats():
    print(">>> 正在测试云端题库 stats 聚合...")
    import sqlite3

    from server.db import RelayDatabase

    tmp_dir = tempfile.mkdtemp(prefix="lf-stats-test-", dir=Path(__file__).resolve().parent / "data")
    db = RelayDatabase(db_path=Path(tmp_dir) / "relay.db")
    db.init_db_sync()
    try:
        with sqlite3.connect(str(db.db_path)) as conn:
            conn.execute(
                "INSERT INTO question_banks (id, name, question_count) VALUES ('b1', '测试库', 4)"
            )
            # 4 题：q1 单选（最新一次对但存疑→计错题池）、q2 单选（最新一次错）、
            # q3 判断（未作答）、q4 单选（与 q2 指纹相同，验证 new_count 去重口径）
            conn.executemany(
                "INSERT INTO bank_questions (id, bank_id, seq, qtype, title, options, answer) VALUES (?,?,?,?,?,?,?)",
                [
                    ("q1", "b1", 1, "single", "1+1=?", '["1","2","3","4"]', "2"),
                    ("q2", "b1", 2, "single", "2+2=?", '["3","4","5","6"]', "4"),
                    ("q3", "b1", 3, "judge", "对吗", "[]", "对"),
                    ("q4", "b1", 4, "single", " 2+2=? ", '["3"," 4 ","5","6"]', " 4 "),
                ],
            )
            conn.executemany(
                "INSERT INTO bank_attempts (id, bank_id, question_id, is_correct, is_doubtful, created_at) VALUES (?,?,?,?,?,?)",
                [
                    ("a1", "b1", "q1", 0, 0, "2026-01-01T00:00:00"),
                    ("a2", "b1", "q1", 1, 0, "2026-01-02T00:00:00"),
                    ("a3", "b1", "q2", 0, 0, "2026-01-03T00:00:00"),
                    ("a4", "b1", "q1", 1, 1, "2026-01-04T00:00:00"),
                ],
            )

        banks = db.list_banks_sync()
        assert len(banks) == 1
        stats = banks[0]["stats"]
        assert stats["question_count"] == 4
        assert stats["answered"] == 2  # 仅 q1/q2 有作答
        assert stats["wrong_count"] == 2  # q1 存疑 + q2 错
        assert stats["correct"] == 0  # 最近一次无"对且不存疑"
        assert stats["attempts"] == 4
        assert stats["accuracy"] == 50.0  # 全量 4 次作答 2 次正确
        assert stats["new_count"] == 1  # 仅 q3（q4 与 q2 指纹同道且已答）
        assert stats["by_type"]["single"] == {"total": 3, "wrong": 2}
        assert stats["by_type"]["judge"] == {"total": 1, "wrong": 0}

        detail = db.get_bank_sync("b1")
        assert detail is not None
        assert detail["stats"]["question_count"] == 4
        assert detail["stats"]["new_count"] == 1
    finally:
        del db
        gc.collect()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("✅ 云端题库 stats 聚合测试全部通过！")


# 4. 测试云端大模型模式与完整数据拉取 (task-4)
def test_cloud_ai_and_sync():
    print(">>> 正在测试云端 AI 模式调度与全量数据 Pull...")
    from server.config import settings
    from server.db import relay_db
    from server.llm import server_llm_service
    from server.main import app

    client = TestClient(app)
    # 裸 TestClient 不触发 lifespan，显式建表保证 sync pull 等数据接口可用
    relay_db.init_db_sync()

    # 1. 测试 AI 模式查询与更新 API
    r = client.get("/api/relay/ai-mode")
    assert r.status_code == 200
    assert "ai_mode" in r.json()

    # 更新为 cloud 模式
    r = client.post(
        "/api/relay/ai-mode",
        json={
            "ai_mode": "cloud",
            "server_llm_model": "test-cloud-model",
            "server_llm_api_key": "sk-mock-key-123",
            "server_llm_base_url": "https://api.test-llm.com/v1",
        },
    )
    assert r.status_code == 200
    assert r.json()["ai_mode"] == "cloud"
    assert settings.ai_mode == "cloud"
    assert settings.is_server_llm_configured() is True

    # 2. Mock 云端大模型流式生成
    original_stream_chat = server_llm_service.stream_chat

    async def mock_stream_chat(messages, system_prompt="", model=None, temperature=0.7):
        yield "云端导师："
        yield "这是服务端直出的流式回答。"

    server_llm_service.stream_chat = mock_stream_chat

    try:
        # 发起 AI 助教请求（云端直出）
        r_ai = client.post(
            "/api/tutor/chat",
            json={"message": "云端模式测试问题"},
            headers={"accept": "text/event-stream"},
        )
        assert r_ai.status_code == 200
        assert "text/event-stream" in r_ai.headers["content-type"]
        body_text = r_ai.text
        assert '{"type": "delta", "text": "云端导师："}' in body_text
        assert '{"type": "delta", "text": "这是服务端直出的流式回答。"}' in body_text
        assert '{"type": "done"}' in body_text

        # 3. 测试数据全量 Pull 端点
        # 先 push 结构化数据
        push_res = client.post(
            "/api/relay/sync/push",
            json={
                "courses": [{"id": "course-pull-1", "title": "云端 Pull 测试课程"}],
                "documents": [{"id": "doc-pull-1", "course_id": "course-pull-1", "chapter_index": 1, "title": "第一节", "content": "# 讲义正文"}],
                "banks": [{"id": "bank-pull-1", "name": "云端题库"}],
                "bank_questions": [{"id": "bq-pull-1", "bank_id": "bank-pull-1", "title": "题目1", "answer": "B"}],
                "bank_attempts": [{"id": "att-1", "bank_id": "bank-pull-1", "question_id": "bq-pull-1", "user_answer": "B", "is_correct": 1}],
                "mistakes": [{"id": "mistake-pull-1", "bank_id": "bank-pull-1", "question_id": "bq-pull-1", "wrong_count": 1}],
                "mindmaps": [{"id": "mm-pull-1", "title": "导图1"}],
                "learner_profile": {"level": "advanced"},
            },
        )
        assert push_res.status_code == 200
        assert push_res.json()["ok"] is True

        # 调用 pull 端点
        pull_res = client.get("/api/relay/sync/pull")
        assert pull_res.status_code == 200
        pull_data = pull_res.json()
        assert pull_data["ok"] is True
        assert any(c["id"] == "course-pull-1" for c in pull_data["courses"])
        assert any(d["id"] == "doc-pull-1" and d["content"] == "# 讲义正文" for d in pull_data["documents"])
        assert any(b["id"] == "bank-pull-1" for b in pull_data["banks"])
        assert any(q["id"] == "bq-pull-1" for q in pull_data["bank_questions"])
        assert any(a["id"] == "att-1" for a in pull_data["bank_attempts"])
        assert any(m["id"] == "mistake-pull-1" for m in pull_data["mistakes"])
        assert any(mm["id"] == "mm-pull-1" for mm in pull_data["mindmaps"])
        assert pull_data["learner_profile"]["level"] == "advanced"

    finally:
        server_llm_service.stream_chat = original_stream_chat
        settings.ai_mode = "auto"
        settings.server_llm_api_key = ""

    print("✅ 云端 AI 模式与全量数据 Pull 测试全部通过！")


# 5. 测试系统版本检测与在线更新接口
def test_system_version_and_update():
    print(">>> 正在测试 server.api_system 模块...")
    from server.db import relay_db
    from server.main import app

    client = TestClient(app)
    relay_db.init_db_sync()  # 裸 TestClient 不触发 lifespan，显式建表

    # 1. 测试版本查询端点
    r = client.get("/api/relay/system/version")
    assert r.status_code == 200
    data = r.json()
    assert "current_version" in data
    assert "latest_version" in data
    assert "in_container" in data
    assert "can_auto_update" in data
    assert "update_driver" in data

    # 2. 测试在线更新触发端点 (未鉴权拦截)
    # 当有 token 限制时
    from server.config import settings
    old_token = settings.relay_server_token
    settings.relay_server_token = "test-update-secret"
    try:
        r_unauth = client.post("/api/relay/system/update")
        assert r_unauth.status_code == 401

        # 携带 token 鉴权成功
        r_auth = client.post(
            "/api/relay/system/update",
            headers={"x-server-token": "test-update-secret"}
        )
        assert r_auth.status_code == 200
        res = r_auth.json()
        assert "status" in res
        assert "message" in res
        assert "driver" in res
    finally:
        settings.relay_server_token = old_token

    # 3. 测试在线大模型连通性测试接口
    r_test = client.post(
        "/api/relay/ai-mode/test",
        json={
            "server_llm_base_url": "http://invalid-test-url.local",
            "server_llm_api_key": "sk-test",
            "server_llm_model": "test-model",
        },
    )
    assert r_test.status_code == 200
    assert r_test.json()["ok"] is False  # invalid url 应优雅返回 ok: False 而不是 500

    print("✅ server.api_system 系统版本与在线更新测试全部通过！")


if __name__ == "__main__":
    test_database()
    test_database_banks_stats()
    test_auth_and_api()
    test_tunnel()
    test_tunnel_status_and_forwarded_headers()
    test_cloud_ai_and_sync()
    test_system_version_and_update()
    print("\n🎉🎉🎉 全部模块自动化测试验证成功！")
