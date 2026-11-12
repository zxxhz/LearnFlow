"""集成冒烟测试（不依赖 LLM）：直接经服务层构造已完成课程，再走真实 HTTP API 验证。

运行：uv run python scripts/smoke_test.py
- APP_DATA_DIR 未设置时自动指向 backend/data-smoke 隔离目录；检测到真实数据目录
  （桌面版目录名，或 courses/ 已有内容且无 .smoke-ok 标记）会拒绝运行，
  除非显式追加参数 --i-know-this-is-real-data。
- 结束时会用 DELETE /api/courses/{id} 清理测试数据（顺带验证级联删除），
  并把运行前的设置（llm/scenes/preferences）、局域网开关与访问令牌按快照还原。
"""
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

os.environ["APP_SMOKE_TEST"] = "1"
sys.stdout.reconfigure(encoding="utf-8")

# ---------- 数据目录隔离防护：必须在导入 app.*（读取 APP_DATA_DIR）之前决定好数据目录 ----------
_REAL_DATA_DIR_NAME = "com.learnflow.desktop"  # 桌面版真实应用数据目录名（Tauri identifier）
_REAL_DATA_ARG = "--i-know-this-is-real-data"


def _has_real_artifacts(target: Path) -> bool:
    """目录中已有非冒烟产物：courses/ 下有内容，且没有冒烟标记文件。"""
    courses = target / "courses"
    try:
        has_content = courses.is_dir() and any(courses.iterdir())
    except OSError:
        return False
    return has_content and not (target / ".smoke-ok").exists()


_env_dir = os.environ.get("APP_DATA_DIR")
if not _env_dir:
    # 未显式指定数据目录：自动指向仓库内的一次性冒烟目录，不触碰真实数据
    _smoke_dir = Path(__file__).resolve().parents[1] / "data-smoke"
    os.environ["APP_DATA_DIR"] = str(_smoke_dir)
    print(f"[smoke] APP_DATA_DIR 未设置，自动使用隔离数据目录：{_smoke_dir}")
elif Path(_env_dir).name == _REAL_DATA_DIR_NAME or _has_real_artifacts(Path(_env_dir)):
    if _REAL_DATA_ARG not in sys.argv:
        print(
            f"[smoke] 警告：APP_DATA_DIR={_env_dir} 疑似真实数据目录"
            "（桌面版数据目录名，或 courses/ 下已有内容且无 .smoke-ok 标记）。\n"
            "冒烟测试会写入/删除测试课程并改动设置。\n"
            f"确认要在真实数据上运行，请追加参数：{_REAL_DATA_ARG}"
        )
        sys.exit(2)
    print(f"[smoke] 已按 {_REAL_DATA_ARG} 在指定数据目录上运行冒烟测试：{_env_dir}")

import urllib.error
import urllib.request

import uvicorn

# 脚本模式（python scripts/smoke_test.py）只把 scripts/ 放进 sys.path，且项目未安装
# 进 venv（[tool.uv] package = false），必须显式补上 backend 根才能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.db import async_session_factory, init_db
from app.models import Course, Document, Exercise, KnowledgePoint
from app.models.base import utcnow_iso
from app.services.generation.indexing import rebuild_sections

# 给冒烟数据目录留标记：后续重跑时据此识别「该目录是冒烟产物」，不误判为真实数据
if Path(os.environ["APP_DATA_DIR"]).name == "data-smoke":
    try:
        (settings.data_dir / ".smoke-ok").write_text(
            "LearnFlow 冒烟测试数据目录（可整体删除）\n", encoding="utf-8"
        )
    except OSError:
        pass

# ---------- 运行前状态快照（结束时由 _restore_state 统一还原） ----------
_lan_flag_path = settings.data_dir / "lan_access_enabled.txt"
_token_path = settings.data_dir / "access_token.txt"
try:
    _ORIG_LAN_FLAG = _lan_flag_path.read_text(encoding="utf-8") if _lan_flag_path.exists() else None
except OSError:
    _ORIG_LAN_FLAG = None
try:
    _ORIG_TOKEN = _token_path.read_text(encoding="utf-8") if _token_path.exists() else None
except OSError:
    _ORIG_TOKEN = None

SAMPLE_MD = """# 第一章 指针入门

C++ 中指针是一个变量，其值为**内存地址**。指针是 C++ 的核心概念。

```cpp
int x = 42;
int* p = &x;  // p 指向 x
```

## 1.1 指针与引用

- 指针可以为空
- 引用必须初始化

> 注意：解引用空指针是未定义行为。

行内公式 $E=mc^2$ 与块级公式：

$$
\\int_0^1 x^2 \\, dx = \\frac{1}{3}
$$

| 概念 | 含义 |
| --- | --- |
| p | 指针 |
"""


async def seed() -> tuple[str, str]:
    await init_db()
    async with async_session_factory() as db:
        course = Course(title="冒烟测试课程", topic="C++ 指针", status="ready", outline=json.dumps([
            {"index": 1, "title": "第一章 指针入门", "points": ["指针概念"]},
            {"index": 2, "title": "第二章 待生成章", "points": []},
        ]))
        db.add(course)
        await db.flush()
        doc = Document(course_id=course.id, chapter_index=1, title="第一章 指针入门", status="done")
        db.add(doc)
        await db.flush()
        doc_dir = settings.courses_dir / course.id / doc.id
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / "current.md").write_text(SAMPLE_MD, encoding="utf-8")
        doc.file_path = doc_dir.joinpath("current.md").relative_to(settings.data_dir).as_posix()
        doc.version = 1
        doc.summary = "本章介绍指针。"
        sections = await rebuild_sections(db, doc, SAMPLE_MD, 1)
        from app.services.generation.highlight import create_auto_highlights
        from app.services.generation.knowledge import HighlightItem

        meta_highlights = [
            HighlightItem(exact="C++ 中指针是一个变量，其值为内存地址。指针是 C++ 的核心概念。", note="核心定义", color="yellow"),
            HighlightItem(exact="解引用空指针是未定义行为", note="避坑要害", color="pink"),
        ]
        await create_auto_highlights(
            db,
            doc=doc,
            sections=sections,
            raw_markdown=SAMPLE_MD,
            meta_highlights=meta_highlights,
        )
        kp = KnowledgePoint(document_id=doc.id, title="指针概念", summary="指针存放内存地址")
        db.add(kp)
        await db.flush()
        db.add_all([
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="code",
                title="第 1 关：打印两数之和",
                task_md="写一个程序，输出 `2 + 3 = 5`。",
                language="python",
                skeleton_code="a = 2\nb = 3\n# TODO：打印 a + b\n",
                expected_output="2 + 3 = 5\n",
                hints=json.dumps(
                    ["用 print 同时打印算式和结果", "print 里多个参数会用空格连接"], ensure_ascii=False
                ),
                order_index=0,
            ),
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="code",
                title="第 2 关：打印乘积",
                task_md="写一个程序，输出 `2 * 3 = 6`。",
                language="python",
                expected_output="2 * 3 = 6\n",
                hints=json.dumps(
                    ["仿照第 1 关：print 的多参数写法", "把加法换成乘法"], ensure_ascii=False
                ),
                reference_code="print('2 * 3 =', 2 * 3)\n",
                order_index=1,
            ),
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="concept",
                title="指针是什么",
                task_md="用自己的话解释：指针是什么？它存放什么？",
                reference_answer="指针是一个变量，其值为内存地址。【评分要点】提到指针存放地址",
            ),
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="choice",
                title="解引用输出",
                task_md="`int x = 7; int* p = &x;`，`std::cout << *p` 输出什么？",
                options='["x 的地址","7","7 的地址","未定义"]',
                answer="B",
            ),
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="fill",
                title="取地址运算",
                task_md="对变量 x 取地址的表达式是 ______。",
                answer=json.dumps(["&x", "& x"], ensure_ascii=False),
            ),
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="math",
                title="导数计算",
                task_md="计算 $f(x) = \\sin(x^2)$ 的导数 $f'(x)$。",
                expected_output="2*x*cos(x**2)",
            ),
        ])
        await db.commit()
        return course.id, doc.id, kp.id


def call(base: str, path: str, method: str = "GET", body=None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def call_raw(base: str, path: str):
    """非 JSON 响应（导出文件等）：返回 (status, bytes, headers)。headers 键统一小写。"""
    req = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def multipart_body(fields: dict, files: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    """手工构造 multipart/form-data（fields: {name: str}，files: [(name, filename, bytes)]）。"""
    boundary = "----LearnFlowSmokeTestBoundary"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, filename, data in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: text/markdown\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def call_multipart(base: str, path: str, fields: dict, files: list[tuple[str, str, bytes]]):
    body, boundary = multipart_body(fields, files)
    req = urllib.request.Request(
        base + path,
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


IMPORT_MD = """# C++ 指针自学笔记

这是我自己整理的笔记，应当原样保留。

# 第一章 指针基础

指针存放内存地址。

```cpp
int x = 1;
int* p = &x;
```

## 1.1 取地址与解引用

*p 就是 x。

# 第二章 动态内存

new 与 delete 必须配对。
"""


async def _snapshot_settings_raw() -> dict | None:
    """运行前从库里直接读原始设置。

    GET /api/settings 的 api_key 是掩码，而 PUT 掩码只会「保留现值」、无法还原真实
    key，所以快照必须取未掩码的库内值（llm/scenes/preferences）。
    """
    from app.models import AppSetting

    async with async_session_factory() as db:
        row = await db.get(AppSetting, "local")
    if row is None:
        return None
    try:
        llm = json.loads(row.llm or "{}")
        prefs = json.loads(row.preferences or "{}")
    except json.JSONDecodeError:
        return None
    return {
        "llm": {k: (llm.get(k) or "") for k in ("base_url", "api_key", "model")},
        "scenes": {
            name: {k: (scene.get(k) or "") for k in ("base_url", "api_key", "model")}
            for name, scene in (llm.get("scenes") or {}).items()
            if isinstance(scene, dict)
        },
        "preferences": prefs,
    }


def _settings_match(cur: dict, orig: dict) -> bool:
    """对比当前 GET /api/settings 响应与运行前原始值（api_key 按设置页掩码规则比较）。"""
    from app.schemas.settings import _mask  # noqa: SLF001  掩码规则须与设置页一致

    cur_llm = cur.get("llm") or {}
    orig_llm = orig.get("llm") or {}
    if cur_llm.get("base_url") != orig_llm.get("base_url") or cur_llm.get("model") != orig_llm.get("model"):
        return False
    if cur_llm.get("api_key") != _mask(orig_llm.get("api_key") or ""):
        return False
    for name in ("generation", "chat"):
        c = (cur.get("scenes") or {}).get(name) or {}
        o = (orig.get("scenes") or {}).get(name) or {}
        if c.get("model") != o.get("model") or c.get("api_key") != _mask(o.get("api_key") or ""):
            return False
    # preferences 只比较当前可见字段（库里的历史遗留多余键无法经 API 还原，忽略）
    cur_prefs = cur.get("preferences") or {}
    orig_prefs = orig.get("preferences") or {}
    return all(orig_prefs.get(k) == v for k, v in cur_prefs.items())


def _restore_state(base: str, orig_settings: dict | None) -> None:
    """按运行前快照统一还原：设置（llm/scenes/preferences）→ 局域网开关 → 访问令牌。"""
    # 1) 设置页三项：取到过快照且与当前不同才回写
    if orig_settings is not None:
        s, cur = call(base, "/api/settings")
        if s == 200 and not _settings_match(cur, orig_settings):
            call(base, "/api/settings", "PUT", {
                "llm": orig_settings["llm"],
                "scenes": orig_settings["scenes"],
                "preferences": orig_settings["preferences"],
            })
    # 2) 局域网开关：原本不存在 → 删除；存在 → 写回原内容
    try:
        if _ORIG_LAN_FLAG is None:
            if _lan_flag_path.exists():
                _lan_flag_path.unlink()
        else:
            _lan_flag_path.write_text(_ORIG_LAN_FLAG, encoding="utf-8")
    except OSError:
        pass
    # 3) 访问令牌：原本存在才写回原内容
    try:
        if _ORIG_TOKEN is not None:
            _token_path.write_text(_ORIG_TOKEN, encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    # 确保冒烟测试验证默认无配置状态（清理残留的局域网开关标记）
    lan_flag = settings.data_dir / "lan_access_enabled.txt"
    if lan_flag.exists():
        try:
            lan_flag.unlink()
        except OSError:
            pass

    course_id, document_id, kp_id = asyncio.run(seed())
    # 运行前快照设置原始值（llm/scenes/preferences，含未掩码 api_key），结束时统一还原
    orig_settings = asyncio.run(_snapshot_settings_raw())
    port = settings.port  # 尊重 APP_PORT：8420 被已在跑的实例占用时可换端口
    base = f"http://127.0.0.1:{port}"
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(2.5)

    ok = True

    def check(name: str, cond: bool, detail=""):
        nonlocal ok
        print(("  ✅" if cond else "  ❌"), name, detail if not cond else "")
        if not cond:
            ok = False

    # 1. 静态托管
    with urllib.request.urlopen(base + "/") as r:
        html = r.read().decode()
    check("GET / 返回前端 index.html", "LearnFlow" in html and r.status == 200)

    # 1.0 PWA 规范资产校验（manifest / sw.js / 图标）
    with urllib.request.urlopen(base + "/manifest.webmanifest") as r:
        manifest_data = json.loads(r.read().decode())
    check("PWA manifest.webmanifest 正常返回", r.status == 200 and manifest_data.get("short_name") == "LearnFlow" and len(manifest_data.get("icons", [])) >= 2)

    s, sw_bytes, sw_hdrs = call_raw(base, "/sw.js")
    check("PWA sw.js 正常返回且携带 Service-Worker-Allowed 响应头", s == 200 and b"learnflow" in sw_bytes.lower() and sw_hdrs.get("service-worker-allowed") == "/")

    s, icon_bytes, _ = call_raw(base, "/icons/icon-192.png")
    check("PWA 192 图标正常返回", s == 200 and len(icon_bytes) > 100)

    # 1.1 系统 open-url 接口校验（打开默认浏览器）
    s, body = call(base, "/api/system/open-url", "POST", {"url": "file:///etc/passwd"})
    check("open-url 拦截非 http/https 协议", s == 400)
    s, body = call(base, "/api/system/open-url", "POST", {"url": "https://github.com/zxxhz/LearnFlow/releases"})
    check("open-url 正常触发默认浏览器", s == 200 and body.get("ok") is True)

    # 1.2 局域网访问配置与令牌管理
    s, body = call(base, "/api/system/access-info")
    check("局域网访问默认关闭", s == 200 and body.get("lan_mode") is False and body.get("lan_enabled") is False)
    s, body = call(base, "/api/system/lan-access?enabled=true", "POST")
    check("设置中开启局域网访问", s == 200 and body.get("lan_mode") is True and body.get("lan_enabled") is True and bool(body.get("token")))
    old_token = body.get("token")
    s, body = call(base, "/api/system/access-token/rotate", "POST")
    check("重新生成访问令牌", s == 200 and body.get("token") != old_token)
    s, body = call(base, "/api/system/lan-access?enabled=false", "POST")
    check("设置中关闭局域网访问", s == 200 and body.get("lan_mode") is False and body.get("lan_enabled") is False)

    # 1.3 局域网访问门禁中间件全链路测试（静态资源免拦 / Cookie自动下发 / Header认证 / 401 / 403）
    async def _test_access_guard():
        from app.main import _AccessGuard
        from fastapi.responses import PlainTextResponse

        async def ok_app(scope, receive, send):
            resp = PlainTextResponse("ok")
            await resp(scope, receive, send)

        guard = _AccessGuard(ok_app)

        async def run_req(path: str, client_ip: str, query: str = "", headers: list | None = None):
            res_headers = []
            status = 0
            body_bytes = b""
            scope = {
                "type": "http",
                "client": (client_ip, 12345),
                "path": path,
                "query_string": query.encode(),
                "headers": headers or [],
            }
            async def dummy_receive():
                return {"type": "http.request"}
            async def dummy_send(msg):
                nonlocal status, body_bytes, res_headers
                if msg["type"] == "http.response.start":
                    status = msg["status"]
                    res_headers = msg.get("headers", [])
                elif msg["type"] == "http.response.body":
                    body_bytes += msg.get("body", b"")
            await guard(scope, dummy_receive, dummy_send)
            return status, body_bytes, {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in res_headers}

        from app.services.system import get_access_token, set_lan_access_enabled
        set_lan_access_enabled(True)
        tok = get_access_token()

        st, _, _ = await run_req("/api/test", "127.0.0.1")
        assert st == 200, f"loopback failed: {st}"

        st, _, _ = await run_req("/assets/index-test.js", "192.168.1.99")
        assert st == 200, f"asset bypass failed: {st}"

        st, _, hdrs = await run_req("/", "192.168.1.99", query=f"token={tok}")
        assert st == 200 and "set-cookie" in hdrs and f"lf_token={tok}" in hdrs["set-cookie"], f"query token failed: {st}, {hdrs}"

        st, _, _ = await run_req("/api/test", "192.168.1.99", headers=[(b"cookie", f"lf_token={tok}".encode())])
        assert st == 200, f"cookie auth failed: {st}"

        st, _, _ = await run_req("/api/test", "192.168.1.99", headers=[(b"x-access-token", tok.encode())])
        assert st == 200, f"header auth failed: {st}"

        st, _, _ = await run_req("/api/test", "192.168.1.99")
        assert st == 401, f"unauth check failed: {st}"

        set_lan_access_enabled(False)
        st, _, _ = await run_req("/", "192.168.1.99", query=f"token={tok}")
        assert st == 403, f"disable lan failed: {st}"
        return True

    try:
        guard_ok = asyncio.run(_test_access_guard())
    except Exception as ex:
        guard_ok = False
        print("  _AccessGuard test error:", ex)
    check("局域网门禁全链路校验(静态资源免拦/Cookie/Header/拦截)", guard_ok)

    # 2. 文档内容 + 块对齐
    s, body = call(base, f"/api/documents/{document_id}/content")
    check("文档 content 接口", s == 200)
    if s == 200:
        check("markdown 返回", "指针" in body["markdown"])
        types = [b["block_type"] for b in body["blocks"]]
        check("9 个块全部索引", len(body["blocks"]) == 9, str(types))
        check("块类型齐全", types == ["heading", "paragraph", "code", "heading", "list", "quote", "paragraph", "math", "table"], str(types))

    # 2.5 自动划重点回显（生成课程时自动提取与落库）
    s, auto_anns = call(base, f"/api/documents/{document_id}/annotations")
    check("自动划重点接口回显", s == 200 and len(auto_anns) >= 2, json.dumps(auto_anns, ensure_ascii=False)[:200])
    if s == 200 and auto_anns:
        first_auto = auto_anns[0]
        check(
            "自动划重点五元组与字段完整",
            bool(first_auto["exact"])
            and bool(first_auto["section_id"])
            and first_auto["status"] == "active"
            and first_auto["note"] in ("核心定义", "避坑要害", "重点提炼"),
            json.dumps(first_auto, ensure_ascii=False)[:150],
        )
        s, auto_conv = call(base, f"/api/annotations/{first_auto['id']}/conversation")
        check("自动划重点对话绑定正常", s == 200 and bool(auto_conv.get("conversation_id")))

    # 3. 创建标注
    s, body = call(base, f"/api/documents/{document_id}/annotations", "POST", {
        "section_id": body["blocks"][1]["id"],
        "exact": "其值为**内存地址**",
        "prefix": "C++ 中指针是一个变量，",
        "suffix": "。指针是 C++ 的核心概念。",
        "start_offset": 11,
        "end_offset": 21,
        "color": "green",
    })
    check("创建标注", s == 200 and "conversation_id" in body, json.dumps(body, ensure_ascii=False)[:200])
    ann_id = body.get("annotation", {}).get("id", "")
    conv_id = body.get("conversation_id", "")
    s, body2 = call(base, f"/api/annotations/{ann_id}/conversation")
    check("标注→对话查询", s == 200 and body2.get("conversation_id") == conv_id)

    # 4. 代码运行沙箱（PRD §5.8）：文档代码块走真实 API
    code_block = next(b for b in call(base, f"/api/documents/{document_id}/content")[1]["blocks"] if b["block_type"] == "code")
    s, body = call(base, "/api/executions", "POST", {
        "document_id": document_id,
        "section_id": code_block["id"],
        "language": "python",
        "code": "print('2 + 3 =', 2 + 3)",
    })
    check("执行 Python → success + 输出", s == 200 and body["status"] == "success" and "2 + 3 = 5" in body["stdout"], json.dumps(body, ensure_ascii=False)[:200])
    s, body = call(base, "/api/executions", "POST", {
        "document_id": document_id,
        "section_id": code_block["id"],
        "language": "python",
        "code": "while True:\n    pass",
    })
    check("死循环 → timeout 终止", s == 200 and body["status"] == "timeout", json.dumps(body, ensure_ascii=False)[:150])
    s, body = call(base, "/api/executions", "POST", {
        "document_id": document_id,
        "section_id": code_block["id"],
        "language": "cpp",
        "code": "int main(){return 0;}",
    })
    check("C++（无编译器环境）→ 友好提示", s == 200 and body["status"] in ("compiler_missing", "success"))
    s, body = call(base, "/api/executions", "POST", {
        "document_id": document_id,
        "section_id": code_block["id"],
        "language": "ruby",
        "code": "puts 1",
    })
    check("不支持的语言 → 400 中文提示", s == 400 and "暂不支持" in str(body.get("detail", "")), str(body)[:150])
    s, body = call(base, f"/api/documents/{document_id}/executions")
    check("执行历史回显（每块最新一条）", s == 200 and len(body) == 1 and body[0]["status"] == "compiler_missing" or (s == 200 and len(body) >= 1))

    # 6.5 运行环境检测 + 安装进度接口（只查状态，不触发真实下载）
    s, body = call(base, "/api/runtime/status")
    check("运行环境状态接口", s == 200 and set(body) >= {"python", "cpp", "installable", "toolchains_dir"} and body["python"]["installed"], str(body)[:150])
    s, body = call(base, "/api/runtime/install/status")
    check("安装进度接口", s == 200 and set(body.get("components", {})) == {"python", "cpp"} and body.get("active") is None, str(body)[:150])
    s, body = call(base, "/api/runtime/install", "POST", {"component": "ruby"})
    check("未知组件 → 4xx 校验", s in (400, 422), str(body)[:120])

    # 6.6 闯关练习（PRD §5.10）：列表回显 / 顺序解锁 / 代码关自动判定 / 删除（LLM 依赖路径见 §8.5）
    s, body = call(base, f"/api/exercises?document_id={document_id}")
    check(
        "练习列表（含知识点标题）",
        s == 200 and len(body) == 6 and all(e["kp_title"] == "指针概念" for e in body),
        json.dumps(body, ensure_ascii=False)[:200],
    )
    if s == 200:
        ex_code = next(e for e in body if e["kind"] == "code" and e["order_index"] == 0)
        ex_code2 = next(e for e in body if e["kind"] == "code" and e["order_index"] == 1)
        ex_concept = next(e for e in body if e["kind"] == "concept")
        ex_choice = next(e for e in body if e["kind"] == "choice")
        ex_fill = next(e for e in body if e["kind"] == "fill")
        ex_math = next(e for e in body if e["kind"] == "math")
        check("未作答时 latest_attempt 为空", ex_code["latest_attempt"] is None)
        check(
            "闯关字段回显（提示列表/首关解锁/次关锁定）",
            isinstance(ex_code["hints"], list)
            and len(ex_code["hints"]) == 2
            and ex_code["unlocked"] is True
            and ex_code2["unlocked"] is False
            and ex_code2["ever_passed"] is False,
            json.dumps({"h": ex_code["hints"], "u1": ex_code["unlocked"], "u2": ex_code2["unlocked"]}, ensure_ascii=False),
        )
        s, body = call(base, f"/api/exercises/{ex_code2['id']}/submit", "POST", {"content": "print('2 * 3 =', 2 * 3)"})
        check("未通关上一关提交第 2 关 → 403", s == 403, str(body)[:120])
        s, body = call(base, f"/api/exercises/{ex_code['id']}/submit", "POST", {"content": "print('2 + 3 =', 2 + 3)"})
        check("代码题正确解 → passed", s == 200 and body["passed"] is True and body["status"] == "success", json.dumps(body, ensure_ascii=False)[:200])
        s, body = call(base, f"/api/exercises/{ex_code2['id']}/submit", "POST", {"content": "print('2 * 3 =', 2 * 3)"})
        check("通过第 1 关后第 2 关解锁并判过", s == 200 and body["passed"] is True, json.dumps(body, ensure_ascii=False)[:200])
        s, body = call(base, f"/api/exercises/{ex_code['id']}/submit", "POST", {"content": "print('2 + 3 =', 2 + 4)"})
        check("代码题输出不符 → 未通过", s == 200 and body["passed"] is False, json.dumps(body, ensure_ascii=False)[:200])
        s, body = call(base, f"/api/exercises/{ex_code['id']}/submit", "POST", {"content": "  "})
        check("空提交 → 400 校验", s == 400, str(body)[:120])
        s, body = call(base, f"/api/exercises/{ex_choice['id']}/submit", "POST", {"content": "B"})
        check("单选正确 → passed", s == 200 and body["passed"] is True, json.dumps(body, ensure_ascii=False)[:120])
        s, body = call(base, f"/api/exercises/{ex_choice['id']}/submit", "POST", {"content": "A"})
        check("单选错误 → 未通过+正确答案", s == 200 and body["passed"] is False and "B" in body["feedback"], json.dumps(body, ensure_ascii=False)[:120])
        s, body = call(base, f"/api/exercises/{ex_fill['id']}/submit", "POST", {"content": "  &X "})
        check("填空归一化 → passed", s == 200 and body["passed"] is True, json.dumps(body, ensure_ascii=False)[:120])
        s, body = call(base, f"/api/exercises/{ex_math['id']}/submit", "POST", {"content": "cos(x**2)*2*x"})
        check("数学题代数等价表达式 → passed", s == 200 and body["passed"] is True, json.dumps(body, ensure_ascii=False)[:120])
        s, body = call(base, f"/api/exercises/{ex_math['id']}/submit", "POST", {"content": "2*x"})
        check("数学题非等价表达式 → 未通过", s == 200 and body["passed"] is False, json.dumps(body, ensure_ascii=False)[:120])
        s, body = call(base, f"/api/exercises?document_id={document_id}")
        latest = next(e for e in body if e["id"] == ex_code["id"])["latest_attempt"]
        check("提交后最新作答回显", latest is not None and latest["passed"] is False)
        relisted = {e["id"]: e for e in body}
        check(
            "通关后解锁状态回显（第 2 关已解锁且 ever_passed）",
            relisted[ex_code2["id"]]["unlocked"] is True and relisted[ex_code2["id"]]["ever_passed"] is True,
            f"unlocked={relisted[ex_code2['id']]['unlocked']} ever_passed={relisted[ex_code2['id']]['ever_passed']}",
        )
        s, body = call(base, f"/api/exercises/wrongbook")
        wb = {e["id"] for e in body}
        wb_ok = ex_code["id"] in wb and ex_choice["id"] in wb and ex_fill["id"] not in wb and ex_math["id"] in wb
        check(
            "错题本：做错的在、做对的不在",
            s == 200 and wb_ok,
            f"n={len(body)} code_in={ex_code['id'] in wb} choice_in={ex_choice['id'] in wb} fill_out={ex_fill['id'] not in wb} math_in={ex_math['id'] in wb}",
        )
        if s == 200 and not wb_ok:
            # 取证模式：错题本断言失败时立刻中止（跳过末尾的删除清理），保留 DB 现场
            print("!! 错题本断言失败，保留现场中止")
            sys.exit(3)
        s, body = call(base, f"/api/exercises/{ex_concept['id']}", "DELETE")
        check("删除练习题", s == 200)
        s, body = call(base, f"/api/exercises?document_id={document_id}")
        check("删除后列表剩 5 题", s == 200 and len(body) == 5)
        s, body = call(base, f"/api/conversations/{conv_id}/messages/stream", "POST", {"content": "   "})
        check("助教流式空内容 → 400", s == 400, str(body)[:120])
        s, body = call(base, "/api/conversations/nonexistent/messages/stream", "POST", {"content": "hi"})
        check("助教流式不存在会话 → 404", s == 404, str(body)[:120])

        # 6.61 学习者画像与认知诊断模型验证
        async def _test_learner_models():
            from app.core.db import async_session_factory
            from app.models.base import new_id
            from app.models.study import LearnerProfile, LearnerMisconception
            uid = new_id()
            async with async_session_factory() as db_session:
                lp = LearnerProfile(id=uid, background_summary="C++初学者，掌握基础语法", socratic_mode=True)
                db_session.add(lp)
                lm = LearnerMisconception(topic="C++ 指针", tag="precedence_error", evidence="混淆 *p++ 运算顺序", status="active")
                db_session.add(lm)
                await db_session.commit()
                queried_lp = await db_session.get(LearnerProfile, lp.id)
                queried_lm = await db_session.get(LearnerMisconception, lm.id)
                return queried_lp is not None and queried_lm is not None

        check("认知画像与迷思模型读写正常", asyncio.run(_test_learner_models()))

        # 6.611 学习者画像 API 闭环测试 (GET, PUT, RESET)
        s, p_init = call(base, "/api/study/profile", "GET")
        check("获取学习者画像 API → 200", s == 200 and "background_summary" in p_init)
        s, p_put = call(base, "/api/study/profile", "PUT", {"background_summary": "测试画像：深入理解异步编程", "socratic_mode": False})
        check("更新学习者画像 API → 200", s == 200 and p_put.get("socratic_mode") is False and "测试画像" in p_put.get("background_summary", ""))
        s, p_reset = call(base, "/api/study/profile/reset", "POST")
        check("重置学习者画像 API → 200", s == 200 and p_reset.get("socratic_mode") is True and p_reset.get("background_summary") == "")

        # 6.62 Agent 工具集独立执行验证 (run_sandbox_code, render_math_plot, inspect_exercise)
        async def _test_agent_tools():
            from app.core.db import async_session_factory
            from app.services.agent_tools import execute_agent_tool
            t_code = await execute_agent_tool("run_sandbox_code", {"language": "python", "code": "print(21 * 2)"})
            code_ok = t_code.get("status") == "success" and "42" in t_code.get("stdout", "")
            t_plot = await execute_agent_tool("render_math_plot", {"expressions": "x**2"})
            plot_ok = t_plot.get("status") == "success" and t_plot.get("svg_length", 0) > 0
            async with async_session_factory() as db_session:
                t_inspect = await execute_agent_tool("inspect_exercise", {"exercise_id": ex_code["id"]}, db=db_session)
                inspect_ok = t_inspect.get("title") == "第 1 关：打印两数之和"
            return code_ok and plot_ok and inspect_ok

        check("Agent 工具集（沙箱/绘图/查题）独立调用正常", asyncio.run(_test_agent_tools()))


    # 6.63 认知画像分学科隔离 + 证据链回溯 + 盲区自动闭环（v0.4.69）
    async def _test_profile_scope_and_evidence():
        from app.core.db import async_session_factory as _db_factory
        from sqlalchemy import select as _select

        from app.models import Exercise as _Exercise
        from app.models.study import LearnerMisconception
        from app.services.profile import format_profile_for_prompt

        async with _db_factory() as db:
            # 用 API 视角取一道真实存在的代码题作为证据来源（不依赖前段局部变量）
            code_ex = (
                await db.scalars(
                    _select(_Exercise).where(
                        _Exercise.document_id == document_id,
                        _Exercise.kind == "code",
                        _Exercise.quiz_id == "",
                        _Exercise.parent_exercise_id == "",
                    )
                )
            ).first()
            misc_code = LearnerMisconception(
                topic="C++ 指针算术步长", tag="概念混淆", evidence="冒烟测试用",
                status="active", scope="coding",
                source_type="exercise", source_id=code_ex.id,
            )
            misc_math = LearnerMisconception(
                topic="复合函数链式法则", tag="公式条件误用", evidence="冒烟测试用",
                status="active", scope="math",
            )
            db.add_all([misc_code, misc_math])
            await db.commit()
            coding_text = await format_profile_for_prompt(db, scope="coding")
            math_text = await format_profile_for_prompt(db, scope="math")
            all_text = await format_profile_for_prompt(db)
            return misc_code.id, code_ex.id, (
                "指针算术步长" in coding_text and "链式法则" not in coding_text
                and "链式法则" in math_text and "指针算术步长" not in math_text
                and "指针算术步长" in all_text and "链式法则" in all_text
            )

    misc_code_id, misc_src_ex_id, scope_ok = asyncio.run(_test_profile_scope_and_evidence())
    check("画像盲区分学科注入过滤（coding/math 互不串味，全量兼容）", scope_ok)
    s, p_body = call(base, "/api/study/profile", "GET")
    scoped = next((m for m in p_body.get("misconceptions", []) if m["id"] == misc_code_id), None)
    check(
        "画像 API 回显 scope 与证据出处（练习溯源）",
        s == 200 and scoped is not None and scoped.get("scope") == "coding"
        and "闯关练习" in (scoped.get("source_label") or ""),
        json.dumps(scoped, ensure_ascii=False)[:200] if scoped else str(s),
    )
    # 盲区证据闭环：来源题独立做对（未存疑）→ 盲区自动 resolved
    s, body = call(base, f"/api/exercises/{misc_src_ex_id}/submit", "POST", {"content": "print('2 + 3 =', 2 + 3)"})
    check("来源题独立做对（自动闭环前置）", s == 200 and body.get("passed") is True, str(body)[:150])
    auto_ok = False
    for _ in range(20):
        s, p_body = call(base, "/api/study/profile", "GET")
        if all(m["id"] != misc_code_id for m in p_body.get("misconceptions", [])):
            auto_ok = True
            break
        time.sleep(0.3)
    check("独立做对后盲区自动 resolved（证据闭环）", auto_ok)

    # 6.64 出题落库前沙箱自验（v0.4.69，fixer=None 纯确定性路径）
    async def _test_selfverify():
        from app.services.exercise import _selfverify_code, _selfverify_math

        r1 = await _selfverify_code("python", "print('hello')", "hello")
        r2 = await _selfverify_code("python", "print('hello')", "world")
        r3 = await _selfverify_code("python", "def broken(:\n", "x")
        m1 = await _selfverify_math("x**2 + 2*x + 1", "(x+1)**2")
        m2 = await _selfverify_math("这不是数学(((", "")
        return r1, r2, r3, m1, m2

    r1, r2, r3, m1, m2 = asyncio.run(_test_selfverify())
    check("自验：代码实测一致 → verified=1", r1 is not None and r1[2] == 1, str(r1))
    check(
        "自验：输出不符且无 LLM → 按实际输出校准 verified=2",
        r2 is not None and r2[2] == 2 and "hello" in (r2[1] or ""),
        str(r2),
    )
    check("自验：编译失败且无 LLM → 丢弃", r3 is None, str(r3))
    check("自验：数学表达式可解析 → verified=1", m1 is not None and m1[2] == 1, str(m1))
    check("自验：非法数学表达式 → 丢弃", m2 is None, str(m2))

    # 6.645 讲义单段修订 → 下游练习一致性提醒（v0.4.69）
    async def _link_kp_to_paragraph_section() -> str:
        from app.core.db import async_session_factory as _db_factory
        from sqlalchemy import select as _select

        from app.models import KnowledgePoint, Section

        async with _db_factory() as db:
            sec = (
                await db.scalars(
                    _select(Section)
                    .where(Section.document_id == document_id, Section.block_type == "paragraph")
                    .order_by(Section.order_index)
                )
            ).first()
            kp_row = await db.get(KnowledgePoint, kp_id)
            kp_row.section_ids = json.dumps([sec.id])
            await db.commit()
            return sec.id

    _rev_sec_id = asyncio.run(_link_kp_to_paragraph_section())
    s, body = call(
        base,
        f"/api/documents/{document_id}/sections/{_rev_sec_id}/revise",
        "POST",
        {"instruction": "冒烟测试修订", "apply": True, "revised_markdown": "修订后的段落：指针是存放内存地址的变量，冒烟测试专用表述。"},
    )
    check(
        "讲义修订 apply 成功且返回 affected_practice（命中 1 个 KP / 5 道练习）",
        s == 200 and body.get("applied") is True
        and len(body.get("affected_practice") or []) == 1
        and body["affected_practice"][0]["exercise_count"] == 5,
        json.dumps(body.get("affected_practice"), ensure_ascii=False)[:200],
    )

    # 6.646 场景槽位第三槽 task（v0.4.69）：写入 + 留空继承
    s, body = call(base, "/api/settings", "PUT", {"scenes": {"task": {"base_url": "https://task.example.com/v1", "api_key": "task-key-12345678", "model": "task-model-x"}}})
    check("task 场景槽位写入", s == 200 and body["scenes"]["task"]["model"] == "task-model-x", str(body)[:150])
    s, body = call(base, "/api/settings", "PUT", {"scenes": {"task": {"model": ""}}})
    check(
        "task 槽位 model 留空回落主配置（api_key 继承不丢）",
        s == 200 and body["scenes"]["task"]["model"] == "" and (body["scenes"]["task"]["api_key"] or "") != "",
        str(body)[:150],
    )

    # 6.647 绘图 AI 自修端点（v0.4.69）：未配 LLM → 400 友好提示
    s, body = call(base, "/api/math/fix", "POST", {"expressions": "sin(x", "error": "无法解析"})
    check("绘图 AI 自修未配 LLM → 400", s == 400 and "LLM" in str(body.get("detail", "")), str(body)[:150])

    # 6.65 课程改名（PATCH title）
    s, orig_course = call(base, f"/api/courses/{course_id}")
    s, body = call(base, f"/api/courses/{course_id}", "PATCH", {"title": "指针入门（已改名）"})
    check("课程改名", s == 200 and body["title"] == "指针入门（已改名）", json.dumps(body, ensure_ascii=False)[:150])
    s, body = call(base, f"/api/courses/{course_id}", "PATCH", {"title": "   "})
    check("课程改名为空 → 4xx", s in (400, 422), str(body)[:120])
    s, body = call(base, f"/api/courses/{course_id}", "PATCH", {"title": orig_course["title"]})
    check("课程改名还原", s == 200 and body["title"] == orig_course["title"])

    # 6.68 统一 AI 助教（v0.5.0）：L0 已学知识目录 / 会话幂等 / 检索工具 / 流式端点路由
    async def _test_assistant_chain():
        from app.core.db import async_session_factory as _dbf
        from app.services.context import build_learned_knowledge_index
        from app.services.assistant import get_or_create_assistant_session
        from app.services.agent_tools.registry import execute_tool

        async with _dbf() as s:
            idx = await build_learned_knowledge_index(s, exclude_document_id=document_id)
            conv1 = await get_or_create_assistant_session(s, "document", document_id)
            conv2 = await get_or_create_assistant_session(s, "document", document_id)
            conv_g1 = await get_or_create_assistant_session(s, "global", "")
            conv_g2 = await get_or_create_assistant_session(s, "global", "")
            learned = await execute_tool("lookup_learned_section", {"keyword": "指针"}, db=s)
            excluded = await execute_tool(
                "lookup_learned_section", {"keyword": "指针"}, db=s, context={"exclude_document_id": document_id}
            )
            mistakes = await execute_tool("lookup_past_mistakes", {"keyword": "指针"}, db=s)
            return idx, conv1.id, conv2.id, conv_g1.id, conv_g2.id, learned, excluded, mistakes

    idx, conv_a, conv_b, conv_g1, conv_g2, learned, excluded, mistakes = asyncio.run(_test_assistant_chain())
    check(
        "L0 已学知识目录：含课程/章节/KP 与掌握度且受长度预算约束",
        "冒烟测试课程" in idx
        and "指针概念" in idx
        and "第一章 指针入门" in idx
        and any(m in idx for m in ("已掌握", "学习中", "未测"))
        and len(idx) <= 4500,
        f"len={len(idx)} head={idx[:80]!r}",
    )
    check(
        "助教会话按归属域幂等（同章同会话、全局独立）",
        conv_a == conv_b and conv_g1 == conv_g2 and conv_g1 != conv_a,
        f"doc={conv_a[:8]} global={conv_g1[:8]}",
    )
    check(
        "lookup_learned_section：命中已学章节并带来源引用",
        learned.get("status") == "success"
        and len(learned.get("hits", [])) >= 1
        and bool(learned["hits"][0].get("references")),
        json.dumps(learned, ensure_ascii=False)[:160],
    )
    check(
        "lookup_learned_section：排除当前章节（防把正在读的内容当旧知）",
        excluded.get("status") == "not_found",
        json.dumps(excluded, ensure_ascii=False)[:120],
    )
    check(
        "lookup_past_mistakes：命中历史错题（课程练习）",
        mistakes.get("status") == "success" and len(mistakes.get("hits", [])) >= 1,
        json.dumps(mistakes, ensure_ascii=False)[:160],
    )
    s, body = call(base, "/api/assistant/session", "POST", {"context_type": "document", "context_id": document_id})
    check(
        "助教会话 API 幂等取回（与直连服务层同 ID）",
        s == 200 and body.get("conversation_id") == conv_a,
        str(body)[:120],
    )
    s, body = call(base, "/api/assistant/session", "POST", {"context_type": "bogus", "context_id": ""})
    check("助教会话非法归属域 → 400", s == 400, str(body)[:120])
    s, body = call(
        base,
        f"/api/conversations/{conv_a}/messages/stream",
        "POST",
        {"content": "指针和引用有什么区别？", "scene": {"kind": "reading", "document_id": document_id}},
    )
    check(
        "助教流式端点未配 LLM → 400 快速失败",
        s == 400 and "LLM" in str(body.get("detail", "")),
        str(body)[:120],
    )
    s, body = call(base, f"/api/conversations/{conv_id}/messages/stream", "POST", {"content": "hi"})
    check("划线会话拒绝走助教端点 → 400", s == 400, str(body)[:120])

    # 6.69 api_key 落盘 DPAPI 加密（v0.5.2 体检 P1：沙箱同用户可读宿主文件，明文密钥可被直接提取）
    s, body = call(base, "/api/settings", "PUT", {"llm": {"base_url": "https://canary.example.com/v1", "api_key": "sk-test-canary-9527", "model": "canary-model"}})
    check("canary key 写入设置", s == 200, str(body)[:120])

    async def _read_stored_llm():
        from app.core.db import async_session_factory as _dbf3
        from app.models import AppSetting

        async with _dbf3() as s3:
            row = await s3.get(AppSetting, "local")
            return json.loads(row.llm) if row and row.llm else {}

    cfg_stored = asyncio.run(_read_stored_llm())
    stored_key = str((cfg_stored or {}).get("api_key", ""))
    check(
        "api_key 落盘为 DPAPI 密文（非明文）",
        stored_key.startswith("dpapi:") and "sk-test-canary-9527" not in json.dumps(cfg_stored),
        f"prefix={stored_key[:12]!r}",
    )
    from app.services.secretbox import decrypt_secret as _decrypt_secret

    check(
        "DPAPI 解密还原明文密钥",
        _decrypt_secret(stored_key) == "sk-test-canary-9527",
        "roundtrip",
    )
    # 还原为未配置态（api_key 继承语义下 model 置空即可让后续「LLM 未配置 → 400」检查成立）
    s, body = call(base, "/api/settings", "PUT", {"llm": {"base_url": "", "api_key": "", "model": ""}})
    check("设置还原为未配置态", s == 200, str(body)[:120])

    # 6.70 全量工具扩权（v0.5.6）：场景裁剪 / 读类直调 / 确认分级 / 自包含写链路
    async def _test_tool_surface():
        from app.core.db import async_session_factory as _dbf6
        from app.services.agent_tools.registry import (
            DESTRUCTIVE_TOOLS,
            SENSITIVE_TOOLS,
            execute_tool,
            select_tool_schemas,
        )
        from app.services.agent_tools.runner import _summarize_args

        async with _dbf6() as s6:
            doc_names = {t["function"]["name"] for t in select_tool_schemas("document")}
            bank_names = {t["function"]["name"] for t in select_tool_schemas("bank_question")}
            global_names = {t["function"]["name"] for t in select_tool_schemas("global")}

            lc = await execute_tool("list_courses", {}, db=s6)
            rd = await execute_tool("read_document", {"document_id": document_id}, db=s6)
            first_sec = (rd.get("sections") or [{}])[0].get("section_id", "")
            rsec = (
                await execute_tool(
                    "read_document", {"document_id": document_id, "section_id": first_sec}, db=s6
                )
                if first_sec
                else {"status": "skipped"}
            )
            le = await execute_tool("list_exercises", {"document_id": document_id}, db=s6)
            lw = await execute_tool("list_wrong_questions", {}, db=s6)
            sr = await execute_tool("get_study_report", {}, db=s6)
            gp = await execute_tool("get_learner_profile", {}, db=s6)
            lb = await execute_tool("list_banks", {}, db=s6)
            lmm = await execute_tool("list_mindmaps", {}, db=s6)
            la = await execute_tool("list_annotations", {"document_id": document_id}, db=s6)
            lbk1 = await execute_tool("list_backups", {}, db=s6)
            gs = await execute_tool("get_sync_status", {}, db=s6)
            unknown = await execute_tool("no_such_tool", {}, db=s6)

            # 写入→回读→还原（模型默认 socratic_mode=True）：先置 False 证明写入生效，再还原默认
            p1 = await execute_tool("update_learner_profile", {"socratic_enabled": False}, db=s6)
            gp2 = await execute_tool("get_learner_profile", {}, db=s6)
            p2 = await execute_tool("update_learner_profile", {"socratic_enabled": True}, db=s6)

            bk = await execute_tool("create_backup", {}, db=s6)
            lbk2 = await execute_tool("list_backups", {}, db=s6)
            dr = await execute_tool("delete_resource", {"kind": "backup", "id": bk.get("backup", "")}, db=s6)
            lbk3 = await execute_tool("list_backups", {}, db=s6)

            return {
                "doc_names": doc_names,
                "bank_names": bank_names,
                "global_names": global_names,
                "sensitive": SENSITIVE_TOOLS,
                "destructive": DESTRUCTIVE_TOOLS,
                "sum_code": _summarize_args({"code": "print(" + "x" * 200 + ")", "language": "python"}),
                "lc": lc, "rd": rd, "rsec": rsec, "le": le, "lw": lw, "sr": sr, "gp": gp,
                "lb": lb, "lmm": lmm, "la": la, "lbk1": lbk1, "gs": gs, "unknown": unknown,
                "p1": p1, "gp2": gp2, "p2": p2, "bk": bk, "lbk2": lbk2, "dr": dr, "lbk3": lbk3,
            }

    ts = asyncio.run(_test_tool_surface())
    dn, bn, gn = ts["doc_names"], ts["bank_names"], ts["global_names"]
    check(
        "场景裁剪：document 集含讲义/练习域、不含题库写工具；bank 集反之；global 全量",
        "generate_exercises" in dn
        and "create_annotation" in dn
        and "add_bank_questions" not in dn
        and "correct_bank_question" not in dn
        and "add_bank_questions" in bn
        and "generate_exercises" not in bn
        and "create_course" in gn
        and "trigger_sync" in gn
        and len(gn) >= len(dn),
        f"doc={len(dn)} bank={len(bn)} global={len(gn)}",
    )
    check(
        "确认分级：写类全部 SENSITIVE，DESTRUCTIVE 为其子集且含删除/同步/重生成",
        {"run_sandbox_code", "correct_bank_question", "delete_resource", "create_course"} <= ts["sensitive"]
        and ts["destructive"] <= ts["sensitive"]
        and {"delete_resource", "trigger_sync", "regenerate_document"} <= ts["destructive"],
        str(ts["destructive"]),
    )
    check(
        "确认卡参数摘要：大段内容折叠为字数、短值截断",
        "字内容" in ts["sum_code"] and "language=python" in ts["sum_code"],
        ts["sum_code"][:120],
    )
    check("list_courses：命中冒烟课程", ts["lc"].get("status") == "success" and any(c.get("id") == course_id for c in ts["lc"].get("courses", [])), json.dumps(ts["lc"], ensure_ascii=False)[:150])
    check(
        "read_document：整章模式带正文+小节目录；小节模式带原文（首个小节可为纯标题块）",
        ts["rd"].get("status") == "success"
        and len(ts["rd"].get("content") or "") > 50
        and len(ts["rd"].get("sections") or []) >= 1
        and ts["rsec"].get("status") == "success"
        and len(ts["rsec"].get("content") or "") >= 1,
        json.dumps({"rd": str(ts["rd"])[:80], "rsec": str(ts["rsec"])[:80]}, ensure_ascii=False),
    )
    check("list_exercises：返回结构合法（success/empty 均可）", ts["le"].get("status") in ("success", "empty"), str(ts["le"])[:120])
    check("list_wrong_questions：返回结构合法", ts["lw"].get("status") in ("success", "empty"), str(ts["lw"])[:120])
    check("get_study_report：含报告主体", ts["sr"].get("status") == "success" and isinstance(ts["sr"].get("report"), dict), str(ts["sr"])[:150])
    check("get_learner_profile：含画像字段", ts["gp"].get("status") == "success" and "background" in ts["gp"] and "misconceptions" in ts["gp"], str(ts["gp"])[:150])
    check("list_banks / list_mindmaps / list_annotations：返回结构合法", ts["lb"].get("status") in ("success", "empty") and ts["lmm"].get("status") in ("success", "empty") and ts["la"].get("status") in ("success", "empty"), str(ts["lb"])[:100])
    check("list_backups / get_sync_status：success", ts["lbk1"].get("status") == "success" and ts["gs"].get("status") == "success", str(ts["gs"])[:150])
    check("未注册工具 → error", "error" in ts["unknown"], str(ts["unknown"])[:80])
    s, body = call(base, f"/api/conversations/{conv_a}/tool-confirm", "POST", {"approve": True})
    check("tool-confirm 无等待请求 → 409", s == 409, str(body)[:100])
    check(
        "update_learner_profile：写入生效并可回读",
        ts["p1"].get("status") == "success" and ts["gp2"].get("socratic_enabled") is False and ts["p2"].get("status") == "success",
        json.dumps(ts["gp2"], ensure_ascii=False)[:120],
    )
    check(
        "create_backup → list → delete_resource(backup) 全链路",
        ts["bk"].get("status") == "success"
        and any(b.get("name") == ts["bk"].get("backup") for b in ts["lbk2"].get("backups", []))
        and ts["dr"].get("status") == "success"
        and not any(b.get("name") == ts["bk"].get("backup") for b in ts["lbk3"].get("backups", [])),
        json.dumps(ts["bk"], ensure_ascii=False)[:120],
    )

    # 6.701 补缺工具链路（v0.5.6 增补）：改批注 / 重写大纲 / 导图连线增删与落库校验
    async def _test_tool_additions():
        from app.core.db import async_session_factory as _dbf61
        from app.schemas.mindmap import MindMapCreate
        from app.services.agent_tools.registry import execute_tool
        from app.services.mindmap import create_mindmap as _mm_create

        async with _dbf61() as s61:
            la2 = await execute_tool("list_annotations", {"document_id": document_id}, db=s61)
            ann_id = (la2.get("annotations") or [{}])[0].get("id", "")
            ua = (
                await execute_tool(
                    "update_annotation", {"annotation_id": ann_id, "note": "（冒烟）助教补注", "color": "blue"}, db=s61
                )
                if ann_id
                else {"status": "skipped"}
            )
            uo1 = await execute_tool(
                "update_course_outline",
                {"course_id": course_id, "chapters": [{"title": "第一章 指针入门"}, {"title": "第二章 待生成章"}]},
                db=s61,
            )
            uo2 = await execute_tool(
                "update_course_outline",
                {
                    "course_id": course_id,
                    "chapters": [{"title": "第一章 指针入门", "points": ["指针概念"]}, {"title": "第二章 待生成章"}],
                },
                db=s61,
            )
            mm = await _mm_create(s61, MindMapCreate(title="（冒烟）工具链路导图"))
            gm = await execute_tool("get_mindmap", {"map_id": mm.id}, db=s61)
            root_id = gm["mindmap"]["root"]["id"]
            kids = await execute_tool(
                "edit_mindmap",
                {
                    "map_id": mm.id,
                    "operations": [
                        {"action": "add_child", "node_id": root_id, "title": "节点A"},
                        {"action": "add_child", "node_id": root_id, "title": "节点B"},
                    ],
                },
                db=s61,
            )
            gm2 = await execute_tool("get_mindmap", {"map_id": mm.id}, db=s61)
            child_ids = [c["id"] for c in gm2["mindmap"]["root"].get("children", [])]
            if len(child_ids) >= 2:
                link = await execute_tool(
                    "edit_mindmap",
                    {"map_id": mm.id, "operations": [{"action": "link", "node_id": child_ids[0], "target_id": child_ids[1], "label": "易混淆"}]},
                    db=s61,
                )
                link_again = await execute_tool(
                    "edit_mindmap",
                    {"map_id": mm.id, "operations": [{"action": "link", "node_id": child_ids[0], "target_id": child_ids[1], "label": "重复"}]},
                    db=s61,
                )
                from app.models import MindMap as _MM

                mm_row = await s61.get(_MM, mm.id)
                saved = json.loads(mm_row.settings or "{}") if isinstance(mm_row.settings, str) else (mm_row.settings or {})
                links_saved = saved.get("cross_links") or []
                unlink = await execute_tool(
                    "edit_mindmap",
                    {"map_id": mm.id, "operations": [{"action": "unlink", "node_id": child_ids[0], "target_id": child_ids[1]}]},
                    db=s61,
                )
            else:
                link = link_again = unlink = {"status": "skipped"}
                links_saved = []
            dr_mm = await execute_tool("delete_resource", {"kind": "mindmap", "id": mm.id}, db=s61)
            return {"ua": ua, "uo1": uo1, "uo2": uo2, "kids": kids, "link": link, "link_again": link_again, "links_saved": links_saved, "unlink": unlink, "dr_mm": dr_mm}

    ta = asyncio.run(_test_tool_additions())
    check(
        "update_annotation：改颜色与备注生效",
        ta["ua"].get("status") in ("success", "skipped") and (ta["ua"].get("status") != "success" or ta["ua"]["annotation"]["color"] == "blue" and "助教补注" in ta["ua"]["annotation"]["note"]),
        str(ta["ua"])[:140],
    )
    check("update_course_outline：重写并还原均成功", ta["uo1"].get("status") == "success" and ta["uo2"].get("status") == "success", str(ta["uo1"])[:120])
    check(
        "edit_mindmap：连线落库、重复连线去重、按对解链",
        ta["kids"].get("status") == "success"
        and ta["link"].get("status") == "success"
        and len(ta["links_saved"]) == 1
        and ta["links_saved"][0].get("label") == "易混淆"
        and ta["link_again"].get("applied", 0) == 0
        and ta["unlink"].get("status") == "success"
        and ta["dr_mm"].get("status") == "success",
        json.dumps({"link": ta["link"], "links": ta["links_saved"], "again": ta["link_again"], "unlink": ta["unlink"]}, ensure_ascii=False)[:200],
    )

    # 6.7 搜索 / 学习时长 / 仪表盘扩展 / 导出 / 备份
    s, body = call(base, "/api/search", )
    check("空搜索词 → 400", s == 400, str(body)[:80])
    s, body = call(base, "/api/search?q=" + urllib.parse.quote("指针"))
    check("全局搜索命中教材原文", s == 200 and len(body["results"]) >= 1 and "指针" in body["results"][0]["snippet"], str(body)[:150])
    s, body = call(base, "/api/study/ping", "POST", {"seconds": 30})
    check("学习时长打点", s == 200 and body["ok"] is True)
    s, body = call(base, "/api/study/ping", "POST", {"seconds": 999})
    check("打点超限 → 400", s == 400)
    s, body = call(base, "/api/dashboard/summary")
    check(
        "仪表盘扩展（掌握度/时长）",
        s == 200 and all("mastery" in w for w in body["weak_points"]) and "study_days" in body and "study_minutes_7d" in body and "retention" not in body,
        str(body)[:150],
    )
    s, raw, headers = call_raw(base, f"/api/courses/{course_id}/export.md")
    check("课程导出 MD", s == 200 and "指针" in raw.decode("utf-8", "replace") and "attachment" in headers.get("content-disposition", ""), s and len(raw))
    s, raw, headers = call_raw(base, f"/api/courses/{course_id}/export.html")
    check("课程导出 HTML", s == 200 and b"katex" in raw and b"markdown-body" in raw, len(raw))

    # 7. 导入自有 Markdown（PRD 实现备注 12）：analyze → confirm → 原文保留
    s, body = call_multipart(base, "/api/courses/import/analyze", {}, [("files", "notes.md", IMPORT_MD.encode("utf-8"))])
    check("导入 analyze 识别 3 章", s == 200 and len(body.get("chapters", [])) == 3, json.dumps(body, ensure_ascii=False)[:200])
    if s == 200:
        titles = [c["title"] for c in body["chapters"]]
        check("切章标题正确", titles == ["C++ 指针自学笔记", "第一章 指针基础", "第二章 动态内存"], str(titles))
        spec = {
            "title": "我的 C++ 笔记课",
            "chapters": [
                {"file_index": c["file_index"], "title": c["title"], "start_line": c["start_line"], "end_line": c["end_line"]}
                for c in body["chapters"]
            ],
        }
        s, body = call_multipart(
            base,
            "/api/courses/import",
            {"spec": json.dumps(spec, ensure_ascii=False)},
            [("files", "notes.md", IMPORT_MD.encode("utf-8"))],
        )
        check("导入 confirm 建课成功", s == 200 and body.get("status") == "ready", json.dumps(body, ensure_ascii=False)[:200])
        imported_course = body.get("id")
        imported_docs = call(base, f"/api/courses/{imported_course}")[1]["documents"]
        check("导入生成 3 个文档且 source=imported", len(imported_docs) == 3 and all(d["source"] == "imported" for d in imported_docs))
        first_doc = imported_docs[0]
        s, body = call(base, f"/api/documents/{first_doc['document_id']}/content")
        check("导入文档原文保留", s == 200 and "这是我自己整理的笔记" in body["markdown"])
        s, body = call(base, f"/api/documents/{first_doc['document_id']}/regenerate", "POST", {})
        check("导入文档禁用重新生成(400)", s == 400 and "原文" in str(body.get("detail", "")), str(body)[:150])
        s, body = call(base, f"/api/courses/{imported_course}", "DELETE")
        check("清理导入课程", s == 200)

    # 8. 场景化 LLM（PRD §5.7）：保存场景覆盖 → 适配层回落验证 → （结束时统一还原）
    test_llm = {"base_url": "https://api.example.com/v1", "api_key": "sk-smoketest-123456", "model": "main-model"}
    s, body = call(base, "/api/settings", "PUT", {
        "llm": test_llm,
        "scenes": {"generation": {}, "chat": {"model": "fast-model"}},
        "preferences": {"auto_highlight": False},
    })
    check("保存场景化与偏好配置", s == 200 and body["scenes"]["chat"]["model"] == "fast-model" and body["preferences"]["auto_highlight"] is False, str(body)[:150])
    s, body = call(base, "/api/settings", "PUT", {"preferences": {"auto_highlight": True}})
    check("设置中重新开启自动划重点", s == 200 and body["preferences"]["auto_highlight"] is True)
    import asyncio as _aio

    from app.core.db import async_session_factory
    from app.services.llm import create_adapter_from_settings

    async def _scene_check():
        async with async_session_factory() as sdb:
            a_primary = await create_adapter_from_settings(sdb)
            a_chat = await create_adapter_from_settings(sdb, "chat")
            a_gen = await create_adapter_from_settings(sdb, "generation")
            return a_primary.model, a_chat.model, a_gen.model

    m_primary, m_chat, m_gen = _aio.run(_scene_check())
    check("场景回落：主/生成=主模型，答疑=覆盖模型", m_primary == "main-model" and m_gen == "main-model" and m_chat == "fast-model", f"{m_primary}/{m_gen}/{m_chat}")

    # 8.5 练习的 LLM 依赖路径：模型置空后必须快速 400（不允许 5xx / 挂起）
    call(base, "/api/settings", "PUT", {"llm": {"base_url": "", "model": ""}, "scenes": {"generation": {}, "chat": {}}})
    s, body = call(base, "/api/exercises/generate", "POST", {"knowledge_point_id": kp_id, "language": "python", "count": 2})
    check("出题(LLM未配置) → 400", s == 400, str(body)[:150])
    s, body = call(base, "/api/exercises/generate", "POST", {"knowledge_point_id": kp_id, "language": "ruby"})
    check("出题语言校验 → 400", s in (400, 422), str(body)[:120])
    s, body = call(base, "/api/quizzes/generate", "POST", {"document_id": document_id, "kp_ids": [kp_id]})
    check("组卷(LLM未配置) → 400", s == 400, str(body)[:120])
    s, body = call(base, f"/api/courses/{course_id}/ask", "POST", {"question": "指针是什么"})
    check("全课问答(LLM未配置) → 400", s == 400, str(body)[:120])
    s, body = call(base, "/api/assistant/session", "POST", {"context_type": "global", "context_id": ""})
    g_conv = body.get("conversation_id", "")
    s, body = call(base, f"/api/conversations/{g_conv}/messages/stream", "POST", {"content": "你好"})
    check("助教答疑(LLM未配置) → 400", s == 400, str(body)[:120])

    # 9. 高数图形化（PRD §5.9）：SymPy + Matplotlib 渲染
    s, body = call(base, "/api/math/render", "POST", {"expressions": "sin(x)/x\ntan(x)", "x_min": -6.5, "x_max": 6.5})
    check("函数绘图 → SVG", s == 200 and "<svg" in body.get("svg", "") and len(body.get("svg", "")) > 2000)
    s, body = call(base, "/api/math/render", "POST", {"expressions": "这不是数学"})
    check(
        "非法表达式 → 400 中文提示",
        s == 400 and ("无法解析" in str(body.get("detail", "")) or "未知符号" in str(body.get("detail", ""))),
        str(body)[:150],
    )

    # 9.5 轻量 PDF 导入（v0.4.69）：文本层直取零 LLM / 扫描版未配 LLM 友好 400
    def _make_smoke_pdf(with_text: bool) -> bytes:
        """手工拼装带 xref 的最小合法 PDF（不引第三方构造依赖）。"""
        if with_text:
            lines = [f"LearnFlow PDF smoke line {i}: pointer and memory basics" for i in range(12)]
            stream = "BT /F1 12 Tf 40 750 Td 14 TL\n" + "".join(f"({l}) Tj T*\n" for l in lines) + "ET"
        else:
            stream = ""
        objs = [
            b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(stream)}>>stream\n{stream}\nendstream".encode("utf-8"),
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, body_bytes in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj".encode() + body_bytes + b"endobj\n"
        xref_pos = len(out)
        out += f"xref\n0 {len(objs) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (
            f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF".encode()
        )
        return bytes(out)

    s, body = call_multipart(base, "/api/courses/import/pdf-transcribe", {}, [("files", "smoke.pdf", _make_smoke_pdf(True))])
    check(
        "PDF 文本层直取（零 LLM）",
        s == 200 and "LearnFlow PDF smoke line" in body.get("content", ""),
        str(body)[:150],
    )
    s, body = call_multipart(base, "/api/courses/import/pdf-transcribe", {}, [("files", "not_pdf.txt", b"hello")])
    check("PDF 导入非 PDF 文件 → 400", s == 400, str(body)[:120])
    s, body = call_multipart(base, "/api/courses/import/pdf-transcribe", {}, [("files", "scan.pdf", _make_smoke_pdf(False))])
    check(
        "扫描版 PDF 未配 LLM → 400 友好提示",
        s == 400 and "LLM" in str(body.get("detail", "")),
        str(body)[:150],
    )

    # 10. 更新检查（PRD 实现备注 15）
    s, body = call(base, "/api/version")
    check("版本接口", s == 200 and body.get("version", "").count(".") == 2, str(body)[:100])
    from app.services.update import has_newer_version

    assert has_newer_version("v9.9.9", "0.1.0") and not has_newer_version("0.1.0", "0.1.0")
    # 无网络/未配置仓库时必须优雅降级（不允许 5xx 或挂起）
    s, body = call(base, "/api/update/check?force=1", "POST")
    check(
        "更新检查优雅降级",
        s == 200 and ("has_update" in body) and ("error" in body or "latest" in body),
        str(body)[:150],
    )

    # 11. 仪表盘
    s, body = call(base, "/api/dashboard/summary")
    check("仪表盘包含测试课程", s == 200 and any(c["id"] == course_id for c in body["courses"]))

    # 12. 题库刷题（独立模块）：analyze → import → round 不泄答案 → 判分 → 错题池 → 删除级联
    def make_bank_xlsx() -> bytes:
        from io import BytesIO

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["题型", "题干", "A", "B", "C", "D", "E", "F", "G", "H", "正确答案", "", "解析", "难易程度"])
        rows = [
            ["单选题", "单选1", "a1", "a2", "a3", "a4", "", "", "", "", "B", "", "解析1", "一般"],
            ["单选题", "单选2", "b1", "b2", "b3", "b4", "", "", "", "", "A", "", "解析2", "较易"],
            ["单选题", "单选3", "c1", "c2", "c3", "c4", "", "", "", "", "C", "", "", "较难"],
            ["单选题", "单选4", "d1", "d2", "d3", "d4", "", "", "", "", "D", "", "解析4", "难"],
            ["单选题", "单选5", "e1", "e2", "e3", "e4", "", "", "", "", "A", "", "解析5", "易"],
            ["多选题", "多选1", "m1", "m2", "m3", "m4", "", "", "", "", "A,C", "", "解析m1", "一般"],
            ["多选题", "多选2", "n1", "n2", "n3", "n4", "", "", "", "", "B,C,D", "", "解析m2", "一般"],
            ["多选题", "多选3", "o1", "o2", "o3", "o4", "", "", "", "", "A,B,C,D", "", "", "一般"],
            ["判断题", "判断1", "", "", "", "", "", "", "", "", "正确", "", "解析j1", "一般"],
            ["判断题", "判断2", "", "", "", "", "", "", "", "", "错误", "", "解析j2", "较易"],
            ["判断题", "判断3", "", "", "", "", "", "", "", "", "对", "", "解析j3", "一般"],
            ["单选题", "", "坏行：缺题干", "", "", "", "", "", "", "", "A", "", "", "一般"],
            ["填空题", "未知题型行", "", "", "", "", "", "", "", "", "A", "", "", ""],
        ]
        for r in rows:
            ws.append(r)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    bank_bytes = make_bank_xlsx()
    s, body = call_multipart(base, "/api/banks/import/analyze", {}, [("file", "test_bank.xlsx", bank_bytes)])
    check(
        "题库 analyze：11 题 + 2 坏行",
        s == 200 and body["question_count"] == 11 and body["skipped_total"] == 2,
        json.dumps(body, ensure_ascii=False)[:200],
    )
    if s == 200:
        check("analyze 样题不含答案", all("answer" not in q and "explanation" not in q for q in body["samples"]))
    s, body = call_multipart(base, "/api/banks/import/analyze", {}, [("file", "notes.md", b"# not a bank")])
    check("题库 analyze 非 xls/xlsx → 400", s == 400, str(body)[:120])

    s, body = call_multipart(base, "/api/banks/import", {}, [("file", "test_bank.xlsx", bank_bytes)])
    check("题库 import 成功", s == 200 and body["question_count"] == 11 and body["stats"]["answered"] == 0 and body["stats"]["new_count"] == 11, json.dumps(body, ensure_ascii=False)[:200])
    bank_id = body.get("id", "")

    s, body = call(base, f"/api/banks/{bank_id}", "PATCH", {"name": "网安题库（改名）"})
    check("题库改名", s == 200 and body.get("name") == "网安题库（改名）", str(body)[:120])
    s, body = call(base, "/api/banks")
    check("题库改名生效", s == 200 and any(b["name"] == "网安题库（改名）" for b in body), str(body)[:150])
    s, body = call(base, f"/api/banks/{bank_id}", "PATCH", {"name": "  "})
    check("题库改名为空 → 4xx", s in (400, 422), str(body)[:120])

    # 6.71 全量工具扩权·题库与练习写工具（v0.5.6）：抽轮脱敏/纠错改题/提示词/重命名/硬骨头
    async def _test_bank_tools():
        from app.core.db import async_session_factory as _dbf7
        from app.services.agent_tools.registry import execute_tool

        async with _dbf7() as s7:
            rd5 = await execute_tool("draw_bank_round", {"bank_id": bank_id, "mode": "all", "size": 5}, db=s7)
            qid = (rd5.get("questions") or [{}])[0].get("question_id", "")
            cb = await execute_tool(
                "correct_bank_question", {"question_id": qid, "explanation": "（冒烟）助教核对后的解析"}, db=s7
            )
            sb1 = await execute_tool("set_bank_prompt", {"bank_id": bank_id, "prompt": "（冒烟）自定义答疑风格"}, db=s7)
            sb2 = await execute_tool("set_bank_prompt", {"bank_id": bank_id, "prompt": ""}, db=s7)
            ur1 = await execute_tool("update_resource_title", {"kind": "bank", "id": bank_id, "title": "（冒烟）改名中"}, db=s7)
            ur2 = await execute_tool("update_resource_title", {"kind": "bank", "id": bank_id, "title": "网安题库（改名）"}, db=s7)
            le2 = await execute_tool("list_exercises", {"document_id": document_id}, db=s7)
            ex_id = (le2.get("exercises") or [{}])[0].get("id", "")
            if ex_id:
                hb1 = await execute_tool("toggle_hard_bone", {"exercise_id": ex_id}, db=s7)
                hb2 = await execute_tool("toggle_hard_bone", {"exercise_id": ex_id, "on": hb1.get("hard_bone")}, db=s7)
            else:
                hb1 = hb2 = {"status": "skipped"}
            return {"rd5": rd5, "cb": cb, "sb1": sb1, "sb2": sb2, "ur1": ur1, "ur2": ur2, "hb1": hb1, "hb2": hb2}

    bt = asyncio.run(_test_bank_tools())
    check(
        "draw_bank_round：抽 5 题不泄答案并带跳转标签",
        bt["rd5"].get("status") == "success"
        and len(bt["rd5"].get("questions") or []) == 5
        and all("answer" not in q and "explanation" not in q for q in bt["rd5"]["questions"])
        and bool(bt["rd5"].get("references")),
        json.dumps(bt["rd5"], ensure_ascii=False)[:150],
    )
    check(
        "correct_bank_question：纠错改解析成功且告知重判",
        bt["cb"].get("status") == "success" and "重判" in str(bt["cb"].get("note", "")),
        str(bt["cb"])[:150],
    )
    check(
        "set_bank_prompt：设置与清空恢复默认",
        bt["sb1"].get("status") == "success" and bt["sb2"].get("status") == "success" and "默认" in str(bt["sb2"].get("note", "")),
        str(bt["sb2"])[:120],
    )
    check(
        "update_resource_title(bank)：改名并还原",
        bt["ur1"].get("status") == "success" and bt["ur2"].get("status") == "success",
        str(bt["ur2"])[:120],
    )
    check(
        "toggle_hard_bone：翻转并按 on 复位",
        bt["hb1"].get("status") in ("success", "skipped") and bt["hb2"].get("status") in ("success", "skipped"),
        str(bt["hb2"])[:120],
    )

    # 1. 抽「做题模式 / all」10 题，验证同一套题内绝无重复题目（ID与题干均唯一）
    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "all", "size": 10})
    check("做题模式抽 10 题", s == 200 and len(body["questions"]) == 10, str(body)[:150])
    if s == 200:
        q_ids = [q["id"] for q in body["questions"]]
        q_titles = [q["title"] for q in body["questions"]]
        check("做题模式同一套题内无重复题", len(q_ids) == len(set(q_ids)) and len(q_titles) == len(set(q_titles)))
        check("抽轮题目不泄答案", all("answer" not in q and "explanation" not in q and "answer_raw" not in q for q in body["questions"]))

    # 2. 抽「做新题模式 / new」10 题，初始状态 11 道均为新题，验证无重复
    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "new", "size": 10})
    check("做新题模式抽 10 题", s == 200 and len(body["questions"]) == 10, str(body)[:150])
    if s == 200:
        new_q_ids = [q["id"] for q in body["questions"]]
        check("做新题模式同一套题内无重复题", len(new_q_ids) == len(set(new_q_ids)))

    # 判分断言用全量轮（11 题），避免随机抽 10/11 漏掉特定题导致 flaky
    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "all", "size": 11})
    if s == 200:
        qs = {q["seq"]: q for q in body["questions"]}
        single_q = qs[1]  # 单选1 → B
        multi_q = qs[6]   # 多选1 → A,C
        judge_q = qs[9]   # 判断1 → 正确(A)
    s, body = call(base, "/api/banks/attempts", "POST", {"question_id": single_q["id"], "content": ["B"]})
    check("单选答对 → passed + 解析", s == 200 and body["passed"] is True and body["explanation"] == "解析1", str(body)[:150])
    s, body = call(base, "/api/banks/attempts", "POST", {"question_id": multi_q["id"], "content": ["A"]})
    check("多选少选 → 未通过", s == 200 and body["passed"] is False and body["correct_answer"] == "A、C", str(body)[:150])
    s, body = call(base, "/api/banks/attempts", "POST", {"question_id": judge_q["id"], "content": ["A"]})
    check("判断答对 → passed", s == 200 and body["passed"] is True and body["correct_answer"] == "正确", str(body)[:150])

    # 3. 作答 3 题后，做新题模式池容量应减少为 8 题，且抽新题绝不包含已作答过的题
    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "new", "size": 20})
    answered_3_ids = {single_q["id"], multi_q["id"], judge_q["id"]}
    check("做新题模式仅抽未做新题", s == 200 and len(body["questions"]) == 8 and all(q["id"] not in answered_3_ids for q in body["questions"]))

    s, body = call(base, f"/api/banks/{bank_id}/wrong")
    check("错题池只含答错的题", s == 200 and len(body) == 1 and body[0]["seq"] == 6, str(body)[:150])
    if s == 200:
        check("错题池含答案与解析", body[0]["answer"] == "A,C" and body[0]["explanation"] == "解析m1")
    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "wrong", "size": 20})
    check("错题重刷抽到错题", s == 200 and len(body["questions"]) == 1 and body["questions"][0]["seq"] == 6, str(body)[:150])
    s, body = call(base, "/api/banks/attempts", "POST", {"question_id": multi_q["id"], "content": ["C", "A"]})
    check("错题重刷答对(乱序多选) → 出池", s == 200 and body["passed"] is True, str(body)[:120])
    s, body = call(base, f"/api/banks/{bank_id}/wrong")
    check("答对后错题池为空", s == 200 and body == [])

    s, body = call(base, f"/api/banks/{bank_id}/stats")
    check(
        "统计：answered=3 / new_count=8 / attempts=4 / accuracy=75%",
        s == 200 and body["answered"] == 3 and body.get("new_count") == 8 and body["attempts"] == 4 and body["accuracy"] == 75.0,
        str(body)[:150],
    )

    s, body = call(base, f"/api/banks/{bank_id}", "DELETE")
    check("删除题库", s == 200)

    async def _bank_left():
        from sqlalchemy import func, select

        from app.models import BankAttempt, BankQuestion

        async with async_session_factory() as sdb:
            n_q = (
                await sdb.scalars(select(func.count()).select_from(BankQuestion).where(BankQuestion.bank_id == bank_id))
            ).one()
            n_a = (
                await sdb.scalars(select(func.count()).select_from(BankAttempt).where(BankAttempt.bank_id == bank_id))
            ).one()
            return n_q, n_a

    n_q, n_a = asyncio.run(_bank_left())
    check("题库删除后题目/作答级联清零", (n_q, n_a) == (0, 0), f"{n_q}/{n_a}")
    s, body = call(base, f"/api/banks/{bank_id}/stats")
    check("删除后 stats 404", s == 404)

    # 9. 级联删除课程（同时验证全部关联数据清理）
    s, body = call(base, f"/api/courses/{course_id}", "DELETE")
    check("删除课程", s == 200)
    s, body = call(base, f"/api/documents/{document_id}/content")
    check("删除后文档 404", s == 404)
    s, body = call(base, f"/api/documents/{document_id}/executions")
    check("删除后执行历史为空", s == 200 and body == [])

    async def _exercise_left():
        from sqlalchemy import func, select

        from app.models import Exercise, ExerciseAttempt

        async with async_session_factory() as sdb:
            n_ex = (
                await sdb.scalars(
                    select(func.count()).select_from(Exercise).where(Exercise.document_id == document_id)
                )
            ).one()
            n_at = (
                await sdb.scalars(
                    select(func.count())
                    .select_from(ExerciseAttempt)
                    .join(Exercise, ExerciseAttempt.exercise_id == Exercise.id)
                    .where(Exercise.document_id == document_id)
                )
            ).one()
            return n_ex, n_at

    n_ex, n_at = _aio.run(_exercise_left())
    check("课程删除后练习/作答级联清零", (n_ex, n_at) == (0, 0), f"{n_ex}/{n_at}")

    # 统一还原运行前状态（设置 / 局域网开关 / 访问令牌），须在服务器仍在运行时执行
    _restore_state(base, orig_settings)

    print("\n结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    server.should_exit = True
    time.sleep(0.5)


if __name__ == "__main__":
    main()
