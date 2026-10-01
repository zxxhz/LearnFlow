# LearnFlow

本地运行的 AI 学习助手。输入想学的科目（C++、高等数学之类），AI 先出大纲再逐章生成讲义；阅读时划线即可提问，也可以用自己的话把知识点讲给 AI 听（费曼式），讲得不牢的地方会自动变成复习卡，由 SM-2 算法安排每天复习。

自己的 Markdown 笔记也能导入，按标题拆章、原文不改写。`demos/` 下有两门示范课程（Python / C++ 基础语法），不配 LLM 也能导入体验代码运行。完整产品设计见 [docs/PRD.md](docs/PRD.md)。

## 功能

- 输入学习目标，AI 生成大纲（可手动改），再逐章生成讲义，带 LaTeX 公式和代码高亮；断了能续，单章能重生成
- 划线提问：阅读时划选任意内容，弹出卡片跟 AI 多轮对话，划线和对话都持久化，重开文档还在原位
- 费曼讲解：AI 扮演学生追问，讲完给评分和漏洞清单，漏洞能跳回原文、一键生成复习卡
- 复习队列：知识点、划线、漏洞自动成卡，SM-2 调度每日复习，四档自评，带统计和连击
- 代码运行：` ```python ` / ` ```cpp ` 块一键运行（限时 10 秒、限内存 256MB、进程树隔离），结果跟着文档存
- 函数图像：` ```plot ` 块画图（SymPy + Matplotlib），多函数叠加、奇点自动断线
- 生成 / 答疑 / 费曼三个场景可各配一个模型，比如生成用便宜模型、费曼批改用强模型
- 仪表盘：课程进度、薄弱知识点、学习热力图
- `APP_HOST=0.0.0.0` 启动后平板浏览器可直接访问（响应式已适配）

## 安装

从 [Releases](https://github.com/zxxhz/LearnFlow/releases) 下载 `LearnFlow_x.x.x_x64-setup.exe` 双击安装。Python 环境和全部依赖都打在包里，不用装；只有运行文档里的 C++ 代码块需要本机有 g++。

从源码跑需要 Python 3.11+（[uv](https://docs.astral.sh/uv/) 管理）和 Node 18+（只为构建前端）：

```bash
# 构建前端，产物输出到 backend/app/static（仓库自带 static 时可跳过）
cd frontend && npm install && npm run build && cd ..

# 启动后端，首次会自动 uv sync 装依赖、建库
cd backend && uv run python -m app.main
```

浏览器会自动打开 `http://127.0.0.1:8420`。先去设置页配模型（OpenAI 兼容协议，填 base_url + API Key + 模型名，点「测试连接」验证），顶部有智谱 GLM / DeepSeek / OpenAI / Moonshot / Ollama 快捷预设。

想完全离线：装 [Ollama](https://ollama.com/)，`ollama pull qwen2.5:7b`，设置页选「Ollama 本地」预设（base_url `http://localhost:11434/v1`，API Key 随便填）。

### 开发模式

```bash
cd backend && uv run uvicorn app.main:app --reload   # 后端 :8420
cd frontend && npm run dev                           # 前端 :5173，/api 自动代理
```

## 平板 / 局域网访问

```bash
cd backend && APP_HOST=0.0.0.0 uv run python -m app.main
```

控制台会打印局域网地址（如 `http://192.168.x.x:8420`），平板连同一个 Wi-Fi 就能访问，界面已适配触屏和窄屏。不在同一网络的话，[Tailscale](https://tailscale.com/) 最省事：两台设备登同一账号，访问 `http://100.x.x.x:8420`；有公网服务器也可以用 frp / cloudflared 转发，但访问认证要自己加。

注意 `0.0.0.0` 会把服务（包括代码沙箱）暴露给所在网络，API Key 是明文存在本机的，别直接暴露公网。

## 代码运行沙箱

代码块右上角有「▶ 运行」按钮：

- Python 不用额外配置：源码运行用当前解释器，安装包版用随包内置的独立 Python（`-I` 隔离模式，仅标准库）
- C++ 需要本机装 g++ 或 clang++（如 [MinGW-w64](https://www.mingw-w64.org/)）并加入 PATH，没装会有提示
- 限制：单次 10 秒（超时杀整个进程树）、内存 256MB（Windows Job Object）、进程数上限、stdin 关闭、每次运行用一次性临时目录，全局串行执行
- 运行结果（stdout / stderr / 退出码 / 耗时）持久化，重开文档还能看到上一次的输出

### 函数图像

` ```plot ` 代码块右上角是「📐 绘图」，每行一个函数（`sin(x)/x` 或 `f2(x)=x**2/8`），默认区间 [-10, 10]：

````md
```plot
sin(x)/x
f2(x)=x**2/8
```
````

## 数据与备份

所有数据都在 `backend/data/`：

- `app.db` — SQLite（WAL 模式）：标注、对话、复习记录、代码执行记录
- `courses/` — 课程文档，纯 Markdown（`current.md` + `versions/`），可以直接进 git

备份就是复制这个目录，设置页里有按钮一键打开。

## 桌面版（Tauri）

`desktop/` 下是 Tauri 壳：独立窗口、托盘常驻、开机自启开关，壳负责拉起和回收本地后端，关窗即最小化到托盘。打包版后端用 PyInstaller 打成独立 exe 随安装包分发（目标机器不需要 Python / uv）：

```bash
# 前置：Rust 工具链（rustup，MSVC stable）
cd backend && uv sync && uv run python scripts/build_backend.py   # → backend/dist/learnflow-backend/
cd desktop && npm install
npx tauri dev     # 开发调试，debug 构建走 uv 流程，不依赖打包产物
npx tauri build   # 产出 NSIS 安装包，位于 src-tauri/target/release/bundle/
```

后端定位逻辑：开发版依次找环境变量 `LEARNFLOW_BACKEND_DIR` → 从 exe 向上找含 `backend/app` 的目录，用 `uv run python -m app.main` 拉起；打包版直接拉起安装目录里的 `backend/learnflow-backend.exe`，数据写在系统应用数据目录。端口默认 8420，可用 `LEARNFLOW_PORT` 覆盖；8420 已有服务在跑就直接复用，不重复拉起。联调打包后端用 `LEARNFLOW_BACKEND_EXE` 指向 exe。

> 国内网络提示：`tauri build` 首次会从 GitHub 下载 NSIS 工具链到 `%LOCALAPPDATA%/tauri/`，超时的话用镜像（如 `https://ghproxy.net/https://github.com/<原路径>`）手动下载 `nsis-3.11.zip` 解压成 `tauri/NSIS/`，`nsis_tauri_utils.dll` 放进 `tauri/NSIS/Plugins/x86-unicode/`（sha1 应为 75197FEE…，与 cli 二进制内嵌哈希一致）后重试。

## 发新版本

应用启动时会静默查一次 GitHub Releases，有新版就在顶部横幅提示（设置页可手动检查、可配仓库）。发布步骤：

1. 同步版本号：`backend/app/core/config.py` 的 `APP_VERSION`、`backend/pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/tauri.conf.json` 的 `version`（Cargo.toml 构建时自动同步）
2. `cd backend && uv run python scripts/build_backend.py` 打包后端，再 `cd desktop && npx tauri build` 出安装包
3. GitHub 建 Release：tag 用 `v<版本号>`，更新说明写在 Release body（横幅只放链接）
4. 检查走 GitHub API 未认证请求，超时 5 秒、失败静默、间隔 1 小时；仓库用 `APP_GITHUB_REPO=owner/repo`（`.env`）或在设置页填

## 技术栈

FastAPI + SQLAlchemy 2.0 (async) + SQLite，React 18 + TS + Vite + TailwindCSS。markdown-it 前后端同规则解析，KaTeX 公式，Shiki 高亮，diff-match-patch 做划线模糊锚定，SSE 流式输出，LLM 走 OpenAI 兼容协议。
