<h1 align="center">LearnFlow</h1>

<p align="center">
  <strong>本地运行、注重隐私的 Agentic AI 伴学与高效刷题系统</strong>
</p>

<p align="center">
  <a href="https://github.com/zxxhz/LearnFlow/releases"><img src="https://img.shields.io/github/v/release/zxxhz/LearnFlow?style=flat-square&color=2563eb" alt="GitHub release" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/zxxhz/LearnFlow?style=flat-square&color=blue" alt="License" /></a>
  <a href="https://github.com/zxxhz/LearnFlow/stargazers"><img src="https://img.shields.io/github/stars/zxxhz/LearnFlow?style=flat-square&color=eab308" alt="GitHub stars" /></a>
  <a href="https://github.com/zxxhz/LearnFlow/issues"><img src="https://img.shields.io/github/issues/zxxhz/LearnFlow?style=flat-square" alt="GitHub issues" /></a>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/React-18-20232A?style=flat-square&logo=react&logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/Tauri-v2-24C8DB?style=flat-square&logo=tauri&logoColor=white" alt="Tauri" />
</p>

<p align="center">
  <a href="https://github.com/zxxhz/LearnFlow/releases">下载安装包</a> ·
  <a href="docs/PRD.md">产品设计文档</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="https://github.com/zxxhz/LearnFlow/issues">反馈问题</a>
</p>

---

## 背景与设计理念

在自学编程语言（如 C++、Python）和高等数学等强逻辑学科时，传统的自学流程常存在三大断层：**教程零散不成体系**、**阅读疑问散落无法回溯**、**缺少真实从零写代码的客观判题闭环**。而普通的 AI 对话助手往往扮演“答题器”，卡壳时直接剧透完整答案，容易让人陷入“看懂了但写不出”的“假懂”陷阱。

**LearnFlow** 旨在打破这些壁垒：系统从单纯的单向问答（Chat）进化为具备**感知诊断、动态工具链调用（Tool Calling）、学习者认知建模**的真正 Agentic 伴学智能体，为自学者构建“**编撰体系讲义 ➔ 沉浸精读研讨 ➔ 链式闯关练习 ➔ 启发助教引导 ➔ 题库极速刷题 ➔ 错题定向清零**”的完整闭环。

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   学 ──── 输入目标 → 大纲协同确认 → 逐章流式生成讲义 → 沉浸阅读器  │
│   │        自动划重点提炼核心定义，沉浸式双栏排版 + ADHD 护眼模式 │
│   │ 遇到疑问：划线 → 弹出研讨卡片（平滑避让）→ 多轮原位持久化对话 │
│   ↓                                                             │
│                                                                 │
│   练 ──── 链式闯关：由浅入深解锁，渐进提示 + 目标输出常显       │
│   │        无骨架从零手写代码 / 数学表达式                      │
│   │        本地受限沙箱真实运行 / SymPy 代数等价客观判题        │
│   ↓                                                             │
│                                                                 │
│   伴 ──── 遇阻召唤启发式助教：苏格拉底式诊断思维盲区与漏洞      │
│   │        助教自主调用 Tool Calling 工具链（沙箱/绘图/透视）    │
│   ↓        持久化沉淀学习者认知画像与易错模式模型               │
│                                                                 │
│   刷 ──── 练习错题自动进错题本，集中攻坚直至重刷通过出池        │
│            独立题库模块：Excel 批量秒级导入 → 随机组卷 → 错题专练 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 功能特性

- **🤖 启发式伴学 Agent** — 卡壳时提供苏格拉底式启发引导，自主循环调用本地沙箱实测、函数绘图与关卡透视工具链，杜绝直接剧透，沉淀学习者认知画像与易错模式。
- **⚔️ 链式代码与代数闯关** — 知识点关卡由浅入深链式顺序解锁；无预填骨架逼迫从零手写代码；提供渐进式折叠提示；内置 SymPy 代数等价判题引擎客观判定数学表达式。
- **🎯 独立题库刷题模块** — 独立于课程体系的刷题引擎，支持 Excel（`.xls` / `.xlsx`）批量秒级导入单选、多选与判断题，支持 10/20/50 题极速随机组卷与专属动态错题池。
- **📚 沉浸式阅读与 ADHD 模式** — 生成讲义自动提炼划重点；阅读页自动隐藏全局侧栏转换为左侧完整目录树与右侧正文双栏布局；专设 ADHD 辅助模式（段落交替护眼色块 / 悬停动态聚焦）；划线提问卡片与正文平滑避让。
- **🖥️ 本地隔离沙箱与高数绘图** — 内置 Python 隔离环境与 C++ 编译沙箱（10 秒强制限时、256MB 内存 Job Object 约束）；支持一键安装便携编译器；内置 ` ```plot ` 代码块一键绘制高清函数曲线。
- **📱 局域网访问与 PWA 跨端支持** — 遵循最小暴露原则默认关闭局域网，设置页一键开启并配备高强度令牌保护；全站支持 PWA，可在平板（iPad）或手机上一键添加到主屏幕体验原生 App 级沉浸交互。
- **🔒 纯本地数据主权与纯净打包** — 全部数据落盘于本地 SQLite（WAL 高性能模式）与 Markdown 文本；设置页一键打包 zip 备份与无损热还原；四层长效防御彻底剔除 Matplotlib 示例图片防相册泄漏。

<details>
<summary>点击展开查看详尽功能说明</summary>

### 🤖 启发式伴学 Agent（Tutor）
- **启发式诊断感知**：闯关失败或执行报错时，卡片即刻浮现「💡 呼叫助教启发诊断」。助教精准定位代码与逻辑偏差，循循善诱，支持多轮流式（SSE）追问。
- **动态工具链闭环（Tool Calling）**：助教具备工具自主调用循环（Agent Loop），在辅导时可主动调用沙箱实测代码猜想（`run_sandbox_code`）、动态调用 SymPy 绘制函数图像（`render_math_plot`）、透视关卡测试用例与标准边界（`inspect_exercise`），前端实时呈现动态执行卡片动效；对不支持 Function Calling 的模型具备平滑纯文本降级保护。
- **学习者认知画像建模**：数据库持久化建档学习者档案（`learner_profiles`：先验知识、认知风格、引导偏好）与认知漏洞（`learner_misconceptions`：易错模式、错误证据、修复状态）；支持「💡 启发」与「📖 直答」双模态自由切换。

### ⚔️ 链式闯关练习与代数/代码判定
- **知识点链式解锁**：同一知识点下的关卡按由浅入深的通关链路编排，前一关通过方可解锁下一关（通关状态永久记录）。
- **从零手写与渐进提示**：每关呈现明确任务、目标输出常显，不提供现成代码骨架，倒逼学习者从零动手敲代码，真实标准输出（stdout）对比判定；配套 2-3 条渐进式提示（Hints，默认显露第 1 条，攻坚卡壳时按需展开）；通关后方可查看参考实现（Reference Code）。
- **SymPy 代数等价判题引擎**：新增 `math` 练习题型，利用符号代数化简判定 `simplify(u - e) == 0`，支持乘法交换律、同类项合并、指数展开等客观数学等价性验证。
- **错题自动进池与随堂小测**：做错题目自动纳入错题本，重刷通过后自动移出；支持跨知识点随机抽题组合「随堂小测」测试出分；存量选择/填空/概念题作为支线保留。

### 🎯 独立题库刷题模块
- **Excel 批量极速导入**：独立于课程体系的刷题引擎，支持 `.xls` 与 `.xlsx` 格式秒级导入单选、多选、判断题。
- **卡片式组卷刷题**：自由选择 10 / 20 / 50 题/轮极速随机组卷，作答即时打分与解析。
- **动态错题池机制**：作答记录追加存储，以每道题最新一次作答状态自动派生错题池，支持错题专项重刷，攻坚通过即时出池。
- **题库管理**：卡片式展现，支持一键重命名、题型分布统计与独立管理。

### 📚 沉浸式阅读、自动划重点与 ADHD 模式
- **结构化体系讲义**：输入科目与目标，AI 生成多级大纲（支持自由增删调整），逐章流式生成详实讲义，配备 LaTeX 公式与代码高亮；提示词全面去 AI 机械味，结合核心痛点与生活化比喻自然展开；支持断点续写与单章重新生成。
- **课程生成自动划重点**：生成或重生成章节时，AI 自动在元数据中提炼 3–6 处核心定义、黄金法则或避坑要害，生成时**自动划重点高亮**并精确锚定在讲义正文中（无重叠）；新建课程确认页与单章重生成弹窗支持自由勾选，设置页提供全局默认偏好开关。
- **沉浸式双栏阅读**：进入阅读页自动隐藏全局主导航栏，呈现左侧完整目录树（全课程章节列表与当前章小节定位、深浅主题切换、返回首页与课程详情）与右侧正文双栏布局；移动端与窄屏自适应目录浮层。
- **划线多轮研讨与平移避让**：阅读讲义划选文字/公式/代码段，即时唤起对话卡片多轮探讨；卡片支持平滑滑入/滑出动效，展开时正文区域平滑平移避让视线，关闭时平滑复原；划线高亮与对话内容完全持久化存储，重开文档位置不丢。
- **ADHD 辅助阅读模式**：针对长篇高密度文本阅读，提供专为注意力打造的辅助阅读模式：
  - **模式 A（段落交替护眼色块）**：正文各段落应用 6 色柔和护眼调色板并加圆角包裹，段落边界一目了然；
  - **模式 B（悬停动态高亮跟随）**：鼠标移入段落时光标所在段落悬浮高亮、微位移与阴影聚焦；
  - 设置页提供全局偏好设置与微缩预览，阅读页顶部操作栏提供 `🧠 ADHD: 关/A/B` 快捷药丸切换。
- **全书问答与全局检索**：课程页直接面向整门讲义全文检索拼装上下文提问；支持基于 SQLite FTS5 的跨课程毫秒级全文检索与高亮直达。
- **Markdown 笔记导入**：支持导入个人 Markdown 笔记，自动根据标题层级无损切章，支持课程随时重命名。

### 🖥️ 代码运行沙箱与函数绘图
- **多语言隔离沙箱**：内置 Python（`-I -B` 隔离模式，仅标准库）与 C++（系统编译器或便携版）沙箱；Windows Job Object 限制 256MB 内存，10 秒强制限时杀进程树，独立临时目录，历史执行结果全持久化。
- **应用内一键便携安装**：设置页「代码运行环境」自动探测环境；缺 C++ 编译器（GCC 14.2.0）或 Python 时可一键后台静默下载便携版，支持国内镜像择优、断点续传与 SHA-256 哈希校验，不修改系统环境变量与注册表。
- **动态函数绘图**：讲义支持 ` ```plot ` 代码块，每行一个函数表达式，SymPy + Matplotlib 自动绘制高清函数图像，多函数叠加对比与奇点自动断线。

### 📱 局域网访问与 PWA 支持
- **原生设置开关**：遵循最小暴露原则，局域网访问默认保持关闭；在设置页「数据与安全」提供直观平滑的「局域网访问」Switch 开关，按需一键开启并自动生成带有安全令牌的访问地址。
- **安全访问令牌（Token Guard）**：局域网访问自动启用令牌校验保护，避免未经授权的设备访问本地服务与沙箱，静态资源白名单免阻拦。
- **全景 PWA 支持**：配置 Web App Manifest、全尺寸自适应图标与专属 Service Worker，手机、平板或电脑浏览器均可「添加到主屏幕」化身独立轻量应用使用，支持缓存加速与离线降级。

### 📊 掌握度仪表盘与本地备份
- **多维学情追踪**：基于闯关练习真实通过率的知识点掌握度评分（0-100）、近 30 天学习热力图分布、累计阅读时长统计、按场景细分的 Token 消耗看板。
- **纯本地数据主权**：所有学习记录与配置存储于本地 `app.db`（SQLite WAL 模式）与 `courses/`（纯 Markdown 文件）；设置页提供一键打包生成 zip 备份与无损恢复。

### 🎨 桌面端体验与纯净运行
- **Tauri v2 架构**：轻量独立窗口、托盘常驻（左键单击/双击即刻唤起主窗口）、关闭窗口自动最小化；启动时自动清理历史残留注册表项。
- **居中 UpdateDialog 弹窗**：应用启动静默检测新版本，居中弹窗展示版本日志；支持 minisign 验签一键升级与平滑重启；多层防抖与默认系统浏览器安全唤起。
- **纯净打包与防相册泄漏**：四层长效防御（Spec 过滤、构建保底、NSIS 安装器升级自清理）彻底剔除 Matplotlib 示例图片与 GUI 图标，杜绝 Windows 照片应用索引污染相册；保留纯无头 Agg + SVG 矢量绘图。
- **界面统一与防折行细节**：全局统一 5xl 居中容器与滚动条稳定槽位消除页面切换跳动；课程卡片徽标单行防折行；侧栏导航层级激活态统一高亮；深色模式全面适配不透明画布与系统原生控件跟随；NSIS 钩子自动清理残留进程杜绝安装文件锁定。

</details>

---

## 快速开始

### 桌面安装包运行（开箱即用 · 推荐）

1. 从 [Releases](https://github.com/zxxhz/LearnFlow/releases) 下载最新版的 `LearnFlow_x.x.x_x64-setup.exe` 双击安装；
2. 首次启动会自动内置一门「C++ 指针入门」示例课，无需配置即可直接体验阅读、划线、代码沙箱与闯关练习；
3. 进入「设置」配置模型（支持 OpenAI 兼容格式，填入 base_url、API Key 与模型名，点击「测试连接」验证）。页面顶部提供 GLM / DeepSeek / OpenAI / Moonshot / Ollama / Gemini 快捷预设；
4. 支持将生成大纲讲义（generation）与对话伴学助教（chat）分别配置不同模型。

### 源码运行与开发

需具备 Python 3.11+（推荐 [uv](https://docs.astral.sh/uv/) 管理）与 Node 18+：

```bash
# 1. 克隆仓库
git clone https://github.com/zxxhz/LearnFlow.git
cd LearnFlow

# 2. 构建前端产物（输出至 backend/app/static）
cd frontend && npm install && npm run build && cd ..

# 3. 启动后端（自动同步依赖并建库）
cd backend && uv run python -m app.main
```

服务就绪后浏览器访问 `http://127.0.0.1:8420` 即可使用。

#### 本地开发模式（前后端热重载）

```bash
# 终端 1：启动后端开发服务（:8420）
cd backend && uv run uvicorn app.main:app --reload

# 终端 2：启动前端开发服务（:5173，自动代理 /api）
cd frontend && npm run dev
```

---

## 使用指南

### 1. 启发式助教与工具调用

- **呼叫助教**：在闯关练习中提交代码或表达式失败时，关卡卡片底部会自动浮现「💡 呼叫助教启发诊断」及追问输入框；
- **启发引导 vs 直答**：卡片支持自由切换「💡 启发引导」与「📖 详细直答」双模式；
- **查看工具执行**：助教在分析时会动态调用工具（如提交精简用例至沙箱验证、调用 SymPy 画图），前端会以动态卡片实时呈现工具执行过程。

### 2. 题库 Excel 导入与随机刷题

- **导入题库**：点击左侧导航「🎯 题库刷题」➔「导入题库」，选择 `.xls` 或 `.xlsx` 格式的题库表格文件（支持题干、选项 A-H、答案、解析与难度），秒级解析入库；
- **抽题速刷**：在题库卡片点击「开始刷题」，自由选择 10 / 20 / 50 题进行随机组卷，卡片式作答并即时客观判分；
- **错题专项**：做错的题目自动汇总至题库「错题重刷」池，针对薄弱点定向攻坚，重刷通过后自动移出。

### 3. 局域网访问与跨端 PWA

LearnFlow 后端默认仅监听本地回环；若需在同一 Wi-Fi 下使用平板或手机伴学：

1. 打开应用进入「设置」➔「数据与安全」➔ 开启「局域网访问」Switch 开关；
2. 界面会显示局域网访问地址（如 `http://192.168.1.100:8420/?token=...`），点击「复制链接」；
3. 将链接发送至平板（iPad）或手机浏览器打开，即可通过访问令牌鉴权直接使用；
4. **添加到主屏幕**：在 iPad Safari 中点击「分享」➔「添加到主屏幕」，或在 Android Chrome 中点击菜单 ➔「安装应用」，即可享受全屏无地址栏打扰的独立 PWA 体验。

### 4. 代码运行环境与便携工具链

- 讲义与练习中的代码块右上角设有「▶ 运行」按钮：Python 使用内置隔离解释器执行；C++ 调用本机 `g++` / `clang++` 编译执行；
- **一键便携安装**：若本机未安装 C++ 编译器，可在运行报错面板或设置页「代码运行环境」中点击「一键安装」，后台自动静默下载并解压免配置的 niXman MinGW-w64 (GCC 14.2.0) 便携版，不污染系统环境变量与注册表。

---

## 配置说明

所有全局配置均可在应用内「设置」页直观调整，亦可在 `backend/` 下创建 `.env` 文件覆盖：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_HOST` | `0.0.0.0` | 后端监听地址（受安全守卫保护） |
| `APP_PORT` | `8420` | 后端服务端口 |
| `APP_DATA_DIR` | `data` | 数据存储目录（桌面版默认落至 `%APPDATA%\com.learnflow.desktop\`） |
| `APP_OPEN_BROWSER` | `true` | 源码启动时是否自动打开浏览器 |
| `APP_GITHUB_REPO` | `zxxhz/LearnFlow` | GitHub 仓库路径（用于更新检查） |

### 纯本地数据与备份

所有学习数据完全保留在用户本地掌控中：
- `app.db`：SQLite 数据库（WAL 模式），记录课程元数据、作答记录、错题池、对话历史与认知档案；
- `courses/`：纯 Markdown 课程讲义原文（`current.md` 及版本快照），原生适配 Git 版本管控；
- 设置页「数据与安全」提供**一键打包备份**为 zip 压缩包，可随时下载并支持一键恢复。

---

## 技术栈

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/React_18-20232A?style=for-the-badge&logo=react&logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/TailwindCSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" alt="TailwindCSS" />
  <img src="https://img.shields.io/badge/Tauri_v2-24C8DB?style=for-the-badge&logo=tauri&logoColor=white" alt="Tauri" />
</p>

| 模块 | 技术选型 | 关键职责 |
| --- | --- | --- |
| **后端核心** | FastAPI · SQLAlchemy 2.0 (asyncio) · SQLite | 高并发异步接口、WAL 模式高性能存储、FTS5 全文索引 |
| **符号计算与绘图** | SymPy 1.14 · Matplotlib (Agg) | 符号代数等价判题、数学公式解析、高清矢量函数图像绘制 |
| **文件与工具链** | markdown-it-py · xlrd · openpyxl · py7zr | 题库 Excel 秒级解析、便携工具链静默解压 |
| **前端架构** | React 18 · TypeScript · Vite · TailwindCSS | 单页应用架构、组件化响应式布局、深色模式跟随 |
| **状态与通信** | Zustand · TanStack Query · SSE (`fetch-event-source`) | 客户端状态流转、服务端数据缓存、打字机流式推送 |
| **文本与渲染** | markdown-it · KaTeX · Shiki · diff-match-patch | 讲义解析、数学公式排版、双主题代码高亮、划线模糊锚定 |
| **跨端与桌面** | Tauri v2 · Rust · Web App Manifest · Service Worker | 托盘常驻桌面客户端、系统级更新验签、全端 PWA 离线支持 |

---

## 路线图与演进

- [x] 独立题库刷题模块与 Excel 批量导入（v0.3.0）
- [x] 练习系统全面闯关化、链式解锁与从零手写代码（v0.4.0）
- [x] 启发式伴学 Agent：感知诊断、Tool Calling 动态工具链、认知画像、代数等价判题（v0.4.7）
- [x] 原生局域网访问开关与访问令牌安全守卫（v0.4.7）
- [x] 全端 PWA 支持与离线加速（v0.4.9）
- [x] 课程生成自动划重点与可选配置（v0.4.15–v0.4.16）
- [x] ADHD 辅助阅读模式与沉浸式双栏阅读架构（v0.4.17–v0.4.18）
- [x] 划线提问卡片动效与正文平移避让联动（v0.4.18）
- [ ] 向量检索增强长课程宏观提问与答疑（计划中）
- [ ] 题库错题自动关联讲义知识点并由 Agent 深度析因（计划中）

---

## 参与贡献

欢迎通过提交 Issue 或 Pull Request 参与项目建设：

1. **Fork** 本仓库；
2. 创建您的特性分支：`git checkout -b feature/AmazingFeature`；
3. 提交您的修改：`git commit -m 'feat: Add some AmazingFeature'`；
4. 推送至远程分支：`git push origin feature/AmazingFeature`；
5. 发起 **Pull Request**。

若在使用中发现任何问题或有改进建议，欢迎提交 [GitHub Issues](https://github.com/zxxhz/LearnFlow/issues)。

---

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

Copyright © 2026 [LearnFlow Contributors](https://github.com/zxxhz/LearnFlow).
