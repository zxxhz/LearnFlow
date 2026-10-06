---
name: bank-drill-module-plan
description: 「题库刷题」独立模块已实现完成（2026-10-03，v0.3.0）——网安竞赛题库(463题.xls)导入学习agent
metadata:
  node_type: memory
  type: project
  originSessionId: sess_af135915-7feb-486a-be46-d8c03d39eae0
---

「学习agent」的独立「题库刷题」模块已于 2026-10-03 实现完成并验证（版本 bump 0.3.0）。用户三个决策：① 独立模块（不进课程体系）；② 不迁移老应用进度（从零开刷）；③ 随机组卷（10/20/50 题/轮）。

**实现落点**：后端 models/services/schemas/api 各一个 bank.py（新表 question_banks/bank_questions/bank_attempts；错题池=追加式 attempt 按「每题最近一次未通过」派生，无状态机）；前端 features/bank/（BankListPage /bank、BankDrillPage /bank/:id、BankQuestionCard）+ 导航「🎯 题库刷题」+ api.banks 命名空间。依赖 xlrd/openpyxl 已入 pyproject 与 learnflow_backend.spec hiddenimports。

**验证状态**：真实题库 463 题导入 API 端到端通过（单选337/多选65/判断61，跳过1行与老应用 bank_meta 一致）；smoke_test.py 新增 20 项题库 case 全绿（但需 `APP_DATA_DIR=data-smoke APP_PORT=8431 PYTHONPATH=. uv run python scripts/smoke_test.py` 隔离跑——用户常驻应用实例会锁 data/app.db）。

**遗留与后续演进**：
- ~~PyInstaller 打包未实际重跑~~ 已在 v0.3.4→v0.4.0 发版构建时覆盖验证（xlrd/openpyxl 正常入包）。
- **v0.4.22 补齐 LLM 智能解析与专属提示词**：做错题目支持 AI 深度解答（原生 SSE 打字机流式，Markdown + KaTeX）；题库支持专属系统提示词，未设置自动回退内置启发式名师黄金提示词；支持一键 AI 润色提示词并原地无缝替换内容。
- **v0.4.23 错题解析全链路保留与小结修复**：小结列表统一采用 `visibleOptions` 重构选项渲染（单选/多选/判断全覆盖）；`bank_questions.ai_explanation` 字段持久化，作答时生成的解析在查看小结与未来刷题中永久保留、0ms 秒开无重复请求，支持重新生成。

