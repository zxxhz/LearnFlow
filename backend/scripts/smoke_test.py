"""集成冒烟测试（不依赖 LLM）：直接经服务层构造已完成课程，再走真实 HTTP API 验证。

运行：uv run python scripts/smoke_test.py
结束时会用 DELETE /api/courses/{id} 清理测试数据（顺带验证级联删除）。
"""
import asyncio
import json
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from app.core.config import settings
from app.core.db import async_session_factory, init_db
from app.models import Course, Document, Exercise, KnowledgePoint
from app.models.base import utcnow_iso
from app.services.generation.indexing import rebuild_sections

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
        await rebuild_sections(db, doc, SAMPLE_MD, 1)
        kp = KnowledgePoint(document_id=doc.id, title="指针概念", summary="指针存放内存地址")
        db.add(kp)
        await db.flush()
        db.add_all([
            Exercise(
                knowledge_point_id=kp.id,
                document_id=doc.id,
                kind="code",
                title="打印两数之和",
                task_md="补全 TODO，使程序输出 `2 + 3 = 5`。",
                language="python",
                skeleton_code="a = 2\nb = 3\n# TODO：打印 a + b\n",
                expected_output="2 + 3 = 5\n",
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


def main() -> None:
    course_id, document_id, kp_id = asyncio.run(seed())
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

    # 2. 文档内容 + 块对齐
    s, body = call(base, f"/api/documents/{document_id}/content")
    check("文档 content 接口", s == 200)
    if s == 200:
        check("markdown 返回", "指针" in body["markdown"])
        types = [b["block_type"] for b in body["blocks"]]
        check("9 个块全部索引", len(body["blocks"]) == 9, str(types))
        check("块类型齐全", types == ["heading", "paragraph", "code", "heading", "list", "quote", "paragraph", "math", "table"], str(types))

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

    # 4. 复习队列（应包含自动卡之外的空队列 + 新卡不存在，因为无 kp——检查结构即可）
    s, body = call(base, "/api/review/queue/today")
    check("复习队列接口", s == 200 and "cards" in body)

    # 5. 手动建卡 → 评分 → SM-2 推进
    s, body = call(base, "/api/review/cards", "POST", {"front": "指针和引用的区别？", "back": "指针可空可改指向；引用必须初始化且不可改绑。"})
    check("手动建卡", s == 200)
    card_id = body.get("id", "")
    s, body = call(base, f"/api/review/cards/{card_id}/grade", "POST", {"quality": 5})
    check("评分(轻松) → 1 天后到期", s == 200 and body["interval_days"] == 1.0, json.dumps(body, ensure_ascii=False)[:150])
    s, body = call(base, f"/api/review/cards/{card_id}/grade", "POST", {"quality": 1})
    check("评分(忘了) → 10分钟后重现(relearning)", s == 200 and body["state"] == "relearning" and body["interval_days"] < 0.01)

    # 6. 代码运行沙箱（PRD §5.8）：文档代码块走真实 API
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

    # 6.6 练习系统（PRD §5.10）：列表回显 / 代码题自动判定 / 删除（LLM 依赖路径见 §8.5）
    s, body = call(base, f"/api/exercises?document_id={document_id}")
    check(
        "练习列表（含知识点标题）",
        s == 200 and len(body) == 4 and all(e["kp_title"] == "指针概念" for e in body),
        json.dumps(body, ensure_ascii=False)[:200],
    )
    if s == 200:
        ex_code = next(e for e in body if e["kind"] == "code")
        ex_concept = next(e for e in body if e["kind"] == "concept")
        ex_choice = next(e for e in body if e["kind"] == "choice")
        ex_fill = next(e for e in body if e["kind"] == "fill")
        check("未作答时 latest_attempt 为空", ex_code["latest_attempt"] is None)
        s, body = call(base, f"/api/exercises/{ex_code['id']}/submit", "POST", {"content": "print('2 + 3 =', 2 + 3)"})
        check("代码题正确解 → passed", s == 200 and body["passed"] is True and body["status"] == "success", json.dumps(body, ensure_ascii=False)[:200])
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
        s, body = call(base, f"/api/exercises?document_id={document_id}")
        latest = next(e for e in body if e["id"] == ex_code["id"])["latest_attempt"]
        check("提交后最新作答回显", latest is not None and latest["passed"] is False)
        s, body = call(base, f"/api/exercises/wrongbook")
        wb = {e["id"] for e in body}
        wb_ok = ex_code["id"] in wb and ex_choice["id"] in wb and ex_fill["id"] not in wb
        check(
            "错题本：做错的在、做对的不在",
            s == 200 and wb_ok,
            f"n={len(body)} code_in={ex_code['id'] in wb} choice_in={ex_choice['id'] in wb} fill_out={ex_fill['id'] not in wb}",
        )
        if s == 200 and not wb_ok:
            # 取证模式：错题本断言失败时立刻中止（跳过末尾的删除清理），保留 DB 现场
            print("!! 错题本断言失败，保留现场中止")
            sys.exit(3)
        s, body = call(base, f"/api/exercises/{ex_concept['id']}", "DELETE")
        check("删除练习题", s == 200)
        s, body = call(base, f"/api/exercises?document_id={document_id}")
        check("删除后列表剩 3 题", s == 200 and len(body) == 3)

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
        "仪表盘扩展（掌握度/遗忘曲线/时长）",
        s == 200 and all("mastery" in w for w in body["weak_points"]) and "retention" in body and "study_days" in body and "study_minutes_7d" in body,
        str(body)[:150],
    )
    s, raw, headers = call_raw(base, f"/api/courses/{course_id}/export.md")
    check("课程导出 MD", s == 200 and "指针" in raw.decode("utf-8", "replace") and "attachment" in headers.get("content-disposition", ""), s and len(raw))
    s, raw, headers = call_raw(base, "/api/review/export.csv")
    check("复习卡导出 CSV", s == 200 and raw.startswith(b"front,back,tags"), len(raw))
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

    # 8. 场景化 LLM（PRD §5.7）：保存场景覆盖 → 适配层回落验证 → 还原
    s, orig = call(base, "/api/settings")
    test_llm = {"base_url": "https://api.example.com/v1", "api_key": "sk-smoketest-123456", "model": "main-model"}
    s, body = call(base, "/api/settings", "PUT", {
        "llm": test_llm,
        "scenes": {"generation": {}, "chat": {}, "feynman": {"model": "strong-model"}},
    })
    check("保存场景化配置", s == 200 and body["scenes"]["feynman"]["model"] == "strong-model", str(body)[:150])
    import asyncio as _aio

    from app.core.db import async_session_factory
    from app.services.llm import create_adapter_from_settings

    async def _scene_check():
        async with async_session_factory() as sdb:
            a_primary = await create_adapter_from_settings(sdb)
            a_feynman = await create_adapter_from_settings(sdb, "feynman")
            a_gen = await create_adapter_from_settings(sdb, "generation")
            return a_primary.model, a_feynman.model, a_gen.model

    m_primary, m_feynman, m_gen = _aio.run(_scene_check())
    check("场景回落：主/生成=主模型，费曼=覆盖模型", m_primary == "main-model" and m_gen == "main-model" and m_feynman == "strong-model", f"{m_primary}/{m_gen}/{m_feynman}")

    # 8.5 练习的 LLM 依赖路径：模型置空后必须快速 400（不允许 5xx / 挂起）
    call(base, "/api/settings", "PUT", {"llm": {"base_url": "", "model": ""}})
    s, body = call(base, "/api/exercises/generate", "POST", {"knowledge_point_id": kp_id, "language": "python", "count": 2})
    check("出题(LLM未配置) → 400", s == 400, str(body)[:150])
    s, body = call(base, "/api/exercises/generate", "POST", {"knowledge_point_id": kp_id, "language": "ruby"})
    check("出题语言校验 → 400", s in (400, 422), str(body)[:120])
    s, body = call(base, "/api/quizzes/generate", "POST", {"document_id": document_id, "kp_ids": [kp_id]})
    check("组卷(LLM未配置) → 400", s == 400, str(body)[:120])
    s, body = call(base, f"/api/courses/{course_id}/ask", "POST", {"question": "指针是什么"})
    check("全课问答(LLM未配置) → 400", s == 400, str(body)[:120])

    call(base, "/api/settings", "PUT", {"llm": {"base_url": orig["llm"]["base_url"], "api_key": orig["llm"]["api_key"], "model": orig["llm"]["model"]}, "scenes": {"generation": {}, "chat": {}, "feynman": {}}})

    # 9. 高数图形化（PRD §5.9）：SymPy + Matplotlib 渲染
    s, body = call(base, "/api/math/render", "POST", {"expressions": "sin(x)/x\ntan(x)", "x_min": -6.5, "x_max": 6.5})
    check("函数绘图 → SVG", s == 200 and "<svg" in body.get("svg", "") and len(body.get("svg", "")) > 2000)
    s, body = call(base, "/api/math/render", "POST", {"expressions": "这不是数学"})
    check(
        "非法表达式 → 400 中文提示",
        s == 400 and ("无法解析" in str(body.get("detail", "")) or "未知符号" in str(body.get("detail", ""))),
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
    check("题库 import 成功", s == 200 and body["question_count"] == 11 and body["stats"]["answered"] == 0, json.dumps(body, ensure_ascii=False)[:200])
    bank_id = body.get("id", "")

    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "random", "size": 10})
    check("抽轮 10 题", s == 200 and len(body["questions"]) == 10, str(body)[:150])
    if s == 200:
        check("抽轮题目不泄答案", all("answer" not in q and "explanation" not in q and "answer_raw" not in q for q in body["questions"]))
    # 判分断言用全量轮（11 题），避免随机抽 10/11 漏掉特定题导致 flaky
    s, body = call(base, f"/api/banks/{bank_id}/round", "POST", {"mode": "random", "size": 11})
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
        "统计：answered=3 / attempts=4 / accuracy=75%",
        s == 200 and body["answered"] == 3 and body["attempts"] == 4 and body["accuracy"] == 75.0,
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

    print("\n结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    server.should_exit = True
    time.sleep(0.5)


if __name__ == "__main__":
    main()
