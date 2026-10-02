# 学习 Agent 产品需求文档（PRD）

| 项目名称 | 学习 Agent（暂定名 LearnFlow） |
| --- | --- |
| 文档版本 | v0.1 |
| 日期 | 2026-09-30 |
| 状态 | 已评审通过（作为 M1 开发依据） |
| 产品定位 | 个人使用的 AI 学习助手：围绕任意课程（编程语言、高等数学等）生成学习文档，支持划线提问、费曼学习法、艾宾浩斯复习，形成完整学习闭环 |

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [用户画像与使用场景](#2-用户画像与使用场景)
3. [核心学习闭环](#3-核心学习闭环)
4. [用户故事](#4-用户故事)
5. [功能需求](#5-功能需求)
6. [非功能需求](#6-非功能需求)
7. [技术架构](#7-技术架构)
8. [数据模型](#8-数据模型)
9. [划线标注锚定方案](#9-划线标注锚定方案)
10. [学习算法细节](#10-学习算法细节)
11. [核心 API 草案](#11-核心-api-草案)
12. [路线图与里程碑验收标准](#12-路线图与里程碑验收标准)
13. [风险与应对](#13-风险与应对)
14. [非目标（Non-goals）](#14-非目标non-goals)
15. [术语表](#15-术语表)

---

## 1. 背景与目标

### 1.1 背景与问题

自学编程语言（如 C++）和高等数学等课程时，存在几个反复出现的问题：

- **资料不成体系**：网上的教程深度参差、顺序混乱，与自己的基础不匹配。
- **疑问被搁置**：阅读中遇到不懂的函数、定理、推导，缺少即问即答且答案可沉淀的渠道；疑问散落在脑子里或各种聊天窗口里，无法回溯。
- **"假懂"无法暴露**：看完觉得自己会了，实际讲不出来——缺少一个强迫输出、暴露理解漏洞的机制。
- **遗忘无管理**：学过的东西没有按遗忘曲线安排复习，等发现忘了时早已离首次学习太远。

### 1.2 产品目标

做一个**个人本地使用的学习 Agent**：

1. 用户写出想学的内容 → Agent 生成结构化课程大纲 → 确认后逐章生成学习文档。
2. 阅读文档时可以**划线**任意内容（函数、定理、代码段），弹出卡片，在卡片里与 AI **多轮对话**，对话与划线一起持久化保存，下次打开还能看到。
3. 内置**费曼学习法**：用自己的话讲解知识点，AI 扮演"学生"追问，最后给出理解度评价和漏洞清单。
4. 内置**艾宾浩斯遗忘曲线复习**：知识点自动生成复习卡片，按 SM-2 算法排期，每天有当日复习队列。
5. 底层架构为后续能力预留：代码在线运行（编程类课程）、平板访问、数学图形化。

### 1.3 成功标准

- 从输入"我想学 C++ 基础"到读上第一章文档，全程不超过 10 分钟（含大纲确认）。
- 划线提问的链路（选中 → 弹卡 → 提问 → 流式回答）流畅且**所有内容可持久化、可回溯**。
- 学 → 问 → 讲 → 复习 四个环节的数据相互打通：划线能转复习卡，费曼漏洞能回链文档位置，复习记录能反映薄弱点。

---

## 2. 用户画像与使用场景

**用户**：产品作者本人（个人工具，无多用户）。

**设备**：Windows 电脑为主。M3 阶段扩展到平板浏览器（通过内网穿透远程访问电脑上运行的服务）。

**典型场景**：

1. 晚上 2 小时学习时间：打开应用 → 今日复习队列（15 分钟）→ 继续读 C++ 下一章 → 划线问 `std::vector` 的扩容机制（卡片对话 3 轮）→ 用费曼模式讲一遍"指针与引用"→ AI 指出 2 个漏洞 → 漏洞自动进复习队列。
2. 周末：创建新课程"高等数学-多元微积分"，AI 生成大纲，调整章节顺序后确认，周末先读第一章，遇到偏导数记号不懂，划线提问并保存了 2 个标注。

---

## 3. 核心学习闭环

产品的一切功能都围绕这条闭环展开，四个环节的数据互相引用：

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   学 ──── 输入学习目标 → 大纲确认 → 逐章生成文档 → 阅读器  │
│   │                                                     │
│   │ 遇到不懂的：划线 → 弹出卡片 → 多轮提问（AI 答疑）      │
│   ↓   标注与对话持久化，成为个人"疑问档案"                 │
│                                                         │
│   讲 ──── 费曼模式：用自己的话讲解知识点                   │
│   │        AI 扮演学生追问 → 理解度评价 → 漏洞清单          │
│   ↓        漏洞回链到文档中的具体位置                      │
│                                                         │
│   复习 ── 知识点/漏洞自动生成复习卡                        │
│            SM-2 按遗忘曲线排期 → 每日复习队列              │
│            ↓                                            │
│          复习中暴露的薄弱点 → 回链文档/标注 → 回到"学"     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**数据打通规则**：

- 知识点（KnowledgePoint）在文档生成时自动抽取，是"讲"与"复习"的锚点。
- 费曼评价的每个漏洞（gap）必须携带 `section_id` 引用，前端可跳转到文档对应位置。
- 划线标注可以一键转为复习卡；费曼漏洞可以一键生成复习卡。
- 复习日志（ReviewLog）累积数据用于仪表盘的"薄弱知识点"分析。

---

## 4. 用户故事

| # | 用户故事 | 优先级 |
| --- | --- | --- |
| US-1 | 作为学习者，我想输入"我想学 C++ 基础，有其他语言基础"，并得到一份可编辑的课程大纲，以便控制学什么、学多深。 | P0 |
| US-2 | 作为学习者，我想让 AI 按大纲逐章生成带代码示例/LaTeX 公式的文档，生成过程中能看到进度，以便边生成边读。 | P0 |
| US-3 | 作为学习者，我想在阅读时划选任意文字并点击"提问"，弹出卡片与 AI 多轮对话，以便即时解决疑问。 | P0 |
| US-4 | 作为学习者，我想让划线和卡片对话都保存下来，下次打开文档还能看到高亮并继续对话，以便疑问可回溯。 | P0 |
| US-5 | 作为学习者，我想配置自己的 LLM API（base_url / api_key / 模型名），以便使用智谱 GLM、DeepSeek 或 OpenAI 等任意兼容服务。 | P0 |
| US-6 | 作为学习者，我想在费曼模式里用自己的话讲解一个知识点，让 AI 扮演学生向我提问，以便暴露理解漏洞。 | P1 |
| US-7 | 作为学习者，我想在讲解结束后得到分数、优点和漏洞清单，漏洞能跳转到文档对应位置，以便精准补漏。 | P1 |
| US-8 | 作为学习者，我想让知识点自动进入复习队列，每天打开应用先复习到期卡片，以便对抗遗忘。 | P1 |
| US-9 | 作为学习者，我想看到课程进度、到期复习量、薄弱知识点等仪表盘信息，以便安排学习。 | P2 |
| US-10 | 作为学习者（未来），我想在写代码示例时直接在文档内运行 Python/C++ 代码看到结果。 | M3 TODO |
| US-11 | 作为学习者（未来），我想在平板浏览器上访问电脑上运行的本应用。 | M3 |

---

## 5. 功能需求

优先级 P0/P1 进入 M1/M2；标注 **[M3 TODO]** 的功能本期只做架构预留，不做实现。

### 5.1 课程与文档生成（P0）

**FR-1.1 创建课程**
- 入口：首页"新建课程"。
- 输入：学习主题（如"C++ 基础"）、当前水平（可选：零基础/有其他语言基础/进阶）、期望深度与范围（自由文本）、章节数量偏好（默认自动）。
- 流程：提交后 LLM 生成课程大纲（JSON：章标题 + 每章要点 bullet + 预估难度），**进入大纲确认页**。

**FR-1.2 大纲确认（人机协同，质量关键闸口）**
- 用户可以：编辑章节标题、增删章、拖动排序、编辑每章要点、整体重新生成（可附一句调整指令，如"多加练习题章节"）。
- 确认后大纲锁定为课程属性，逐章生成以此为依据。

**FR-1.3 逐章生成流水线**
- 确认大纲后启动生成任务：按章节顺序生成（每章一次 LLM 调用，携带全局大纲 + 前面章节的摘要作上下文，而非全文，控制 token）。
- 每章生成完成后：落盘 Markdown 文件 → 解析建立 Section 索引（见 §8.3）→ 抽取知识点 → 更新进度。
- **断点续生成**：任务状态逐章持久化（pending / generating / done / failed），中断后重开应用可继续，失败章可单独重试。
- 前端实时进度：SSE 推送（第几章、生成中/完成/失败、耗时）。
- 生成期间可以阅读已完成章节。

**FR-1.4 文档内容规范（生成 prompt 的硬性要求）**
- 编程类课程：代码块必须使用 fenced code block 并标注语言（```cpp）；示例可运行、有注释。
- 高数类课程：公式必须用 KaTeX 兼容 LaTeX（行内 `$...$`，块级 `$$...$$`），避免 KaTeX 不支持的宏。
- 每章开头有"本章知识点"小结；篇幅预算默认 2000–4000 中文字/章（可在设置中调整）。
- 每章文档由 LLM 在同一生成流程中顺带输出结构化知识点清单（标题 + 一句话摘要 + 涉及的标题路径），作为 KnowledgePoint 数据。

**FR-1.5 重新生成与版本**
- 单章可"重新生成"（可附调整指令），生成成功后文档版本号 +1，旧版本快照保留在 `versions/` 子目录。
- 重新生成后按 §9 的锚定机制尽力保留旧标注。

### 5.2 阅读器（P0）

**FR-2.1 渲染**
- 渲染课程 Markdown：标题层级、段落、列表、表格、引用、代码块（Shiki 高亮）、KaTeX 公式（行内/块级）。
- 每个内容块（标题/段落/代码块等）携带稳定 `section_id`（来源 §8.3 索引），供标注锚定与漏洞跳转。

**FR-2.2 导航**
- 左侧目录树（按标题层级）；目录项高亮当前阅读位置，点击滚动定位。
- 章节间上一章/下一章导航；生成中的章节显示占位状态。
- 阅读进度（本章滚动百分比）本地记忆。

**FR-2.3 标注呈现**
- 已保存的标注在文档中渲染为高亮背景（不同颜色 = 不同标注），点击高亮打开对应卡片（见 FR-3）。
- 阅读器右侧提供"本文标注列表"抽屉，列出本章所有标注，点击定位。

### 5.3 划线提问卡片（P0，核心交互）

**FR-3.1 划线交互**
- 鼠标/触摸选中文本后浮现轻量工具条：`提问`（创建标注并打开对话卡片）、`高亮`（仅保存高亮，不开对话）、颜色选择（4 色）。
- 划线最小粒度：块内文本；支持跨行选择，不支持跨块选择（跨块选择提示"请分段划选"）。

**FR-3.2 提问卡片**
- 形态：从右侧滑出的卡片面板（不遮挡当前阅读位置；桌面端宽度约 420px），显示：划线原文（引用样式 + 跳回原文定位按钮）、该划线的**历史对话**、底部输入框。
- 对话：多轮，流式输出（SSE）；上下文自动携带划线原文及其所在章节内容（含前后章节摘要），保证 AI 答疑有据。
- 持久化：标注、每条消息实时落库；关闭卡片/应用后重开，高亮仍在、对话记录完整。
- 卡片内可执行操作：`转为复习卡`（把该疑问生成一张 ReviewCard）、删除标注、修改颜色。

**FR-3.3 标注管理**
- 标注可编辑备注（不进对话的私有笔记）、换色、删除（删除需确认，连带对话一并删除）。
- 文档重新生成后锚定失败的标注进入 `orphan` 状态：在标注列表中显示"原文已变更"，提供"重新挂载"（在文档中重新划选）或删除选项，不自动丢弃数据。

### 5.4 费曼学习模式（P1）

**FR-4.1 发起**
- 入口一：文档内知识点小节旁的"费曼讲解"按钮；入口二：仪表盘/知识点列表选择。
- 选择知识点后创建 FeynmanSession，展示：知识点摘要、来源文档链接、讲解输入区。

**FR-4.2 讲解与追问（AI 扮演学生）**
- 用户用自己的话写讲解（纯文本，支持公式与代码片段）。
- 提交后进入追问循环：LLM 以"好奇但较真的学生"身份，基于讲解内容 + 来源章节原文提出 1 个最关键的问题（一次只问一个，降低用户负担）。
- 用户作答 → AI 继续追问或表示满意；默认最多 4 轮（可在设置调整），AI 判定覆盖充分可提前结束。
- 每轮消息持久化，会话可中断、可稍后继续（状态机见 §10.2）。

**FR-4.3 评价与漏洞闭环**
- 用户随时点击"请给我评价"，或追问轮次结束时自动评价。
- 评价输出（结构化 JSON）：理解度评分 0–100、讲解的优点列表、**漏洞清单**（每条：问题描述 + 严重程度 + 回链 `section_id`）、改进建议。
- 漏洞清单展示时提供：`跳转到文档位置`、`生成复习卡`（一键或全部）。
- 会话结束后汇总存档，仪表盘可回看历史费曼记录与分数趋势。

### 5.5 复习系统：艾宾浩斯 / SM-2（P1）

**FR-5.1 复习卡来源**
- 自动：文档生成时抽取的 KnowledgePoint 每个自动生成一张复习卡（正面 = 知识点标题 + 提示问题，背面 = 摘要 + 文档回链）。可在课程设置中关闭自动生成。
- 手动：划线标注"转为复习卡"、费曼漏洞"生成复习卡"、复习页手工新建。
- 卡片可编辑正反面、可暂停（suspended）、可删除。

**FR-5.2 每日复习队列**
- 首页显示"今日到期 N 张"；到期队列按 `due_at` 排序，含新卡（受每日新卡上限控制，默认 20，可调）。
- 复习交互：显示正面 → 用户回忆 → 点"显示答案" → 四档自评按钮：`忘了` / `模糊` / `记得` / `轻松`（映射 SM-2 质量 1/3/4/5，见 §10.1）。
- "忘了"的卡片当天队尾重现，直至自评 ≥ 模糊。
- 每次评分写 ReviewLog（评分、间隔、EF 变化、复习前后状态），作为统计与薄弱点分析的数据源。

**FR-5.3 复习统计**
- 简单统计页：今日已复习/待复习、累计复习数、连续打卡天数、未来 7 天到期负载条形图。

### 5.6 学习仪表盘（P2）

- 课程卡片：进度（已完成章/总章）、最近学习时间。
- 今日概览：到期复习数、进行中的费曼会话数。
- 薄弱知识点榜：按（费曼评价漏洞次数 + 复习卡遗忘次数加权）排序，Top 10，点击跳转知识点。
- 学习热力图（GitHub 风格，按天统计学习动作数）。

### 5.7 设置（P0 基础版）

- **LLM 配置**：base_url、api_key、模型名、温度默认值；`测试连接` 按钮（发一条最小请求验证连通并显示模型回包）。支持保存多套配置并切换（如"便宜模型做生成 / 强模型做费曼评价"——M1 先做单配置 + 字段分组预留）。
- **生成参数**：每章篇幅预算、每日新卡上限、费曼最大追问轮数、每知识点练习数。
- **数据**：显示数据目录位置；提供"打开数据目录"按钮；说明备份方式（复制 `data/` 目录即可，文档为纯 Markdown 可用 git 管理）。

### 5.8 [M3 TODO] 代码运行沙箱

> 本期**不实现**，仅声明预留的架构位置，确保未来接入时不需要改动底层数据模型与 API 结构。

- 预留内容：`code_executions` 表结构（§8.2）、消息体中的 `code_block` 引用协议、后端 `services/execution/` 空目录与接口签名。
- 目标形态：文档代码块右上角"运行"按钮 → 后端受限沙箱执行（Python 直接子进程+资源限制；C++ 先编译后运行）→ 结果（stdout/stderr/耗时/退出码）回填到代码块下方，与文档位置绑定持久化。
- 安全红线：默认仅监听 127.0.0.1；沙箱进程限时（默认 10s）、限内存、无网络；Windows 下以受限作业对象（Job Object）运行。

### 5.9 [M3 TODO] 平板访问与桌面壳

- 平板：前端做响应式适配（划线交互改为长按选择）；后端提供 `--host 0.0.0.0` 启动选项 + 启动时展示局域网地址；文档化推荐的内网穿透方案（Tailscale/自建 frp）。平板只作客户端，服务始终运行在电脑上（符合用户"平板远程控制电脑"的设想）。
- 桌面壳：Tauri 包装（加载本地服务 URL），提供独立窗口、系统托盘、开机自启。数据与服务端不变。

### 5.10 练习系统（P1）

把"运用刚学的知识点"从静态文档练习升级为可交互、有判定的做题闭环（§5.1 的章节文档末尾练习仍保留，作为随文小练）。

**FR-10.1 出题**
- 入口：阅读页顶栏「📝 练习」抽屉 / 知识点浮层每条「📝 练习」链接；按**知识点**手动生成（可选 Python / C++，默认 2 题/知识点，设置可调 1–4）。
- LLM 单次调用产出题组（`chat_json` 校验，重试 ≤2）：代码题 + 概念简答题混合（≥1 道代码题 + ≥1 道概念题）。
- 出题与判定都以**教材原文**为依据，禁止超纲；重新生成会替换该知识点现有练习与作答记录。
- 章节重新生成时练习随知识点重建一并重置；删除课程级联清理。

**FR-10.2 代码题（自动判定）**
- 题面（任务说明）+ 带 `TODO` 注释的代码骨架 + 预期输出；学习者补全后点「▶ 运行判定」。
- 复用代码运行沙箱（§5.8）真实执行，**stdout 归一化对比**（统一换行、去行尾空白与首尾空行）自动判通过/未通过；编译失败/超时/运行错误给出对应中文提示。
- 题目硬约束（写入出题 prompt）：单文件可运行、禁标准输入、禁随机/时间/网络（保证输出确定）；预期输出与正确解法逐字符一致。
- 预期输出默认折叠，点「查看预期输出」按需揭示。

**FR-10.3 概念简答题（LLM 评分）**
- 题面具体（针对概念/区别/步骤/原因），附分点参考答案与评分要点（评分要点不下发前端）。
- 学习者作答后提交，LLM 按参考答案 + 教材原文评分：通过/未通过 + 分数（0–100）+ 中文评语（先肯定后指出缺漏，≤200 字）；"意思对即可"，有实质概念错误或关键要点缺失才判不通过。
- 参考答案默认折叠，作答后可按需查看。

**FR-10.4 作答记录**
- 每次提交落库（提交内容 + 判定结果 + 输出/评语），可无限次重试；抽屉回显**最近一次**作答（内容与通过状态），重开文档不丢。
- 每题可单独删除（连带作答记录）。

---

## 6. 非功能需求

| 类别 | 需求 |
| --- | --- |
| 部署 | 一条命令启动：后端同时托管 API 与前端构建产物，启动后自动打开浏览器；默认仅监听 `127.0.0.1`。 |
| 性能 | 阅读器打开单章文档 < 300ms（本地）；LLM 流式回答首 token < 3s（取决于服务方）；复习队列加载 < 200ms。 |
| 数据安全 | 全部数据本地存储（SQLite + 文件）；api_key 仅存本地数据库，日志中不得打印；请求仅发往用户配置的 LLM 地址。 |
| 可备份 | 删除性操作前确认；`data/` 目录自包含（数据库 + 文档 + 配置），复制即备份；文档为纯 Markdown，可用 git 版本管理。 |
| 可扩展 | LLM 供应商可替换（适配层）；数据模型全部携带 `user_id`（当前恒为 `local`）为未来多用户留位；SSE 事件格式统一，便于未来加消息类型。 |
| 健壮性 | LLM 调用失败可重试且有明确错误提示；生成任务中断可恢复；数据库使用 WAL 模式，异常断电不损坏。 |
| 兼容 | Windows 10/11（主要），路径处理全部使用 pathlib；Python 3.12；Node 20+（仅开发期构建前端）。 |

---

## 7. 技术架构

### 7.1 形态决策：本地 Web 服务为核心（不可逆决策，已定）

**决策**：不做纯桌面应用，而是 **FastAPI 本地服务 + 浏览器前端** 作为核心形态。服务同时托管 REST/SSE API 和前端静态构建产物，一条命令启动。

**理由**（此决策支撑三个已确认的诉求，是唯一不需要重写的路径）：

1. **桌面高效使用**：M1/M2 直接浏览器全屏/固定标签页使用；M3 套 Tauri 壳即获得独立窗口、托盘等桌面体验，**前后端代码零改动**。
2. **平板访问**：服务本质是 Web 服务，未来 `--host 0.0.0.0` + 内网穿透后，平板浏览器直接访问，**不需要任何新端**。
3. **开发效率**：跳过桌面打包链路，热重载开发，出问题调试直观。

```
M1/M2（当前）                     M3 演进（同一套代码）
┌──────────────┐                ┌──────────────┐
│  浏览器标签页  │                │ Tauri 桌面壳  │
└──────┬───────┘                │ 平板浏览器 ──内网穿透──┐
       │ http://127.0.0.1:8420  └──────┬───────┘       │
       ▼                               ▼               ▼
┌─────────────────────────────────────────────────────────┐
│              FastAPI 进程（本地常驻）                      │
│  ┌──────────┐ ┌───────────┐ ┌──────────────────────┐    │
│  │ REST/SSE │ │ 静态文件    │ │ 服务层                │    │
│  │ API      │ │ (前端构建) │ │ 生成流水线/费曼/SM-2   │    │
│  └──────────┘ └───────────┘ │ LLM适配器 [执行沙箱M3] │    │
│                             └──────────────────────┘    │
│         ▼                          ▼                    │
│   SQLite (data/app.db)     Markdown 文件 (data/courses/)│
└─────────────────────────────────────────────────────────┘
```

### 7.2 技术栈清单

| 层 | 选型 | 版本/说明 |
| --- | --- | --- |
| 后端框架 | Python + FastAPI | Python 3.12；Pydantic v2 做请求/响应与 LLM 结构化输出校验 |
| ORM / DB | SQLAlchemy 2.0 (async) + aiosqlite | SQLite，开 WAL 模式 |
| 依赖管理 | uv | `pyproject.toml` 锁定 |
| LLM 接入 | OpenAI 兼容协议适配层 | `base_url + api_key + model` 全部可配置；流式与非流式统一封装 |
| 前端框架 | React 18 + TypeScript + Vite | |
| 富文本/划线引擎 | TipTap（基于 ProseMirror） | 阅读器渲染与划线高亮的基础，ProseMirror 的位置映射是划线能力的关键 |
| 样式 | TailwindCSS | |
| 公式渲染 | KaTeX | 生成侧 prompt 强制 KaTeX 兼容语法 |
| 代码高亮 | Shiki | 构建期/运行时高亮，支持 cpp/python 等全语言 |
| 状态管理 | Zustand（UI 态）+ TanStack Query（服务端态） | |
| 流式通信 | SSE（`fetch-event-source`） | 对话流式输出、生成进度推送 |

### 7.3 LLM 适配层设计（不可逆决策，已定）

```
业务服务层（生成流水线 / 答疑 / 费曼 / 出卡）
        │  统一接口: chat(messages, stream=..., response_model=...)
        ▼
┌─────────────────────┐
│  LLMAdapter 抽象基类 │   ← 业务只依赖此接口
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ OpenAICompatAdapter │  （M1 唯一实现：智谱 GLM / DeepSeek / OpenAI /
└─────────────────────┘    Moonshot 等任何 OpenAI 兼容端点）
   （未来可加 OllamaAdapter 等实现，业务层无感）
```

- 适配层职责：请求组装、流式分片归一化（不同厂商 SSE 细节差异在此抹平）、错误分类（网络/鉴权/限流/内容审查）、重试策略、用量统计（token 数记录进消息）。
- 结构化输出：大纲、知识点抽取、费曼评价等使用 `response_format` / JSON mode + Pydantic 校验，校验失败自动重试（最多 2 次）。
- **Prompt 管理**：全部 prompt 以模板文件形式存放在 `backend/app/prompts/*.md`（含变量占位符），按场景命名（`outline` / `chapter_doc` / `annotation_qa` / `feynman_tutor` / `feynman_eval` / `card_gen`），禁止在业务代码里内联长 prompt——便于迭代调优与版本对比。

### 7.4 目录结构约定

```
学习agent/
├── docs/                      # PRD 与后续设计文档
├── backend/
│   ├── app/
│   │   ├── main.py            # 入口：挂载路由 + 静态文件 + 启动浏览器
│   │   ├── core/              # 配置加载(.env)、日志、常量
│   │   ├── models/            # SQLAlchemy 模型（§8）
│   │   ├── schemas/           # Pydantic 请求/响应模型
│   │   ├── api/               # 路由层（courses/documents/annotations/
│   │   │                      #   conversations/review/feynman/settings/dashboard）
│   │   ├── services/          # 业务逻辑
│   │   │   ├── llm/           # LLM 适配层（adapter 基类 + openai_compat 实现）
│   │   │   ├── generation/    # 大纲生成、逐章流水线、section 索引、知识点抽取
│   │   │   ├── anchoring/     # 划线锚定/重挂载（§9）
│   │   │   ├── review/        # SM-2 调度器
│   │   │   ├── feynman/       # 费曼状态机
│   │   │   └── execution/     # [M3 TODO] 代码运行沙箱占位
│   │   └── prompts/           # 全部 prompt 模板（.md）
│   ├── pyproject.toml
│   └── data/                  # 运行时数据（自包含，整体复制即备份；默认 gitignore）
│       ├── app.db             # SQLite
│       └── courses/{course_id}/{document_id}/
│           ├── current.md     # 当前版本正文（纯 Markdown，无内嵌标记）
│           └── versions/v{n}.md
└── frontend/
    ├── src/
    │   ├── features/          # reader / annotation / feynman / review / dashboard / settings
    │   ├── lib/               # api client、sse、锚定渲染辅助
    │   └── components/
    └── package.json
```

---

## 8. 数据模型

### 8.1 ER 总览

```
Course 1────* Document 1────* Section
   │              │  │
   │              │  └────* KnowledgePoint 1────1 ReviewCard (source_type=kp)
   │              │                │
   │              │                └────* FeynmanSession 1────1 Conversation 1────* Message
   │              │
   │              └────* Annotation 1────1 Conversation 1────* Message
   │                        │
   │                        └────1 ReviewCard (source_type=annotation, 可选)
   │
   └────（课程级统计由以上表派生，不单独建表）

ReviewCard 1────* ReviewLog                    （复习调度与日志）
Settings：单行表（id='local'）                    （LLM 配置 + 偏好）
code_executions：[M3 TODO] 预留，见 §8.2
```

所有业务表均含 `user_id TEXT NOT NULL DEFAULT 'local'`（为未来多用户预留，当前恒定）；主键一律为 UUID 字符串；时间戳统一 UTC ISO8601。

### 8.2 表结构定义

**courses**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | UUID |
| user_id | TEXT | 恒 `'local'` |
| title | TEXT | 课程名（可由主题生成） |
| topic | TEXT | 用户原始学习目标输入 |
| level | TEXT | 用户自述水平（可空） |
| outline | TEXT(JSON) | 确认后的大纲：`[{index, title, points[]}]` |
| status | TEXT | `draft / generating / ready / archived` |
| settings | TEXT(JSON) | 课程级覆盖项（如关闭自动出卡） |
| created_at / updated_at | TEXT | |

**documents**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | |
| user_id | TEXT | |
| course_id | TEXT FK | |
| chapter_index | INTEGER | 章序号（对应大纲 index） |
| title | TEXT | 章标题 |
| version | INTEGER | 当前版本号，从 1 起；重新生成 +1 |
| file_path | TEXT | 相对 data/ 的正文路径 `courses/{cid}/{did}/current.md` |
| status | TEXT | `pending / generating / done / failed` |
| created_at / updated_at | TEXT | |

**sections**（文档块索引，可由正文全文重建——这是"数据库为文件的派生索引"原则）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | 稳定块 ID（UUID 短码），**跨版本尽力保持**（见 §8.3） |
| user_id | TEXT | |
| document_id | TEXT FK | |
| version | INTEGER | 建立索引时的文档版本 |
| order_index | INTEGER | 块在文档中的顺序 |
| block_type | TEXT | `heading / paragraph / code / list / table / quote / math` |
| heading_path | TEXT(JSON) | 所属标题路径 `["第2章","2.3 指针"]` |
| content_hash | TEXT | 块规范化文本的 SHA-256 前 16 位 |
| text_excerpt | TEXT | 前 120 字符（供模糊锚定与搜索） |

**knowledge_points**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | |
| user_id | TEXT | |
| document_id | TEXT FK | |
| section_ids | TEXT(JSON) | 关联块 ID 列表（漏洞回链/跳转目标） |
| title / summary | TEXT | 知识点名与一句话摘要 |
| tags | TEXT(JSON) | 预留 |
| created_at | TEXT | |

**annotations**（划线标注，锚定字段见 §9）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | |
| user_id | TEXT | |
| document_id | TEXT FK | |
| section_id | TEXT | 锚定块 ID |
| version | INTEGER | 创建时文档版本 |
| exact | TEXT | 划线精确文本（去首尾空白） |
| prefix / suffix | TEXT | 前文 / 后文各 ~32 字符（模糊锚定用） |
| start_offset / end_offset | INTEGER | 块内字符偏移（**仅为提示值**，非权威） |
| color | TEXT | 4 色枚举 |
| note | TEXT | 私有备注（可空） |
| status | TEXT | `active / orphan` |
| created_at / updated_at | TEXT | |

**conversations / messages**（统一对话模型：划线答疑与费曼共用）

| conversations | | |
| --- | --- | --- |
| id | TEXT PK | |
| user_id | TEXT | |
| kind | TEXT | `annotation / feynman` |
| annotation_id | TEXT FK 可空 | kind=annotation 时指向标注 |
| feynman_session_id | TEXT FK 可空 | kind=feynman 时指向会话 |

| messages | | |
| --- | --- | --- |
| id | TEXT PK | |
| conversation_id | TEXT FK | |
| role | TEXT | `user / assistant`（system prompt 不存消息表，由服务层按模板现组装，保证 prompt 迭代后历史可解释） |
| content | TEXT | 正文（Markdown） |
| meta | TEXT(JSON) | 预留（token 用量、模型名、引用的 section_id 列表） |
| created_at | TEXT | |

**review_cards**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | |
| user_id | TEXT | |
| source_type | TEXT | `knowledge_point / annotation / feynman_gap / manual` |
| knowledge_point_id | TEXT FK 可空 | |
| annotation_id | TEXT FK 可空 | |
| front / back | TEXT | 正面（问题） / 背面（答案摘要 + 文档回链 section_ids） |
| state | TEXT | `new / learning / review / relearning`（SM-2 扩展状态机） |
| due_at | TEXT | 到期时间 |
| interval_days | REAL | 当前间隔（支持小数天，供同日重学步骤） |
| easiness_factor | REAL | EF，初始 2.5，下限 1.3 |
| repetitions | INTEGER | 连续答对次数 |
| lapses | INTEGER | 遗忘次数（薄弱点分析依据） |
| suspended | INTEGER(bool) | 暂停 |
| created_at / last_reviewed_at | TEXT | |

**review_logs**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | |
| card_id | TEXT FK | |
| reviewed_at | TEXT | |
| quality | INTEGER | 本次自评映射值 (1/3/4/5) |
| interval_days | REAL | 评分后的新间隔 |
| ease_factor | REAL | 评分后的 EF |
| state_before / state_after | TEXT | 状态迁移 |

**feynman_sessions**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | TEXT PK | |
| user_id | TEXT | |
| knowledge_point_id | TEXT FK | |
| conversation_id | TEXT FK | 对话体（messages 表复用） |
| status | TEXT | `explaining / questioning / evaluating / done`（§10.2） |
| round_count | INTEGER | 已追问轮数 |
| evaluation | TEXT(JSON) | 评价结果 `{score, strengths[], gaps[{desc, severity, section_id}], advice}` |
| created_at / updated_at | TEXT | |

**settings**（单行，id=`'local'`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| llm | TEXT(JSON) | `{base_url, api_key, model, temperature}` |
| preferences | TEXT(JSON) | `{daily_new_cards, chapter_length, feynman_max_rounds, auto_create_cards}` |
| updated_at | TEXT | |

**code_executions**（**[M3 TODO]** 本期不建表不实现，仅锁定设计以防未来数据模型冲突）

| 字段 | 说明 |
| --- | --- |
| id / user_id | 常规 |
| source_message_id / annotation_id | 运行请求来源（二选一可空） |
| document_id / section_id | 代码块在文档中的位置 |
| language / code | 语言与代码快照 |
| status / stdout / stderr / exit_code / duration_ms | 执行结果 |

**exercises**（§5.10）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id / user_id / created_at | | 常规 |
| knowledge_point_id | TEXT FK | 所属知识点（重建知识点时连带删除） |
| document_id | TEXT | 冗余章节 id，按文档列题用 |
| kind | TEXT | `code`（自动判定）/ `concept`（LLM 评分） |
| title / task_md | TEXT | 题目标题与任务描述（markdown） |
| language | TEXT | 代码题 `python / cpp`；概念题为空 |
| skeleton_code | TEXT | 代码题骨架（含 TODO 挖空） |
| expected_output | TEXT | 代码题预期 stdout（判定基准） |
| reference_answer | TEXT | 概念题参考答案与评分要点 |

**exercise_attempts**（§5.10，每次提交一条）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id / user_id / created_at | | 常规 |
| exercise_id | TEXT FK | |
| content | TEXT | 提交的代码或答案文本 |
| status | TEXT | 代码题=执行状态（§5.8）；概念题=`graded` |
| exit_code / stdout / stderr / duration_ms | | 代码题执行结果 |
| passed | BOOL(NULL) | 判定结果；执行未完成时为 NULL |
| feedback | TEXT | 概念题评语（含分数）；代码题失败提示 |

### 8.3 文档不可变原则与 Section 稳定 ID（不可逆决策，已定）

1. **正文只存文件，数据库存派生索引**：课程文档正文是磁盘上的纯 Markdown 文件（无任何内嵌 ID 标记，git 友好、可手工阅读）；`sections` 表是从文件解析出的**派生索引**，任何时候可删除重建（re-index 任务）。
2. **块划分规则**：以 Markdown 块级元素为粒度——每个标题、段落、列表（整块）、代码块、表格、引用块、独立公式块各为一个 section。ID 为随机短码，与内容无关。
3. **ID 稳定性策略**：文档同版本内 re-index 时，按 `(heading_path, content_hash)` 匹配保留旧 ID；文档重新生成（版本 +1）时，新旧版本逐块做相似度对齐，匹配度高的块**继承旧 ID**（保住划线），无法匹配的块发新 ID，旧标注转 `orphan`。
4. **位置信息永不作为权威**：任何锚定只认 ID + 文本（§9），偏移量仅作定位加速。这条原则保证用户外部编辑文件（允许，但需触发重建索引）不会系统性破坏标注。

---

## 9. 划线标注锚定方案（不可逆决策，已定）

> 划线持久化是本产品最核心也最容易做错的底层能力。采用类 Hypothesis.is 的**双重锚定（结构 + 文本）**方案。

### 9.1 锚定数据

创建标注时记录五元组：`(section_id, exact, prefix, suffix, offset_hint)`：

- `section_id`：划线所在块的稳定 ID（第一重锚：结构定位，O(1)）。
- `exact`：划线精确文本（第二重锚：内容验证）。
- `prefix` / `suffix`：划线前/后各约 32 字符上下文（模糊恢复依据）。
- `start/end_offset`：当时块内偏移，**仅作提示**。

### 9.2 渲染时锚定流程（前端）

```
1. 取文档 blocks（含 section_id）与该文档全部 annotations
2. 对每条标注：
   a. 找到 section_id 对应块 → 偏移提示处尝试精确匹配 exact
      ├─ 命中 → 高亮 [置信度: 精确]
      └─ 未命中 →
   b. 在该块全文中查找 exact（内容未变但位置漂移的情况）
      ├─ 命中 → 高亮 [置信度: 精确]
      └─ 未命中 →
   c. 用 prefix + exact + suffix 做模糊匹配（diff-match-patch，相似度阈值 0.8）
      ├─ 命中 → 高亮 [置信度: 模糊，视觉上用稍浅样式提示]
      └─ 未命中 → 标记 status=orphan
3. orphan 标注不出现在正文中，出现在标注列表中并提供重新挂载
```

前端实现依托 TipTap/ProseMirror 的 Decoration 机制渲染高亮（不改动文档内容本身），多标注重叠时按创建顺序分层。

### 9.3 重新挂载（re-anchor）

orphan 标注在标注列表中点"重新挂载"→ 进入选择模式 → 用户在文档中重新划选 → 后端用新五元组**原位更新**该标注（保留对话与创建时间），状态回 `active`。

---

## 10. 学习算法细节

### 10.1 SM-2 调度（艾宾浩斯复习的实现）

采用 SuperMemo-2 算法及其通用的四按钮交互映射（Anki 风格）：

| 按钮 | quality q | 语义 |
| --- | --- | --- |
| 忘了 | 1 | 完全想不起来 |
| 模糊 | 3 | 想起来了但费劲/有错漏 |
| 记得 | 4 | 正常想起 |
| 轻松 | 5 | 秒答 |

调度规则：

- `q >= 3`（记住）：`repetitions += 1`；间隔：第 1 次 = 1 天，第 2 次 = 6 天，第 n 次 = `round(interval_prev × EF)`。
- `q < 3`（遗忘）：`repetitions = 0`，`lapses += 1`，卡片进入 `relearning`，10 分钟后当天队尾重现；次日间隔重置为 1 天。
- EF 更新：`EF' = EF + (0.1 − (5−q) × (0.08 + (5−q) × 0.02))`，下限 1.3。
- 新卡投放：每日新卡上限 `daily_new_cards`（默认 20），新卡在当日到期队列尾部插入，保证复习优先于新学。
- 状态机：`new → learning（间隔 < 1 天的学习步骤）→ review → (遗忘) relearning → review`。

### 10.2 费曼会话状态机

```
 explaining ──提交讲解──► questioning ──(AI 追问 ⇄ 用户作答，≤ max_rounds)──┐
     ▲                          │                                          │
     │                    用户随时点"请求评价"                                │
     │                          ▼                                          ▼
     └────重新讲解（保留历史）─── evaluating ◄───────────────────────────────┘
                                     │ 生成结构化评价（分数/优点/漏洞/建议）
                                     ▼
                                    done（漏洞可一键回链文档 / 生成复习卡；
                                          可基于同一知识点再次发起新会话）
```

- **tutor prompt 要点**（`feynman_tutor.md`）：扮演"好奇但较真的初学者学生"，一次只问一个问题；问题必须针对讲解中的含糊、跳跃、错误；优先问"为什么"而不是"是什么"；检测到用户答非所问时礼貌指出。携带上下文：知识点摘要 + 来源章节原文 + 已有对话。
- **eval prompt 要点**（`feynman_eval.md`）：输出严格 JSON（Pydantic 校验）；每个 gap 必须给出 `section_id`（从提供的章节块列表中选择）；分数校准描述嵌入 prompt（如 85+ = 能清晰讲清边界情况）。
- 中断恢复：状态存 `feynman_sessions.status`，重开应用后可从任意状态继续。

### 10.3 文档生成流水线

```
输入学习目标
    │ ① outline prompt（含：主题/水平/范围/章节偏好）
    ▼
课程大纲 JSON ──用户编辑确认──► 锁定大纲
    │ ② 逐章循环（i = 1..n，顺序执行）：
    │     输入 = 全局大纲 + 章 i 要点 + 章 1..i-1 的内容摘要（每章 ≤300 字，由
    │            生成时顺带产出并存库）+ 内容规范（FR-1.4）
    │     输出 = 章正文 Markdown + 知识点清单 JSON + 本章摘要
    │     落盘 → section 索引 → 知识点入库(+自动出卡) → 进度 SSE 推送
    │     失败：该章标 failed，可单独重试，不阻塞后续章节的手动触发
    ▼
课程 status = ready
```

- 摘要传递而非全文传递：控制上下文成本，同时保持章节间衔接。
- 所有结构化输出（大纲、知识点、评价）走 Pydantic 校验 + 失败重试（≤2 次），重试仍失败则报错给用户并保留原始输出供排查。

---

## 11. 核心 API 草案

统一前缀 `/api`；成功响应直接返回数据体，错误返回 `{detail: string}`；流式接口用 SSE。

### 设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/settings` | 读取（api_key 掩码返回） |
| PUT | `/api/settings` | 保存 |
| POST | `/api/settings/llm/test` | 测试连通性，返回模型回包与延迟 |

### 课程与生成

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/courses` | 输入学习目标 → 创建课程并返回**大纲草稿** |
| PUT | `/api/courses/{id}/outline` | 提交编辑后的大纲，锁定 |
| POST | `/api/courses/{id}/generate` | 启动逐章生成任务（幂等，可断点续） |
| GET | `/api/courses/{id}/progress` | **SSE**：生成进度事件 |
| GET | `/api/courses` / `GET /api/courses/{id}` | 列表 / 详情（含各章状态） |
| POST | `/api/documents/{id}/regenerate` | 单章重新生成（可附指令） |
| DELETE | `/api/courses/{id}` | 归档删除（二次确认） |

### 阅读与标注

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/documents/{id}/content` | 返回 `{markdown, blocks:[{id,type,heading_path}], annotations}` |
| GET | `/api/documents/{id}/annotations` | 标注列表 |
| POST | `/api/documents/{id}/annotations` | 创建标注（§9 五元组），返回标注 + 自动创建的 conversation id |
| PATCH | `/api/annotations/{id}` | 改色/改备注/重新挂载（更新五元组） |
| DELETE | `/api/annotations/{id}` | 删除（连带对话） |

### 对话（划线答疑 & 费曼共用）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/conversations/{id}/messages` | 历史消息 |
| POST | `/api/conversations/{id}/messages` | 发送用户消息，**SSE** 返回 assistant 流式增量 + 结束事件（含消息 id 与用量） |

费曼专用：`POST /api/feynman/sessions`（指定 knowledge_point 开启）、`POST /api/feynman/sessions/{id}/evaluate`（触发评价，SSE 或同步返回 JSON）、`GET /api/feynman/sessions?knowledge_point_id=`。

### 练习（§5.10）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/exercises/generate` | `{knowledge_point_id, language, count?}` 为知识点出题（替换旧题），LLM 同步返回 |
| GET | `/api/exercises?document_id=` | 文档全部练习（含知识点标题与最近一次作答） |
| POST | `/api/exercises/{id}/submit` | `{content}` 提交作答：代码题执行并判定 / 概念题 LLM 评分 |
| DELETE | `/api/exercises/{id}` | 删除练习（连带作答记录） |

### 复习

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/review/queue/today` | 今日到期队列（含新卡配额计算） |
| POST | `/api/review/cards/{id}/grade` | 提交评分 `{quality}`，返回调度结果（新 due_at 等） |
| POST | `/api/review/cards` / PATCH / DELETE | 手动建卡 / 编辑 / 暂停删除 |
| GET | `/api/review/stats` | 统计（今日、连击、7 日负载） |

### 知识点与仪表盘

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/documents/{id}/knowledge-points` | 知识点列表 |
| GET | `/api/dashboard/summary` | 课程进度 + 今日概览 + 薄弱榜 + 热力图数据 |

---

## 12. 路线图与里程碑验收标准

### M1 —— 会学、会问（P0 全部）

范围：课程创建/大纲确认/逐章生成流水线、阅读器（公式/代码高亮/目录导航）、划线标注 + 卡片流式对话 + 持久化、设置页。

**验收标准**：

- [ ] 输入"我想学 C++ 基础（有其他语言基础）"，2 分钟内得到可编辑大纲；确认后逐章生成，中途关闭应用重开能继续生成。
- [ ] 高数课程文档中行内/块级公式正确渲染；C++ 代码块正确高亮。
- [ ] 划线 → 弹卡 → 三轮流式对话 → 关闭应用 → 重开：高亮仍在，点击高亮完整恢复对话。
- [ ] 手工改动某章 Markdown 文件一个段落措辞后触发重建索引，原有标注仍能锚定（精确或模糊）。
- [ ] 配置智谱 GLM 与 DeepSeek 两套 base_url 均可通过"测试连接"并正常生成。
- [ ] 数据目录复制到另一台电脑（装好运行时）后应用完整可用。

### M2 —— 会讲、会复习（P1 + P2）

范围：SM-2 复习系统全套、费曼模式全套、仪表盘。

**验收标准**：

- [ ] 生成课程后知识点自动成卡；每日队列遵守新卡上限；"忘了"的卡当天重现；间隔演进符合 §10.1 规则（用例验证：轻松×3 后间隔 ≥ 1→6→EF×6）。
- [ ] 费曼完整走通：讲解 → 至少 2 轮追问 → 评价输出合法 JSON（分数/优点/漏洞），每个漏洞可跳转到文档正确位置，可一键生成复习卡。
- [ ] 中断的费曼会话可从原状态继续。
- [ ] 仪表盘薄弱榜能反映"费曼漏洞 + 复习遗忘"两个数据源。

### M3 —— 运行、多端（TODO，先设计后实现）

- 代码运行沙箱（Python 先行，C++ 随后）：文档内运行、结果持久化、安全限制达标。
- 平板浏览器访问（响应式 + `--host` + 内网穿透文档）；Tauri 桌面壳。
- 数学图形化（SymPy 求解/化简、函数图像渲染，嵌入高数文档）。
- 视届时需求引入：本地 Ollama 适配器、语音讲解费曼、向量检索增强长课程答疑。

---

## 13. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| LLM 生成的数学内容有误（公式错、推导跳步） | 高数课程可信度受损 | 大纲人工确认是第一道闸；划线提问让疑问即时澄清；单章可重新生成；prompt 中明确"推导写全每一步"。接受残余风险：本产品定位是"学习辅助"而非"教科书替代"，用户须保有问题意识。 |
| 长课程生成 token 成本与耗时 | 等待久、花钱 | 逐章生成（可边读边等）、摘要传递控制上下文、篇幅预算可调、支持切换低价模型做生成。 |
| OpenAI 兼容实现间差异（SSE 细节、JSON mode 支持度） | 某供应商下结构化输出失败 | 适配层归一化；JSON 校验失败自动重试；不支持 JSON mode 的端点退化为 prompt 约束 + 解析容错。 |
| 划线锚定在文档重生成后丢失 | 核心体验受损 | §9 双重锚定 + 版本对齐继承 ID + orphan 重新挂载流程，保证**数据永不自动丢弃**。 |
| TipTap 划线渲染复杂度超预期 | M1 延期 | TipTap + Decoration 是成熟路径；M1 先支持块内单选区高亮，重叠/跨块等边界在 M1 内按 §9.2 规则降级处理。 |
| SQLite 并发写限制 | 生成任务与用户操作并发 | 单用户场景写频率低；WAL 模式 + 异步队列串行化生成任务的写操作，足够。 |
| Windows 子进程/路径问题（尤其未来沙箱） | M3 沙箱坑多 | 全线 pathlib；沙箱设计为可替换接口，先做 Python（subprocess + Job Object 限制），C++ 需要工具链检测与友好报错。 |
| api_key 泄露到日志/前端 | 安全 | 掩码返回；日志脱敏；服务默认只绑 127.0.0.1。 |

---

## 14. 非目标（Non-goals）

以下内容**明确不做**（或明确推迟），防止范围蔓延：

1. **多用户与云部署**：MVP 不做注册/登录/云端存储（数据模型已留 `user_id` 位）。
2. **移动原生 App**：平板只通过浏览器访问，不做 iOS/Android 客户端。
3. **在线 IDE 级代码运行**：M3 沙箱目标是"示例代码验证"，不是通用编程环境（无任意包安装、无长时任务）。
4. **RAG / 向量库**：MVP 用"章节摘要 + 划线上下文"拼接即可满足个人课程规模；架构不排除未来引入。
5. **协作与分享**：不做多人编辑、不做课程市场/分享链接。
6. **离线 LLM 为默认**：默认 OpenAI 兼容云 API；Ollama 适配器是未来可选项而非 M1/M2 目标。
7. **通用笔记软件**：标注与对话围绕"学习文档"存在，不做自由笔记/双向链接/标签系统。

---

## 15. 术语表

| 术语 | 含义 |
| --- | --- |
| SM-2 | SuperMemo-2 间隔重复算法，用 EF（易度因子）与间隔控制复习排期，是 Anki 的核心算法 |
| 费曼学习法 | 通过"向别人讲解"来检验和深化理解的学习方法；本产品中 AI 扮演被讲解的学生 |
| 艾宾浩斯遗忘曲线 | 描述记忆随时间衰减的规律，间隔重复即按此规律安排复习时点 |
| Section | 文档中一个块级元素（标题/段落/代码块等）及其实例记录，携带稳定 ID |
| 锚定（Anchoring） | 将划线标注重新定位到文档内容的过程；本产品采用"块 ID + 精确文本 + 上下文"双重锚定 |
| orphan 标注 | 因文档变更而无法重新定位的标注；保留数据并支持手动重新挂载 |
| 费曼漏洞（gap） | 费曼评价中指出的具体理解缺陷，携带文档位置引用 |
| OpenAI 兼容 API | 实现了 OpenAI Chat Completions 协议（含 SSE 流式）的服务接口，当前主流 LLM 服务普遍提供 |
| SSE | Server-Sent Events，HTTP 单向服务端推送，用于流式回答与生成进度 |
| TipTap / ProseMirror | 前端富文本/文档渲染框架，提供划线高亮所需的 Decoration 与位置映射能力（见 §16 实现备注：阅读器实际采用自研块渲染器） |

---

## 16. 实现备注（M1-M2 交付时）

以下为编码实现阶段对上文的具体化与偏差记录，**实现以此为准**：

1. **阅读器渲染方案**：放弃 TipTap/ProseMirror，改用**自研块渲染器**——markdown-it 逐块渲染 + KaTeX auto-render + Shiki 代码高亮 + DOM 文本节点切分实现高亮包裹。理由：只读文档场景下 TipTap 的数学/代码扩展集成复杂度高、收益低；自研方案锚定原理不变（块 ID + 文本 + 上下文，渲染时 diff-match-patch 模糊定位）。
2. **前后端块对齐**：后端用 `markdown-it-py`（js-default 预设）、前端用 `markdown-it`（默认预设）——两者为同源移植，同一份 Markdown 的顶层块序列与行号范围一致，块索引可按行号精确对齐。权威解析器为后端 `app/services/docparser.py`，前端 `src/lib/markdown.ts` 保持同规则。
3. **启动方式**：`cd backend && uv run python -m app.main`，监听 `127.0.0.1:8420` 并自动打开浏览器；前端构建产物输出到 `backend/app/static/` 由 FastAPI 托管（SPA fallback）；开发模式 `uvicorn --reload` + `vite dev`（:5173 代理 /api）。
4. **数据模型微调**：`documents` 增加 `summary`（章节摘要，供后续章节生成的上下文传递）与 `error` 字段；`review_cards` 增加 `introduced_at`（每日新卡配额依据）；费曼会话创建即进入 `questioning` 状态（`explaining` 保留给未来）。
5. **章节生成输出协议**：单次 LLM 调用输出正文 + `<LEARNFLOW_META>` 分隔符 + JSON（`{summary, knowledge_points[]}`），省去第二次抽取调用；JSON 解析失败不致命（正文仍有效）。
6. **批注对话获取**：标注列表不含 conversation_id，前端通过 `GET /api/annotations/{id}/conversation` 获取（创建时直接用响应里的）。
7. **里程碑范围确认**：M1+M2 一次性交付（课程生成/阅读器/划线卡片/设置 + 复习/费曼/仪表盘）；§5.8-§5.9 的 M3 项目仍为 TODO 未实现。
8. **§5.8 代码运行沙箱（M3 已实现）**：`code_executions` 表落地时省略了 `source_message_id/annotation_id`（本实现运行来源恒为文档代码块，仅保留 `document_id/section_id`）；Windows 下 Job Object 提供 内存 256MB / 进程数 64 / kill-on-close 限制，**网络隔离未强制执行**（Job Object 无法便捷禁网，本地单用户场景由时间/进程/内存限制兜底）——§5.8 的"无网络"红线在此场景下以资源限制替代；Python 用当前解释器 `-I -B -X utf8` 隔离运行；C++ 需要系统 PATH 中有 g++/clang++，缺失时返回 `compiler_missing` 与安装指引；执行结果持久化，阅读器按块回显最新一条。
9. **校验错误归一**：全局 RequestValidationError 处理器把 FastAPI 默认的 422 结构化错误转为 400 + 中文平铺消息。
10. **M1/M2 缺口收口**：复习页手工建卡、课程级"自动生成知识点复习卡"开关（`PATCH /api/courses/{id}`）、仪表盘薄弱点直达费曼入口、费曼列表显示知识点标题，均已补齐。
11. **§5.9 桌面壳（已实现）**：Tauri 2 壳位于 `desktop/`，加载 `http://127.0.0.1:8420`（`LEARNFLOW_PORT` 可覆盖）。壳负责后端进程生命周期：启动时若端口空闲则以 `uv run python -m app.main` 拉起（隐藏窗口、禁自动开浏览器），TCP 轮询就绪后跳转，退出时 kill 回收；后端目录定位顺序为 `LEARNFLOW_BACKEND_DIR` → 从 exe 向上查找。托盘：显示窗口 / 开机自启（tauri-plugin-autostart）/ 退出；关窗为隐藏到托盘。个人本机模式后端仍以 uv 源码方式运行（未做 PyInstaller sidecar 打包），分发安装包的前提是目标机器具备 uv + 项目目录；后续做成独立发行版时再引入 sidecar。
12. **自有 Markdown 导入（M3 增补，已实现）**：`POST /api/courses/import/analyze` + `POST /api/courses/import`（multipart）。切章为机械规则（≥2 个 h1 按 h1 切 → 否则 ≥2 个 h2 按 h2 切 → 整文件一章；章内次级标题作大纲要点），LLM 仅用于修饰课程标题与提取知识点（未配置 LLM 时导入仍可用，跳过知识点）。原文保留三层含义：章节内容为原文精确切片（仅行号定位统一换行）、完整原件归档到 `courses/{cid}/originals/`、用户磁盘源文件只读；`documents.source = imported` 的文档禁用重新生成（API 400 + 前端隐藏入口）。
13. **场景化模型（§5.7 预留项落地）**：`app_settings.llm` JSON 增加 `scenes: {generation, chat, feynman}` 三槽位，适配层 `create_adapter_from_settings(db, scene)` 按字段级覆盖（场景非空字段覆盖主配置，空字段回落），api_key 空白/掩码继承旧值；调用点：章节生成与导入提取=generation、划线答疑=chat、费曼追问与评价=feynman。设置页支持智谱/DeepSeek/OpenAI/Moonshot/Ollama 快捷预设（Ollama 走 OpenAI 兼容端点 `localhost:11434/v1`，无需独立适配器）。
14. **高数图形化（§5.9 已实现）**：`POST /api/math/render`（SymPy 解析 + Matplotlib Agg 渲染 SVG，即时返回不持久化）；前端 ` ```plot ` 代码块「📐 绘图」按钮，支持多函数、奇点断线；sympify 后校验自由符号只允许 x（防止把任意标识符当符号渲染）。平板访问：`APP_HOST=0.0.0.0` + 启动打印局域网地址 + 前端响应式（移动抽屉导航/目录浮层/触屏划线/卡片全宽）；内网穿透推荐 Tailscale（README 有安全提示）。
15. **启动时更新检查（已实现）**：`GET /api/version`（版本源为 `app/core/config.py` 的 `APP_VERSION`，发布时与 tauri.conf.json/package.json 一同 bump）+ `POST /api/update/check?force=`。查 GitHub Releases latest（未认证 API，5s 超时，失败静默降级绝不阻塞启动）；仓库来源=设置页偏好 `github_repo`（owner/repo）→ 回落环境变量 `APP_GITHUB_REPO`，两者皆空则禁用。前端打开时自动检查（后端节流 1h，设置页按钮强制），有新版显示可关闭横幅（「本次忽略」按版本记忆于 sessionStorage）。版本比较忽略 tag 前缀 v、预发布版小于正式版。
16. **运行环境一键安装（§5.8 增补，已实现）**：`GET /api/runtime/status`（检测 bundled/managed/system/none + 版本）+ `POST /api/runtime/install`（后台线程，进度走 `GET /api/runtime/install/status` 轮询）。便携包落在软件目录 `toolchains/`（安装目录只读时兜底数据目录），**不写系统 PATH/注册表**；C++ 用 niXman mingw-builds 14.2.0 UCRT（7z 约 92MB，py7zr 解压），Python 用 python.org embeddable 3.12.10（约 11MB）。下载源用 512KB Range 试读择优（GitHub 直连 → ghproxy/gh-proxy 镜像；python.org → 华为云 → npmmirror）。沙箱查找顺序：系统 PATH → 托管目录（Python 为 打包内置 → 托管 → PATH）。已知坑的处置：7z 解压会还原只读属性（删目录前先递归清只读位）；杀软短暂锁文件用退避重试；gcc 对 argv[0] 做 realpath 导致 junction 别名失效，改用**硬链接镜像**到纯 ASCII 基（系统码页表示不了非 ASCII 安装路径时 ld 会找不到 crt 对象，GBK 码页系统不受影响）；MinGW 编译产物的运行时 DLL 与 g++ 同目录，运行时把该 bin 目录前置到子进程 PATH；**编译步同理**——cc1plus/collect2 等 g++ 子进程的 libwinpthread-1.dll 等 DLL 也只在 bin 目录（打包版实测：漏掉编译步会在用户机器上弹「找不到 libwinpthread-1.dll」系统错误，开发环境能跑纯因 PATH 里恰有 Git 自带的同名 DLL）；后端进程启动即 SetErrorMode(SEM_FAILCRITICALERRORS)，沙箱子进程继承后缺 DLL 等加载硬错误静默转为退出码，不再弹模态框卡住应用。前端入口：设置页「代码运行环境」区块 + 代码块 `compiler_missing` 结果下的内联一键安装。
17. **练习系统（§5.10，已实现）**：出题复用 `generation` 场景、概念题评分复用 `chat` 场景（不新增场景槽位）；出题 prompt 的占位符用 `[[VAR]]` 语法（与代码大括号天然不冲突）。代码题判定在服务层做 stdout 归一化对比（统一 CRLF、去行尾空白与首尾空行），沙箱 runner 零改动（stdin 仍 DEVNULL，题目一律禁 `input()`）；概念题分数不单独落库，折叠进 feedback（`（90 分）…`）。练习挂在知识点上：章节重新生成即重置（与自动复习卡同策略），出题接口为"替换式"（重新生成覆盖旧题与作答）。前端不做代码高亮编辑器（v1 用 mono textarea + Tab 缩进），抽屉 420px；提交后靠 `["exercises", documentId]` 查询失效回显最新作答（与代码块执行回显同模式）。冒烟测试覆盖非 LLM 路径（判定/回显/级联/未配 LLM 400）；出题与评分链路用本地 OpenAI 兼容 mock 服务手测验证。
