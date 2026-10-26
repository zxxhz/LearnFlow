"""内容出口：课程导出 Markdown / 静态 HTML（PRD 数据只进不出的另一半）。"""
import html as html_mod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Document
from app.services.sections_text import load_document_markdown


async def _done_documents(db: AsyncSession, course: Course) -> list[Document]:
    docs = (
        await db.scalars(
            select(Document)
            .where(Document.course_id == course.id, Document.status == "done")
            .order_by(Document.chapter_index)
        )
    ).all()
    return list(docs)


async def course_markdown(db: AsyncSession, course: Course) -> str:
    """整课合并为一个 Markdown 文档（含章节标题）。"""
    parts = [f"# {course.title}\n"]
    for d in await _done_documents(db, course):
        parts.append(f"\n\n---\n\n## 第 {d.chapter_index} 章 {d.title}\n\n")
        parts.append(load_document_markdown(d).strip())
    return "".join(parts) + "\n"


async def course_notes_markdown(db: AsyncSession, course: Course) -> str:
    """整课学习笔记与重点批注汇编导出：课程大纲 + 章节摘要 + 划线原文 + 个人手写随笔 + 助教问答。"""
    from app.models import Annotation, Conversation, Message

    docs = await _done_documents(db, course)
    parts = [
        f"# 《{course.title}》个人学习笔记与重点批注汇编\n\n",
        f"> 主题：{course.topic} | 涵盖章节：{len(docs)} 章\n\n",
        "## 目录大纲\n\n",
    ]
    for d in docs:
        parts.append(f"- 第 {d.chapter_index} 章：{d.title}\n")
    parts.append("\n---\n")

    for d in docs:
        parts.append(f"\n## 第 {d.chapter_index} 章 {d.title}\n")
        if d.summary:
            parts.append(f"> **本章要点摘要**：{d.summary.strip()}\n\n")

        anns = (
            await db.scalars(
                select(Annotation)
                .where(Annotation.document_id == d.id, Annotation.status == "active")
                .order_by(Annotation.created_at)
            )
        ).all()

        if not anns:
            parts.append("*(本章暂无划线与随笔批注)*\n\n")
            continue

        parts.append(f"### 🖍 本章划线与笔记（共 {len(anns)} 处）\n\n")
        for idx, ann in enumerate(anns, 1):
            parts.append(f"#### {idx}. 标注内容\n")
            parts.append(f"> {ann.exact}\n\n")
            parts.append(f"- **高亮颜色**：`{ann.color}`\n")
            if ann.note and ann.note.strip():
                parts.append(f"- **📝 我的随笔批注**：{ann.note.strip()}\n")

            # 关联问答
            conv = (
                await db.scalars(
                    select(Conversation).where(Conversation.annotation_id == ann.id)
                )
            ).first()
            if conv:
                msgs = (
                    await db.scalars(
                        select(Message)
                        .where(Message.conversation_id == conv.id)
                        .order_by(Message.created_at)
                    )
                ).all()
                if msgs:
                    parts.append("- **💬 助教问答研讨回顾**：\n")
                    for m in msgs:
                        role_name = "🙋 学生" if m.role == "user" else "🤖 助教"
                        content_indented = m.content.strip().replace("\n", "\n  ")
                        parts.append(f"  - **{role_name}**：{content_indented}\n")
            parts.append("\n")

    return "".join(parts)


_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/github-markdown-css@5/github-markdown-light.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}]});"></script>
<style>
  body { background:#f6f8fa; margin:0; padding:24px 0; }
  .markdown-body { max-width: 860px; margin: 0 auto; background:#fff; padding:48px 56px; border-radius:8px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
  hr.chapter { margin: 48px 0; border:none; border-top:2px dashed #d0d7de; }
  @media print { body { background:#fff; padding:0; } .markdown-body { box-shadow:none; padding:0; max-width:none; } }
</style>
</head>
<body>
<article class="markdown-body">
__BODY__
</article>
</body>
</html>
"""


async def course_html(db: AsyncSession, course: Course) -> str:
    """整课渲染为单文件静态 HTML：KaTeX 自动渲染公式（CDN），可直接浏览器打开/打印 PDF。"""
    from markdown_it import MarkdownIt

    md = MarkdownIt("commonmark", {"html": False, "typographer": True}).enable("table")
    parts = [f"<h1>{html_mod.escape(course.title)}</h1>"]
    for d in await _done_documents(db, course):
        parts.append(f"<hr class='chapter'><h2>第 {d.chapter_index} 章 · {html_mod.escape(d.title)}</h2>")
        parts.append(md.render(load_document_markdown(d)))
    body = "\n".join(parts)
    return _HTML_TMPL.replace("__TITLE__", html_mod.escape(course.title)).replace("__BODY__", body)
