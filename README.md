<div align="center">

# LearnFlow

本地运行的 AI 学习助手

[![Release][release-shield]][release-url]
[![Stars][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]

[下载安装包](https://github.com/zxxhz/LearnFlow/releases) · [产品设计文档](docs/PRD.md) · [反馈问题](https://github.com/zxxhz/LearnFlow/issues)

</div>

输入想学的科目（C++、高等数学之类），AI 先出大纲再逐章生成讲义；阅读时划线即可提问，也可以用自己的话把知识点讲给 AI 听（费曼式），讲得不牢的地方会自动变成复习卡，由 SM-2 算法安排每天复习。

自己的 Markdown 笔记也能导入，按标题拆章、原文不改写。`demos/` 下有两门示范课程（Python / C++ 基础语法），不配 LLM 也能导入体验代码运行；全新安装首次启动还会自动内置一节「C++ 指针入门」示例课，阅读 / 练习 / 复习 / 沙箱都能直接玩。

<details>
<summary>目录</summary>

- [功能](#功能)
- [安装](#安装)
- [平板 / 局域网访问](#平板--局域网访问)
- [代码运行沙箱](#代码运行沙箱)
- [数据与备份](#数据与备份)
- [桌面版（Tauri）](#桌面版tauri)
- [路线图](#路线图)
- [技术栈](#技术栈)

</details>

## 功能

- 输入学习目标，AI 生成大纲（可手动改），再逐章生成讲义，带 LaTeX 公式和代码高亮；断了能续，单章能重生成
- 划线提问：阅读时划选任意内容，弹出卡片跟 AI 多轮对话，划线和对话都持久化，重开文档还在原位
- 费曼讲解：AI 扮演学生追问，讲完给评分和漏洞清单，漏洞能跳回原文、一键生成复习卡
- 复习队列：知识点、划线、漏洞自动成卡，SM-2 调度每日复习，四档自评，带统计和连击；每日到期数可桌面通知提醒
- 练习系统：按知识点出题（代码补全 / 单选 / 填空 / 概念简答），代码题真实运行对比 stdout 自动判定，概念题 AI 按参考答案评分给评语；做错的题自动进复习队列和错题本，做对自动过卡；还能跨知识点组卷「随堂小测」出分
- 错题本：最近一次做错的题集中一页，重练通过后对应复习卡自动按「记得」过一遍
- 问整门课：课程页直接向全课程提问（章节摘要 + 全文检索拼上下文，SSE 流式回答）
- 全局搜索：跨课程全文检索（FTS5），命中片段高亮，直达阅读位置
- 代码运行：` ```python ` / ` ```cpp ` 块一键运行（限时 10 秒、限内存 256MB、进程树隔离），结果跟着文档存；缺编译器可一键装便携版（装在软件目录不动系统，下载自动择优直连/镜像、断点续传、SHA-256 校验）
- 函数图像：` ```plot ` 块画图（SymPy + Matplotlib），多函数叠加、奇点自动断线
- 仪表盘：课程进度、薄弱知识点（掌握度 0-100 = 复习间隔 / 费曼评分 / 练习通过率三信号合成）、遗忘曲线（按间隔留存率）、学习热力图、阅读时长、Token 用量（近 30 天分场景）
- 导出：整课导出 Markdown / 静态 HTML（公式可渲染、打印即 PDF），复习卡导出 Anki CSV
- 生成 / 答疑 / 费曼三个场景可各配一个模型，比如生成用便宜模型、费曼批改用强模型；支持 Ollama 本地模型（一键检测已装模型并填入）
- 深色模式：侧栏一键切换、跟随系统记忆，代码高亮 / 公式 / 划线高亮全部适配
- `APP_HOST=0.0.0.0` 启动后平板浏览器可直接访问（响应式已适配；自动启用访问令牌，非本机来源必须携带）

## 安装

从 [Releases](https://github.com/zxxhz/LearnFlow/releases) 下载 `LearnFlow_x.x.x_x64-setup.exe` 双击安装。Python 环境和全部依赖都打在包里，不用装；运行文档里的 C++ 代码块需要 g++——没装的话应用内可以一键安装便携版（见[代码运行沙箱](#代码运行沙箱)），也可以自己装 [MinGW-w64](https://www.mingw-w64.org/)。

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

控制台会打印局域网地址（自带访问令牌，如 `http://192.168.x.x:8420/?token=…`），平板连同一个 Wi-Fi 就能访问，界面已适配触屏和窄屏。

`0.0.0.0` 模式自动启用访问令牌保护：非本机来源的所有请求必须携带 token（地址里的 `?token=…` 或 `X-Access-Token` 头均可），本机和桌面版不受影响。设置页「数据与安全」可查看带 token 的完整地址、随时重新生成令牌（旧地址立即失效）。不在同一网络的话，[Tailscale](https://tailscale.com/) 最省事：两台设备登同一账号，访问 `http://100.x.x.x:8420`；有公网服务器也可以用 frp / cloudflared 转发。

注意 0.0.0.0 会把服务（包括代码沙箱）暴露给所在网络，令牌只挡未授权访问，别把端口直接映射到公网。

## 代码运行沙箱

代码块右上角有「▶ 运行」按钮：

- Python 不用额外配置：源码运行用当前解释器，安装包版用随包内置的独立 Python（`-I` 隔离模式，仅标准库）
- C++ 需要本机有 g++ 或 clang++：系统 PATH 里有就直接用；没有时点运行结果里的「⬇ 一键安装」或设置页「代码运行环境」装便携版
- 限制：单次 10 秒（超时杀整个进程树）、内存 256MB（Windows Job Object）、进程数上限、stdin 关闭、每次运行用一次性临时目录，全局串行执行
- 运行结果（stdout / stderr / 退出码 / 耗时）持久化，重开文档还能看到上一次的输出

### 一键安装运行环境

设置页「代码运行环境」能看到 Python / C++ 的检测结果（内置 / 系统 / 应用内 / 未安装 + 版本），缺什么点「安装」：

- **C++**：niXman mingw-builds 便携版（GCC 14.2.0，UCRT，7z 约 92MB），解压到软件安装目录的 `toolchains/mingw64/`
- **Python**：python.org embeddable 便携版（3.12.10，约 11MB，仅标准库），解压到 `toolchains/python/`
- 不写系统 PATH、不写注册表、不弹安装器——删掉 `toolchains/` 目录就是卸载；应用安装目录只读时（如装进 Program Files）自动落到数据目录
- 下载源自动择优：GitHub 直连不通（国内常见）自动走 ghproxy 系镜像；Python 包走 python.org → 华为云 → npmmirror；下载支持断点续传，产物做 SHA-256 校验（不符自动清缓存换源重下）
- 安装在后台进行，进度条实时显示；装完再点「▶ 运行」即可，无需重启

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

- `app.db` — SQLite（WAL 模式）：标注、对话、复习记录、练习作答、代码执行记录、Token 用量
- `courses/` — 课程文档，纯 Markdown（`current.md` + `versions/`），可以直接进 git

备份就是复制这个目录。设置页「数据与安全」还能一键打包备份（`app.db` + `courses/` 存到 `data/backups/`）、查看 / 恢复 / 删除备份——恢复在重启应用后生效。整课内容也可以在课程页导出成 Markdown / HTML，复习卡可导出 Anki CSV。

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

### 应用内自动更新

桌面版内置更新器（`tauri-plugin-updater`）：打开应用时静默检查新版本，横幅上「⬇ 一键更新」下载安装包（带进度）→ 校验 minisign 签名 → 静默安装 → 自动重启；浏览器 / 局域网模式回退「查看发布页」链接。

发版时的额外步骤（在 `npx tauri build` 之前）：

```bash
# 签名私钥不入库（desktop/src-tauri/keys/），丢失将无法签名更新，需换公钥重发一版手动安装
export TAURI_SIGNING_PRIVATE_KEY="$(pwd)/src-tauri/keys/learnflow.key"
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
npx tauri build   # 产出 exe 与同名 .sig
```

构建后按 `.sig` 内容手工生成 `latest.json`（`version` / `pub_date` / `platforms.windows-x86_64.{signature, url}`），与安装包一同上传 GitHub Release——更新器端点固定读 `releases/latest/download/latest.json`，少了它自动更新会静默回退到发布页链接。

## 路线图

- [ ] 语音讲解费曼
- [ ] 向量检索增强长课程答疑

更多想法欢迎提 [Issue](https://github.com/zxxhz/LearnFlow/issues)，PR 也欢迎。

## 技术栈

FastAPI + SQLAlchemy 2.0 (async) + SQLite（FTS5 全文检索），React 18 + TS + Vite + TailwindCSS（深色模式）。markdown-it 前后端同规则解析，KaTeX 公式，Shiki 双主题高亮，diff-match-patch 做划线模糊锚定，SSE 流式输出，LLM 走 OpenAI 兼容协议。

<!-- shields -->
[release-shield]: https://img.shields.io/github/v/release/zxxhz/LearnFlow?style=for-the-badge
[stars-shield]: https://img.shields.io/github/stars/zxxhz/LearnFlow?style=for-the-badge
[issues-shield]: https://img.shields.io/github/issues/zxxhz/LearnFlow?style=for-the-badge
[release-url]: https://github.com/zxxhz/LearnFlow/releases
[stars-url]: https://github.com/zxxhz/LearnFlow/stargazers
[issues-url]: https://github.com/zxxhz/LearnFlow/issues
