"""集成冒烟测试（不依赖 LLM）：直接经服务层构造已完成课程，再走真实 HTTP API 验证。

运行：uv run python scripts/smoke_test.py
结束时会用 DELETE /api/courses/{id} 清理测试数据（顺带验证级联删除）。
"""
import asyncio
import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from app.core.config import settings
from app.core.db import async_session_factory, init_db
from app.models import Course, Document
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
        await db.commit()
        return course.id, doc.id


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


def main() -> None:
    course_id, document_id = asyncio.run(seed())
    base = "http://127.0.0.1:8420"
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8420, log_level="warning")
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

    # 6. 仪表盘
    s, body = call(base, "/api/dashboard/summary")
    check("仪表盘包含测试课程", s == 200 and any(c["id"] == course_id for c in body["courses"]))

    # 7. 级联删除课程（同时验证全部关联数据清理）
    s, body = call(base, f"/api/courses/{course_id}", "DELETE")
    check("删除课程", s == 200)
    s, body = call(base, f"/api/documents/{document_id}/content")
    check("删除后文档 404", s == 404)

    print("\n结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    server.should_exit = True
    time.sleep(0.5)


if __name__ == "__main__":
    main()
