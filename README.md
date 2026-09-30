# LearnFlow · 学习 Agent

个人本地使用的 AI 学习助手：输入想学的课程（C++、高等数学等）→ AI 生成大纲并逐章生成学习文档 → 阅读中划线提问（卡片对话持久化）→ 费曼讲解暴露漏洞 → SM-2/艾宾浩斯复习队列。

完整产品需求见 [docs/PRD.md](docs/PRD.md)。

## 功能（M1+M2）

- **课程生成**：学习目标 → AI 大纲（可编辑）→ 逐章生成文档（LaTeX 公式 / 代码高亮），断点续生成、单章重新生成
- **划线提问**：阅读时划选任意内容 → 弹出卡片与 AI 多轮对话，标注与对话全部持久化，四色高亮、模糊重锚定、orphan 重新挂载
- **费曼学习**：用自己的话讲解知识点，AI 扮演学生追问，给出评分与漏洞清单，漏洞可跳转原文、一键生成复习卡
- **复习系统**：知识点/划线/漏洞自动成卡，SM-2 调度每日复习队列，四档自评，统计与连击
- **代码运行**：文档内 Python/C++ 代码块一键运行（限时 10s、限内存 256MB、进程树隔离），结果与文档位置绑定持久化
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

**第一步**：进入「设置」页配置 LLM（OpenAI 兼容协议，填 base_url + API Key + 模型名，支持智谱 GLM / DeepSeek / OpenAI 等），点「测试连接」确认。

### 开发模式

```bash
cd backend && uv run uvicorn app.main:app --reload   # 后端 :8420
cd frontend && npm run dev                            # 前端 :5173，/api 自动代理
```

## 数据与备份

所有数据在 `backend/data/`（自包含）：

- `app.db` — SQLite（WAL 模式）：标注、对话、复习记录、代码执行记录等
- `courses/` — 课程文档正文，纯 Markdown（`current.md` + `versions/`），可用 git 管理

复制整个 `data/` 目录即完成备份；「设置」页可一键打开该目录。

## 代码运行沙箱

文档中标注 ` ```python ` 或 ` ```cpp ` 的代码块右上角有「▶ 运行」按钮：

- **Python**：开箱即用（使用当前解释器，`-I` 隔离模式 + UTF-8）
- **C++**：需要本机安装 g++ 或 clang++（如 [MinGW-w64](https://www.mingw-w64.org/)）并加入 PATH；未安装时会给出友好提示
- 安全限制：单次运行限时 10 秒（超时杀进程树）、内存上限 256MB（Windows Job Object）、进程数上限、stdin 关闭、工作目录一次性临时目录；全局串行执行
- 结果（stdout/stderr/退出码/耗时）持久化保存，重新打开文档仍显示最近一次结果

## 技术栈

FastAPI + SQLAlchemy 2.0 (async) + SQLite ｜ React 18 + TS + Vite + TailwindCSS ｜ markdown-it（前后端同规则块解析）｜ KaTeX ｜ Shiki ｜ diff-match-patch（划线模糊锚定）｜ SSE 流式 ｜ OpenAI 兼容 LLM 适配层

## 分支与提交

主分支 `main`，按模块提交（地基 / 后端生成链路 / 后端复习费曼 / 前端各模块 / 集成），见 `git log`。
