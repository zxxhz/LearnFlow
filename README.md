# LearnFlow · 学习 Agent

个人本地使用的 AI 学习助手：输入想学的课程（C++、高等数学等）→ AI 生成大纲并逐章生成学习文档 → 阅读中划线提问（卡片对话持久化）→ 费曼讲解暴露漏洞 → SM-2/艾宾浩斯复习队列。

完整产品需求见 [docs/PRD.md](docs/PRD.md)。

## 功能（M1+M2）

- **导入自有文档**：上传自己的 .md 笔记，自动按标题层级识别章节结构（可编辑确认），原文精确保留不改写，归档原件并提取知识点进入复习循环
- **课程生成**：学习目标 → AI 大纲（可编辑）→ 逐章生成文档（LaTeX 公式 / 代码高亮），断点续生成、单章重新生成
- **划线提问**：阅读时划选任意内容 → 弹出卡片与 AI 多轮对话，标注与对话全部持久化，四色高亮、模糊重锚定、orphan 重新挂载
- **费曼学习**：用自己的话讲解知识点，AI 扮演学生追问，给出评分与漏洞清单，漏洞可跳转原文、一键生成复习卡
- **复习系统**：知识点/划线/漏洞自动成卡，SM-2 调度每日复习队列，四档自评，统计与连击
- **代码运行**：文档内 Python/C++ 代码块一键运行（限时 10s、限内存 256MB、进程树隔离），结果与文档位置绑定持久化
- **高数图形化**：` ```plot ` 代码块一键绘制函数图像（SymPy + Matplotlib，支持多函数与奇点断线，如 `sin(x)/x`）
- **场景化模型**：生成 / 答疑 / 费曼 三个场景可分别指定模型（留空用主配置），如便宜模型做生成、强模型做费曼评价
- **平板访问**：`APP_HOST=0.0.0.0` 启动后平板浏览器直接访问（响应式已适配），支持内网穿透远程使用
- **仪表盘**：课程进度、薄弱知识点榜、学习热力图

## 运行

依赖：Python 3.11+（[uv](https://docs.astral.sh/uv/)）、Node 18+（仅构建前端时需要）。

```bash
# 1. 构建前端（产物输出到 backend/app/static；仓库若已带 static 可跳过）
cd frontend && npm install && npm run build && cd ..

# 2. 启动（首次自动 uv sync 安装后端依赖、建库）
cd backend && uv run python -m app.main
```

启动后自动打开浏览器访问 `http://127.0.0.1:8420`。

**第一步**：进入「设置」页配置 LLM（OpenAI 兼容协议，填 base_url + API Key + 模型名），点「测试连接」确认。顶部有智谱 GLM / DeepSeek / OpenAI / Moonshot / **Ollama 本地** 快捷预设。

**本地 Ollama**：安装 [Ollama](https://ollama.com/) 后 `ollama pull qwen2.5:7b`，设置页点「Ollama 本地」预设（base_url `http://localhost:11434/v1`，API Key 随意填如 `ollama`）即可完全离线使用。三个场景槽位（生成/答疑/费曼）可分别指定不同模型，留空用主配置。

### 开发模式

```bash
cd backend && uv run uvicorn app.main:app --reload   # 后端 :8420
cd frontend && npm run dev                            # 前端 :5173，/api 自动代理
```

### 桌面应用（Tauri 壳）

独立窗口 + 系统托盘常驻 + 开机自启开关；壳负责拉起/回收本地后端，关窗即最小化到托盘。

```bash
# 前置：Rust 工具链（rustup，MSVC stable）
cd desktop
npm install
npx tauri dev     # 开发调试
npx tauri build   # 产出安装包（NSIS，位于 src-tauri/target/release/bundle/）
```

壳按以下顺序定位后端目录：环境变量 `LEARNFLOW_BACKEND_DIR` → 从 exe 向上查找含 `backend/app` 的目录。端口默认 8420，可用 `LEARNFLOW_PORT` 覆盖。若 8420 已有服务在跑，壳会直接复用而不重复拉起。

## 数据与备份

所有数据在 `backend/data/`（自包含）：

- `app.db` — SQLite（WAL 模式）：标注、对话、复习记录、代码执行记录等
- `courses/` — 课程文档正文，纯 Markdown（`current.md` + `versions/`），可用 git 管理

复制整个 `data/` 目录即完成备份；「设置」页可一键打开该目录。

## 平板 / 局域网访问

```bash
cd backend && APP_HOST=0.0.0.0 uv run python -m app.main
```

启动时会在控制台打印局域网地址（如 `http://192.168.x.x:8420`），平板与电脑连同一 Wi-Fi 即可访问。界面已做响应式（侧栏抽屉、目录浮层、触屏划线选择）。

**跨网络访问（内网穿透）**——推荐方案：

1. **Tailscale（推荐，零配置）**：电脑与平板都装 Tailscale 并登录同一账号，平板访问电脑的 Tailscale IP（`http://100.x.x.x:8420`），流量端到端加密，无需公网 IP。
2. **frp / cloudflared**：有公网服务器时用 frp 转发 8420 端口；无服务器可用 cloudflared tunnel。**务必加访问认证**（如 cloudflare access / frp token）。

⚠️ 安全提示：`0.0.0.0` 会把服务（含代码运行沙箱）暴露给所在网络，API Key 明文存于本机——只在可信私网（家庭 Wi-Fi / Tailscale）开启，不要直接暴露公网。

## 代码运行沙箱

文档中标注 ` ```python ` 或 ` ```cpp ` 的代码块右上角有「▶ 运行」按钮：

- **Python**：开箱即用（使用当前解释器，`-I` 隔离模式 + UTF-8）
- **C++**：需要本机安装 g++ 或 clang++（如 [MinGW-w64](https://www.mingw-w64.org/)）并加入 PATH；未安装时会给出友好提示
- 安全限制：单次运行限时 10 秒（超时杀进程树）、内存上限 256MB（Windows Job Object）、进程数上限、stdin 关闭、工作目录一次性临时目录；全局串行执行
- 结果（stdout/stderr/退出码/耗时）持久化保存，重新打开文档仍显示最近一次结果

### 高数图形化

文档中 ` ```plot ` 代码块出现「📐 绘图」按钮，每行一个函数（`sin(x)/x` 或 `f(x)=x**2`），后端用 SymPy 解析、Matplotlib 渲染 SVG，支持多函数对比、奇点自动断线、默认区间 [-10, 10]：

````md
```plot
sin(x)/x
f2(x)=x**2/8
```
````

## 技术栈

FastAPI + SQLAlchemy 2.0 (async) + SQLite ｜ React 18 + TS + Vite + TailwindCSS ｜ markdown-it（前后端同规则块解析）｜ KaTeX ｜ Shiki ｜ diff-match-patch（划线模糊锚定）｜ SSE 流式 ｜ OpenAI 兼容 LLM 适配层

## 分支与提交

主分支 `main`，按模块提交（地基 / 后端生成链路 / 后端复习费曼 / 前端各模块 / 集成），见 `git log`。
