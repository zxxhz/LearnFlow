"""首跑示例课程：无 LLM 配置时也能体验阅读器 / 沙箱 / 练习 / 复习（PRD §5.1 的冷启动兜底）。

仅在「从未有过任何课程」且未播种过（flag 文件）时注入；用户删除后不再重生。
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Course,
    Document,
    Exercise,
    KnowledgePoint,
)
from app.models.exercise import EXERCISE_CHOICE, EXERCISE_CODE, EXERCISE_FILL
from app.services.generation.indexing import rebuild_sections

logger = logging.getLogger(__name__)

SAMPLE_MD = """# 第 1 章 指针与内存

指针是 C++ 的核心概念：它是一个**值为内存地址**的变量。理解指针需要先理解内存布局。

## 1.1 地址与解引用

每个变量都住在内存的某个地址上。`&x` 取地址，`*p` 解引用（访问地址指向的值）。

```cpp
#include <iostream>
int main() {
    int x = 42;
    int* p = &x;        // p 存的是 x 的地址
    std::cout << *p << std::endl;  // 解引用：输出 42
    return 0;
}
```

对空指针解引用是**未定义行为**，程序可能崩溃——这是新手最常见的段错误来源。

## 1.2 Python 里的"引用"对照

Python 变量本质是对象的引用，没有指针运算，但有同样的"名字 → 对象"映射思想：

```python
a = [1, 2, 3]
b = a          # b 与 a 指向同一个列表
b.append(4)
print(len(a))  # 输出 4：改 b 就是改 a
```

## 1.3 图像：平方函数

```plot
y = x^2, sin(x)/x
```
"""

SAMPLE_EXERCISES = [
    {
        "kind": EXERCISE_CODE,
        "title": "第 1 关：解引用入门",
        "task_md": "写一个 Python 程序：从字典 `{'value': 7}` 里取出 `'value'` 的值并打印出来，让输出为 `7`。",
        "language": "python",
        "hints": json.dumps(
            ["字典取值用方括号或 .get()", "print(7) 就能输出 7，关键是先取到它"], ensure_ascii=False
        ),
        "reference_code": "d = {'value': 7}\nprint(d['value'])",
        "expected_output": "7",
    },
    {
        "kind": EXERCISE_CHOICE,
        "title": "空指针解引用",
        "task_md": "对空指针（nullptr）解引用会发生什么？",
        "options": ["返回 0", "未定义行为，通常崩溃", "抛出可捕获的异常", "自动分配内存"],
        "answer": "B",
    },
    {
        "kind": EXERCISE_FILL,
        "title": "取地址运算符",
        "task_md": "C++ 中对变量 x 取地址的表达式是 ______。",
        "answer": ["&x", "& x"],
    },
]

SAMPLE_KPS = [
    {
        "title": "地址与解引用",
        "summary": "指针变量存地址；& 取地址、* 解引用；空指针解引用是未定义行为。",
    },
    {
        "title": "Python 引用语义",
        "summary": "Python 变量是对象的引用；赋值不复制对象，别名共享同一对象。",
    },
]


async def seed_sample_course(db: AsyncSession) -> None:
    flag = settings.data_dir / ".sample-seeded"
    any_course = (await db.scalars(select(Course.id).limit(1))).first()
    if any_course is not None or flag.exists():
        return
    try:
        course = Course(
            title="C++ 指针入门（示例课程）",
            topic="C++ 指针",
            status="ready",
            outline=json.dumps(
                [{"index": 1, "title": "指针与内存", "points": ["地址与解引用", "引用语义"]}],
                ensure_ascii=False,
            ),
        )
        db.add(course)
        await db.flush()
        doc = Document(
            course_id=course.id, chapter_index=1, title="指针与内存", status="done", version=1
        )
        db.add(doc)
        await db.flush()

        # 正文落盘（导入/generated 同一布局：courses/{cid}/{did}/current.md）
        doc_dir = settings.courses_dir / course.id / doc.id
        doc_dir.mkdir(parents=True, exist_ok=True)
        doc.file_path = doc_dir.relative_to(settings.data_dir).as_posix() + "/current.md"
        (settings.data_dir / doc.file_path).write_text(SAMPLE_MD, encoding="utf-8")

        sections = await rebuild_sections(db, doc, SAMPLE_MD, 1)
        sec_ids = [s.id for s in sections]

        kp_ids: list[str] = []
        for i, kp in enumerate(SAMPLE_KPS):
            row = KnowledgePoint(
                document_id=doc.id,
                title=kp["title"],
                summary=kp["summary"],
                section_ids=json.dumps(sec_ids[i:: len(SAMPLE_KPS)]),
            )
            db.add(row)
            kp_ids.append("")  # 占位，flush 后回填
        await db.flush()
        kp_rows = (
            await db.scalars(select(KnowledgePoint).where(KnowledgePoint.document_id == doc.id))
        ).all()
        kp_ids = [r.id for r in kp_rows]

        # 练习按主题归属知识点（选择/填空 → 第 1 个；代码 → 第 2 个）
        by_kind = {EXERCISE_CHOICE: 0, EXERCISE_FILL: 0, EXERCISE_CODE: 1}
        for j, ex in enumerate(SAMPLE_EXERCISES):
            db.add(
                Exercise(
                    knowledge_point_id=kp_ids[by_kind.get(ex["kind"], 0) % len(kp_ids)],
                    document_id=doc.id,
                    kind=ex["kind"],
                    title=ex["title"],
                    task_md=ex["task_md"],
                    language=ex.get("language", ""),
                    skeleton_code=ex.get("skeleton_code", ""),
                    hints=ex.get("hints", "[]"),
                    reference_code=ex.get("reference_code", ""),
                    expected_output=ex.get("expected_output", ""),
                    options=json.dumps(ex.get("options", []), ensure_ascii=False),
                    answer=json.dumps(ex["answer"], ensure_ascii=False)
                    if ex["kind"] == EXERCISE_FILL
                    else ex.get("answer", ""),
                )
            )
        await db.commit()
        flag.write_text("ok", encoding="utf-8")
        logger.info("示例课程已注入（首跑）")
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.warning("示例课程注入失败（跳过，不影响使用）", exc_info=True)
