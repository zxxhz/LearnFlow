<div align="center">

# LearnFlow

本地运行的 AI 伴学与个人知识库工具

[![Release][release-shield]][release-url]
[![Stars][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]

[下载安装包](https://github.com/zxxhz/LearnFlow/releases) · [产品设计文档](docs/PRD.md) · [反馈问题](https://github.com/zxxhz/LearnFlow/issues)

</div>

输入想学的科目（如 C++ 进阶、离散数学、网络安全），AI 生成大纲并逐章撰写讲义。也可以导入自己的 Markdown 笔记或题库表格。阅读时可随时划线提问，做题卡关时有带工具调用（代码沙箱实测、函数绘图）的伴学助教启发提示；另外内置了独立思维导图画布、多题型刷题、代码手写闯关与因材施教的学习者认知画像。

所有数据完全存放在本地，支持接入各大兼容 OpenAI 协议的模型（DeepSeek、智谱、Moonshot、OpenAI、Gemini 等）或本地部署的 Ollama。

<details>
<summary>目录</summary>

- [核心功能](#核心功能)
  - [1. 课程生成与讲义阅读](#1-课程生成与讲义阅读)
  - [2. 知识点代码闯关与数学判题](#2-知识点代码闯关与数学判题)
  - [3. 伴学 Agent 与启发式助教](#3-伴学-agent-与启发式助教)
  - [4. 题库刷题模块](#4-题库刷题模块)
  - [5. 思维导图与知识图谱](#5-思维导图与知识图谱)
  - [6. 学习者画像与因材施教](#6-学习者画像与因材施教)
  - [7. 代码与函数绘图沙箱](#7-代码与函数绘图沙箱)
- [安装与运行](#安装与运行)
- [局域网访问与 PWA](#局域网访问与-pwa)
- [客户端内置更新与镜像加速](#客户端内置更新与镜像加速)
- [数据存储与备份](#数据存储与备份)
- [路线图](#路线图)
- [技术栈](#技术栈)

</details>

## 核心功能

### 1. 课程生成与讲义阅读
- **大纲生成与单章控制**：输入目标生成大纲树，支持手动调整章节顺序与标题；逐章异步流式生成讲义，支持中途断点续传与单章独立重生成。
- **自有笔记导入**：支持直接导入外部 Markdown 笔记，自动根据标题层级拆解章节，原文完整保留不擅自改写。
- **自动划重点**：生成讲义时可选由模型自动提取核心定义与避坑要害（3~6 处），浏览器 DOM 精确对齐高亮并关联独立标注卡片。
- **划线提问与正文平移动效**：划选任意文本即刻弹出提问卡片与 AI 对话，右侧面板展开时正文平滑向左自适应避让，关闭后自动复位；高亮与对话持久化存储。
- **ADHD 辅助阅读模式**：
  - 模式 A：12 种柔和马卡龙护眼色在正文段落、列表、引用块间循环交替，降低长文视觉疲劳；
  - 模式 B：鼠标悬停聚焦段落高亮并带微位移反馈。
- **独立字号调节**：课程与刷题支持独立 13px–24px 步进微调，正文文字、代码块与 KaTeX 数学公式（`$...$` 与 `$$...$$`）采用 `em` 相对比例等比自适应缩放。
- **侧边栏折叠与独立滚动**：支持快捷键 <kbd>Ctrl</kbd> + <kbd>B</kbd>（Mac 下 <kbd>Cmd</kbd> + <kbd>B</kbd>）收起左侧大纲树，正文独立展开全宽；左侧目录树独立滚动，不随右侧正文滚出视口。

### 2. 知识点代码闯关与数学判题
- **代码闯关链**：每个知识点生成全代码闯关任务，无骨架从零手写代码，前一关通过才解锁下一关；支持渐进式提示（默认给思路提示，卡关可逐级展开），全部通关后才展示参考实现。
- **数学代数等价判题**：针对公式与数学题，基于 SymPy `simplify(u - e) == 0` 进行代数等价性自动判题，自动识别乘法交换律、幂次展开与化简表达式。
- **全屏交互抽屉**：闯关抽屉支持「⤢ 全屏」展开，在宽屏居中视野下编写代码与查看输出，支持与课程正文字号联动调节。
- **错题本**：闯关未通过的任务自动沉淀至独立错题本，方便后续针对性重练。

### 3. 伴学 Agent 与启发式助教
- **双模态引导**：做题受阻时可呼叫助教，支持「💡 启发引导」（苏格拉底式反问、指出思路偏差、不直接给答案）与「📖 直答解析」两种模式自由切换。
- **Tool Calling 动态工具链**：助教集成自主工具调用闭环，可自主调用后端沙箱执行代码验证结果（`run_sandbox_code`）、动态绘制函数图像辅助几何理解（`render_math_plot`）或透视当前关卡状态（`inspect_exercise`），前端实时透传工具执行状态。

### 4. 题库刷题模块
- **表格题库导入**：支持导入 `.xlsx` / `.xls` 格式的题库表格（单选、多选、判断等题型），题干与选项完整支持 Markdown 与 KaTeX 数学公式。
- **做新题与模考模式**：
  - 做新题模式：只抽从未作答过的题目，攻坚刷穿全库，做一题少一题，看板实时统计未做新题数；
  - 做题模式：全库随机抽题模拟自测；
  - 同套题内容严格指纹去重，杜绝单轮内出现雷同题。
- **错题 AI 流式深度解答**：答错时一键唤起 AI 深度解析，包含错因诊断、核心考点、逐项辨析与举一反三；解析结果自动落库持久化，进入小结页或重刷时 0ms 秒开展示，无需重复消耗 Token。
- **题库级专属提示词**：每个题库可单独配置答疑与命题专属 Prompt（留空自动使用内置启发式名师提示词），支持在配置弹窗内点击「AI 润色提示词」一键原地优化。

### 5. 思维导图与知识图谱
- **自研原生渲染画布**：基于 React + SVG 贝塞尔曲线开发的层级树渲染引擎，无需重型第三方依赖；支持鼠标滚轮自由缩放（0.3x~2.5x）、画布平移拖拽、全屏居中与分支节点折叠/展开。
- **AI 画像生成与双向导入导出**：支持根据用户学习背景一键生成多级导图；支持 Markdown 大纲或 JSON 格式的双向导入与导出。
- **Agent 自然语言交互式控图**：侧边悬浮面板支持自然语言指令交互（如“在 XX 节点下拆解 3 个关键子项”、“删掉废弃分支”），由 Agent 通过结构化工具实时操作内存树并同步画布。
- **节点详情抽屉与专属知识问答**：点击任意节点平滑滑出详情抽屉，展示面包屑路径；支持调用 AI 一键深度剖析底层原理、直观类比与易混淆盲区，支持围绕当前节点的上下文多轮追问。

### 6. 学习者画像与因材施教
- **认知画像持久化**：建立 `LearnerProfile`（技术背景、先验知识栈、引导偏好）与 `LearnerMisconception`（易错模式、高频概念盲区、掌握状态）。
- **全链路 Prompt 注入**：大纲设计、章节教材撰写、划线问答、伴学助教诊断及错题解析 5 大关键链路均自动注入当前画像上下文。
- **异步后台自动演进**：在划线问答、助教诊断与错题解析完成后，系统后台异步提炼用户的思维盲区并持续演进认知档案；设置页支持可视化查看、手动修改背景与一键重置。

### 7. 代码与函数绘图沙箱
- **力扣式代码块编辑与执行**：讲义内的 ` ```python ` 与 ` ```cpp ` 代码块右上角带有运行按钮，支持在正文中直接修改代码并运行测试，支持重开回显历史结果与一键重置回初始代码。
- **执行安全隔离**：单次运行限时 10 秒（超时自动终止进程树）、内存上限 256MB（Windows Job Object）、stdin 关闭、一次性临时工作目录；Python 使用随包内置隔离环境，C++ 依赖本机 g++/clang++。
- **高数函数图像绘制**：` ```plot ` 代码块一键解析函数表达式并渲染高清矢量 SVG 图像，支持多函数同图对比与奇点自动断线（如 `sin(x)/x`）。

## 安装与运行

### 方式一：下载安装包（推荐，开箱即用）
从 [Releases](https://github.com/zxxhz/LearnFlow/releases) 下载 `LearnFlow_x.x.x_x64-setup.exe` 安装运行。
- 安装包已内置 Python 运行环境与核心依赖，**电脑无需安装 Python 或 Node.js**；
- 只有运行文档里的 C++ 代码块需要本机装有 `g++`（如 [MinGW-w64](https://www.mingw-w64.org/)）并加入环境变量 PATH。

### 方式二：从源码运行
依赖环境：Python 3.11+（使用 [uv](https://docs.astral.sh/uv/) 管理）与 Node.js 18+（构建前端）：

```bash
# 1. 构建前端（产物输出至 backend/app/static）
cd frontend && npm install && npm run build && cd ..

# 2. 启动服务（首次会自动 uv sync 安装依赖并初始化数据库）
cd backend && uv run python -m app.main
```

启动后浏览器会自动打开 `http://127.0.0.1:8420`。

### 模型配置
打开客户端「设置」页配置大语言模型：
- 协议：标准 OpenAI 兼容协议（填写 Base URL、API Key 与模型名称，支持一键点击「测试连接」）；
- 顶部预设：内置智谱 GLM、DeepSeek、OpenAI、Moonshot、Ollama、Gemini 等一键配置预设；
- 场景分工：支持为「通用生成」与「对话问答」单独指定不同模型（例如生成大纲用高吞吐量模型，伴学诊断用强推理模型）；
- 完全离线运行：本机安装 [Ollama](https://ollama.com/) 并拉取模型（如 `ollama pull qwen2.5:7b`），设置中选择「Ollama 本地」预设即可无外网完全离线运行。

### 桌面开发与打包（Tauri）
`desktop/` 目录下提供基于 Tauri 的轻量级桌面外壳（支持独立窗口、系统托盘常驻与生命周期管理）：

```bash
# 1. 打包后端独立可执行文件
cd backend && uv sync && uv run python scripts/build_backend.py

# 2. 桌面客户端调试与构建
cd desktop
npm install
npx tauri dev     # 开发调试模式
npx tauri build   # 构建 Windows NSIS 安装包（产物位于 src-tauri/target/release/bundle/）
```

## 局域网访问与 PWA

- **局域网访问**：在设置页「局域网访问」中直接开启开关，控制台与设置页均会展示本机局域网访问链接及安全访问令牌（Token）；平板或手机连入同一 Wi-Fi 后即可在浏览器中使用。
- **PWA 桌面化体验**：移动端或平板浏览器访问局域网地址时，可点击浏览器菜单「添加到主屏幕」或「安装应用」，获得全屏无边框的独立 Native 体验，离线资源由内置 Service Worker 自动托管。
- **远程访问**：在异地网络下建议配合 [Tailscale](https://tailscale.com/) 使用（两端登录同账号，通过 Tailscale 分配的 IP 访问即可享受端到端加密），无需开放公网端口。

## 客户端内置更新与镜像加速

客户端启动时会自动静默检测 GitHub Releases，发现新版本会在设置页和弹窗中提示：
- **全链路镜像测速与智能路由**：内置国内各大主流 GitHub 加速镜像并发测速模块（GH-Proxy, GHFast, Moeyy 等），支持「🚀 自动择优（哪个快用哪个）」或手动指定锁定镜像；
- **自定义加速源**：支持用户在设置中添加自己的私有加速源，并支持原地编辑与测速；
- **一键极速更新**：在更新弹窗中点击「一键自动更新」，系统通过当前最优加速节点流式拉取安装包，实时展示下载进度与网络测速，下载完毕后平滑唤起安装程序。

## 数据存储与备份

应用数据完全存储于本地，开箱自包含：
- **源码模式**：所有数据存放于 `backend/data/` 目录；
- **打包安装版**：数据存放于系统应用数据目录（Windows 下为 `%APPDATA%\com.learnflow.desktop\`）；
- **核心文件**：
  - `app.db`：SQLite 数据库（采用 WAL 模式），包含所有课程结构、高亮标注、对话历史、闯关记录、题库题目与作答、思维导图树以及学习者画像；
  - `courses/`：课程正文与版本历史，采用纯 Markdown 文件保存，便于使用 Git 或外部工具检索；
  - 设置页提供「打开数据目录」按钮，直接备份该目录即可完成完整数据迁移。

## 路线图

- [ ] PDF 格式教材/讲义自动解析与切章导入
- [ ] 题库全真模拟考试与限时交卷模式
- [ ] 知识图谱跨课程全局概念关联网络

欢迎在 [Issues](https://github.com/zxxhz/LearnFlow/issues) 提出使用反馈与功能建议。

## 技术栈

- **后端**：Python 3.11+ / FastAPI / SQLAlchemy 2.0 (Async) / SQLite (WAL) / SymPy (代数化简与等价判题) / Matplotlib (无头矢量 SVG 绘图) / PyInstaller
- **前端**：React 18 / TypeScript / Vite / TailwindCSS / Lucide Icons
- **解析与排版**：markdown-it / KaTeX / Shiki 代码高亮 / diff-match-patch (划线模糊容错重锚定)
- **桌面与移动端**：Tauri v2 (Rust) / NSIS / PWA (Service Worker + Web App Manifest)
- **AI 架构**：OpenAI 兼容协议客户端 / Server-Sent Events (SSE) 毫秒级打字机流式输出 / Agent Tool Calling 闭环

<!-- shields -->
[release-shield]: https://img.shields.io/github/v/release/zxxhz/LearnFlow?style=for-the-badge
[stars-shield]: https://img.shields.io/github/stars/zxxhz/LearnFlow?style=for-the-badge
[issues-shield]: https://img.shields.io/github/issues/zxxhz/LearnFlow?style=for-the-badge
[release-url]: https://github.com/zxxhz/LearnFlow/releases
[stars-url]: https://github.com/zxxhz/LearnFlow/stargazers
[issues-url]: https://github.com/zxxhz/LearnFlow/issues
