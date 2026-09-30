## 任务

在 `C:\Users\Emoing\Desktop\学习agent` 下编写 **docs/PRD.md** —— 一份完整的中文产品需求文档，覆盖产品需求、技术栈选型、以及后续难以修改的底层架构设计。**本轮只写 PRD 文档，不写代码**（你确认 PRD 后的下一轮再开始搭建项目）。

## 已确认的关键决策

1. **个人使用**，无账号体系（数据模型预留 user_id 字段以防未来扩展）
2. **形态：本地 Web 服务为核心**——FastAPI 同时托管 API 与前端构建产物，一条命令启动、浏览器打开 localhost。M3 再加：Tauri 桌面壳（桌面体验）、响应式适配 + 内网穿透（平板访问）。理由：这是唯一同时满足"桌面用 + 未来平板访问"且无需重写架构的方案；纯桌面应用无法被平板浏览器访问
3. **后端 Python 3.12 + FastAPI**；前端 React 18 + TypeScript + Vite
4. **LLM 走 OpenAI 兼容协议**（base_url + api_key + model 可配置，智谱 GLM / DeepSeek / OpenAI 自由切换），后端做适配器层抽象，不锁死任何一家

## PRD 将锁定的底层架构（难以修改的部分，PRD 重点）

### 技术栈
- **前端**：React 18 + TS + Vite；TipTap(ProseMirror) 做阅读器与划线标注（行业成熟方案）；TailwindCSS；KaTeX 渲染高数公式；Shiki 代码高亮；Zustand + TanStack Query；SSE 流式对话
- **后端**：FastAPI + Pydantic v2；SQLAlchemy 2.0 (async) + aiosqlite；uv 管理依赖
- **存储**：SQLite（标注/对话/复习记录等结构化数据）+ 磁盘 Markdown 文件（课程文档本体，可 git 备份、可迁移）的混合方案
- **LLM**：OpenAI 兼容适配层 + 按场景的 prompt 模板管理（文档生成/划线答疑/费曼评价/卡片生成）

### 数据模型（PRD 核心章节）
- Course（课程）→ Document（文档，带 version 版本号，文档不可变原则）→ Section（稳定块 ID，每个标题/段落/代码块生成时分配）
- KnowledgePoint（知识点，文档生成时自动抽取，是费曼与复习的锚）
- **Annotation（划线标注）：双重锚定方案**（块 ID + 文本引用 + 前后文上下文，类 Hypothesis.is），文档轻微改动不丢标注——这是划线功能最难改的底层设计
- Annotation → Conversation（卡片内多轮对话，流式，全部持久化，重开文档可见）
- ReviewCard（SM-2 / 艾宾浩斯调度：间隔、难度系数、复习队列）
- FeynmanSession（费曼讲解记录 + LLM 扮演学生的追问 + 理解度评价 + 漏洞清单回链文档）
- CodeExecution（M3 代码运行结果预留字段，现在只留接口）

### 学习闭环（产品核心逻辑）
学（输入学习目标 → LLM 生成大纲 → 确认后逐章生成文档）→ 问（划线弹出卡片对话）→ 讲（费曼：用自己的话解释，LLM 扮演学生提问并评价）→ 复习（知识点自动进入 SM-2 队列，每日复习）

### 路线图
- **M1**：课程创建与文档生成（大纲确认 → 逐章生成，可断点续生成）+ 阅读器（LaTeX 公式/代码高亮/目录导航）+ 划线提问卡片（流式对话 + 持久化）+ 基础设置页（LLM 配置）
- **M2**：艾宾浩斯复习系统（SM-2 每日队列 + 复习界面）+ 费曼学习模式 + 学习仪表盘（进度/薄弱知识点）
- **M3（TODO，PRD 只做设计预留）**：代码运行沙箱（Python/C++）、移动端响应式 + 内网穿透方案、Tauri 桌面壳、高数图形化（SymPy/Matplotlib）

## 交付物

- `docs/PRD.md`：完整 PRD（背景与目标 / 用户画像 / 用户故事 / 功能需求详述 / 非功能需求 / 技术架构图 / 数据模型与 ER 说明 / 核心 API 草案 / 学习算法细节（SM-2 参数、费曼流程状态机、文档生成流水线）/ 划线锚定方案 / 路线图 / 风险与应对 / 非目标）