"""助教 Prompt 教学质量离线评测（dev-only，吸收 DeepTutor TutorBench 学生模拟器协议）。

不进打包与冒烟。用 LLM 扮演带特定认知盲区的学生，与 exercise_tutor 助教多轮对聊，
再由评审 LLM 按 Rubric 打分：是否剧透答案 / 是否寒暄套话 / 启发性 1-5 分。
用于每次大改 tutor / annotation prompt 后的回归验证。

用法（在 backend/ 目录）：
  # 复用真实桌面数据目录里已配置的模型（只读其 app_settings.llm）：
  uv run python scripts/eval_tutor_prompts.py --data-dir "%APPDATA%\\com.learnflow.desktop"
  # 或显式指定模型：
  uv run python scripts/eval_tutor_prompts.py --base-url https://api.xx.com/v1 --api-key sk-xx --model glm-4-flash
  # 结果落盘：
  uv run python scripts/eval_tutor_prompts.py --data-dir ... --out eval_report.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 隔离数据目录必须在 import app.* 之前决定（与 smoke_test 同规则）
_ISOLATED_DIR = Path(tempfile.mkdtemp(prefix="learnflow-eval-"))
os.environ["APP_DATA_DIR"] = str(_ISOLATED_DIR)

from pydantic import BaseModel  # noqa: E402

from app.core.db import async_session_factory, init_db  # noqa: E402
from app.models import AppSetting, Course, Document, Exercise, ExerciseAttempt, KnowledgePoint  # noqa: E402
from app.models.base import utcnow_iso  # noqa: E402
from app.services.llm import create_adapter_from_settings  # noqa: E402
from app.services.tutor import stream_exercise_diagnosis  # noqa: E402

STUDENT_TURNS = 3

# 三个典型学生人设（含真实自学者的对抗性行为：直接要答案 / 概念混淆 / 一句批评就放弃）
PERSONAS = [
    {
        "name": "直接要答案型",
        "desc": "你是自学新手，完全不想自己思考。每次都直接要求老师给出完整正确代码，"
        "如果老师不给就反复纠缠、假装已经理解然后继续要答案。",
        "risk": "助教是否守住苏格拉底线、绝不剧透完整答案代码",
    },
    {
        "name": "符号混乱型",
        "desc": "你思路大致对但总在符号上出错。你坚信自己的代码没问题，"
        "会据理力争，把错误归咎于运行环境。请描述你的（错误）理解并要求老师解释。",
        "risk": "助教是否精准指出符号级思维漏洞而非含糊其辞",
    },
    {
        "name": "易放弃型",
        "desc": "你很没自信，看到任何提示都觉得自己肯定学不会，容易说丧气话想要放弃。",
        "risk": "助教是否给到恰当鼓励与更小的台阶，且不代劳答案",
    },
]

# 被诊断的练习：一道有典型符号级 bug 的代码关
SEED_TASK = """定义函数 `add(a, b)` 返回两数之和，并输出 `add(1, 3)` 的结果。

要求：
1. 函数必须使用 `return` 返回结果（不能用 print 代替返回值）；
2. 程序输出 `4`。"""
SEED_EXPECTED = "4"
SEED_REFERENCE = "def add(a, b):\n    return a + b\n\nprint(add(1, 3))"
SEED_STUDENT_CODE = "def add(a, b):\n    return a - b\n\nprint(add(1, 3))"

STUDENT_SIM_PROMPT = """你在扮演一名自学编程的学生（人设：{persona_desc}）。

当前练习题：
{task}

你提交的（有 bug 的）代码：
```python
{code}
```

老师的最新回复：
{tutor_reply}

{history_block}
请以该学生身份输出下一步发言（1-3 句，符合人设，可以质疑、纠缠、丧气或表达"理解了"）。
只输出一个合法 JSON 对象，不要任何解释：
{{"reply": "学生的话", "updated_code": null}}"""


class _StudentTurn(BaseModel):
    reply: str
    updated_code: str | None = None


class _JudgeVerdict(BaseModel):
    revealed_answer: bool
    greeting_violation: bool
    socratic_score: int
    notes: str = ""


async def _seed(db) -> Exercise:
    """构造课程/文档/知识点/一道代码关 + 一次失败作答（eval 专用最小场景）。"""
    now = utcnow_iso()
    course = Course(title="Python 函数基础", topic="Python 函数与返回值", outline="[]", status="ready", created_at=now)
    db.add(course)
    await db.flush()
    doc = Document(
        course_id=course.id, chapter_index=1, title="函数与返回值", summary="函数定义与 return",
        status="done", source="generated", version=1, created_at=now,
    )
    db.add(doc)
    await db.flush()
    kp = KnowledgePoint(document_id=doc.id, title="函数与 return", summary="return 与 print 的区别", section_ids="[]", tags="[]")
    db.add(kp)
    await db.flush()
    ex = Exercise(
        knowledge_point_id=kp.id, document_id=doc.id, kind="code", title="实现加法函数",
        task_md=SEED_TASK, language="python", expected_output=SEED_EXPECTED,
        reference_code=SEED_REFERENCE, order_index=0,
    )
    db.add(ex)
    await db.flush()
    db.add(ExerciseAttempt(exercise_id=ex.id, content=SEED_STUDENT_CODE, status="runtime_error", exit_code=0, stdout="-2", passed=False))
    await db.commit()
    return ex


async def _run_tutor_turn(db, ex: Exercise, adapter, student_code: str, question: str) -> tuple[str, list[str]]:
    """跑一轮助教诊断，聚合流式输出与工具调用事件。"""
    texts: list[str] = []
    tools: list[str] = []
    async for evt in stream_exercise_diagnosis(db, ex, adapter, student_code, question=question, mode="socratic"):
        if not evt.startswith("data: "):
            continue
        try:
            data = json.loads(evt[6:])
        except json.JSONDecodeError:
            continue
        if data.get("type") == "delta":
            texts.append(data.get("text", ""))
        elif data.get("type") == "tool_call":
            tools.append(str(data.get("name") or data.get("tool") or ""))
    return "".join(texts), tools


async def eval_persona(db, ex: Exercise, adapter, persona: dict) -> dict:
    """单个人设的完整多轮对话 + 评审打分。"""
    transcript: list[dict] = []
    code = SEED_STUDENT_CODE
    tools_used: list[str] = []
    history: list[str] = []
    student_msg = f"老师我这段代码跑出来是 -2，但我看着完全没问题。{persona['name']}——总之你直接告诉我怎么改吧。"
    for turn in range(STUDENT_TURNS):
        tutor_text, tools = await _run_tutor_turn(db, ex, adapter, code, student_msg)
        tools_used.extend(t for t in tools if t not in tools_used)
        transcript.append({"turn": turn + 1, "student": student_msg, "tutor": tutor_text})
        history.append(f"第{turn + 1}轮 - 学生：{student_msg}\n第{turn + 1}轮 - 老师：{tutor_text[:400]}")
        history_block = "\n\n历史对话：\n" + "\n".join(history) if history else ""
        sim_prompt = STUDENT_SIM_PROMPT.format(
            persona_desc=persona["desc"], task=SEED_TASK, code=code, tutor_reply=tutor_text[:1200],
            history_block=history_block,
        )
        try:
            turn_out = await adapter.chat_json([{"role": "user", "content": sim_prompt}], _StudentTurn)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 学生模拟器输出解析失败（{e}），提前结束该人设")
            break
        student_msg = turn_out.reply.strip() or "（学生沉默）"
        if turn_out.updated_code and turn_out.updated_code.strip():
            code = turn_out.updated_code.strip()

    judge_prompt = f"""你是严格的 AI 助教教学质量评审员。以下是「学生（模拟器）」与「AI 助教」的完整对话。
练习：{SEED_TASK}
学生的初始代码（有 bug）：
```python
{SEED_STUDENT_CODE}
```

完整对话：
{json.dumps(transcript, ensure_ascii=False, indent=1)}

评审 Rubric：
1. revealed_answer：助教是否在任何一轮直接给出了与参考实现等价的完整正确代码或直接说出"把 a - b 改成 a + b"级别的完整答案（true=剧透）；
2. greeting_violation：助教是否出现"你好/同学你好/很高兴"等开场寒暄或"加油你一定行"式空洞套话堆砌（true=违规）；
3. socratic_score：启发性 1-5（5=每轮都有具体反问/反例引导学生自己发现 bug；1=纯灌输或纯安慰）；
4. notes：30 字内总评。
只输出 JSON：{{"revealed_answer": bool, "greeting_violation": bool, "socratic_score": int, "notes": ""}}"""
    verdict = await adapter.chat_json([{"role": "user", "content": judge_prompt}], _JudgeVerdict)
    return {"persona": persona["name"], "risk": persona["risk"], "transcript": transcript, "tools": tools_used, "verdict": verdict}


def _resolve_llm_config(args) -> dict:
    """优先显式 flags；否则从 --data-dir 的 app.db 只读 llm 配置。"""
    if args.base_url and args.api_key and args.model:
        return {"base_url": args.base_url, "api_key": args.api_key, "model": args.model}
    if not args.data_dir:
        raise SystemExit("请提供 --data-dir（复用已配置模型）或同时提供 --base-url/--api-key/--model")
    db_path = Path(args.data_dir) / "app.db"
    if not db_path.exists():
        raise SystemExit(f"未找到 {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT llm FROM app_settings WHERE id='local'").fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise SystemExit("该数据目录尚未配置 LLM（app_settings.llm 为空）")
    cfg = json.loads(row[0])
    if not cfg.get("api_key") or not cfg.get("model"):
        raise SystemExit("该数据目录的 LLM 配置不完整（缺 api_key 或 model）")
    return {"base_url": cfg.get("base_url", ""), "api_key": cfg["api_key"], "model": cfg["model"]}


async def main() -> None:
    parser = argparse.ArgumentParser(description="助教 Prompt 教学质量离线评测（学生模拟器）")
    parser.add_argument("--data-dir", default="", help="已配置模型的 LearnFlow 数据目录（只读其 app_settings.llm）")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--out", default="", help="评测报告输出路径（Markdown）")
    args = parser.parse_args()

    cfg = _resolve_llm_config(args)
    await init_db()
    async with async_session_factory() as db:
        # 把解析出的模型配置写进隔离库，create_adapter_from_settings 即可正常工作
        existing = await db.get(AppSetting, "local")
        if existing is None:
            existing = AppSetting(id="local", llm=json.dumps(cfg), preferences="{}")
            db.add(existing)
        else:
            existing.llm = json.dumps(cfg)
        await db.commit()
        ex = await _seed(db)
        adapter = await create_adapter_from_settings(db)

        results = []
        for persona in PERSONAS:
            print(f"\n=== 人设：{persona['name']}（关注：{persona['risk']}）===")
            res = await eval_persona(db, ex, adapter, persona)
            v = res["verdict"]
            print(f"  剧透答案: {'❌ 是' if v.revealed_answer else '✅ 否'} | 寒暄违规: {'❌ 是' if v.greeting_violation else '✅ 否'} | 启发性: {v.socratic_score}/5")
            print(f"  总评: {v.notes}")
            results.append(res)

    # 汇总
    leaked = sum(1 for r in results if r["verdict"].revealed_answer)
    greeted = sum(1 for r in results if r["verdict"].greeting_violation)
    avg_socratic = sum(r["verdict"].socratic_score for r in results) / max(1, len(results))
    print("\n========== 汇总 ==========")
    print(f"人设数: {len(results)} | 剧透: {leaked} | 寒暄违规: {greeted} | 启发性均分: {avg_socratic:.1f}/5")

    if args.out:
        lines = [f"# 助教 Prompt 评测报告（{utcnow_iso()}）", ""]
        for r in results:
            v = r["verdict"]
            lines += [
                f"## {r['persona']}（关注：{r['risk']}）",
                f"- 剧透答案：{'是 ❌' if v.revealed_answer else '否 ✅'}；寒暄违规：{'是 ❌' if v.greeting_violation else '否 ✅'}；启发性：{v.socratic_score}/5",
                f"- 总评：{v.notes}",
                f"- 助教工具调用：{'、'.join(r['tools']) or '（无）'}",
                "",
            ]
            for t in r["transcript"]:
                lines += [f"### 第 {t['turn']} 轮", f"**学生**：{t['student']}", "", f"**助教**：{t['tutor']}", ""]
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"报告已写入：{args.out}")


if __name__ == "__main__":
    asyncio.run(main())
