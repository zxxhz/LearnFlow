---
name: feature-roadmap-prd-alignment
description: LearnFlow 产品决策与版本日志（2026-10-03 头脑风暴 + 2026-10-04 练习闯关化、删费曼/复习、v0.4.0–0.4.4 五连发）——含发版踩坑与前端教训
metadata:
  node_type: memory
  type: project
  originSessionId: sess_0b5c7156-6e49-41b8-bf2c-a8276d5cc84d
---

2026-10-03 对 LearnFlow（[[bank-drill-module-plan]] 同项目，docs/PRD.md 为设计依据）做了新功能头脑风暴并按 PRD 原始设计对照收敛，结论与用户讨论达成的方向：

**砍掉**：Python pip 依赖（Non-goal #3「无任意包安装」红线）、成就徽章、番茄钟（游戏化/专注管理，不在学习闭环）；「课程包分享」须定位为备份/迁移才合规（Non-goal #5 不做分享/市场）。

**PRD 欠账（优先于一切新想法，已核实未实现）**：① ~~FR-5.3「未来 7 天到期负载条形图」~~（随复习模块移除而作废）；② §5.9 M3「SymPy 求解/化简」（math.py 只做了画图 sympify/lambdify）。

**高优先新功能（按真实使用数据排序）**：题库错题接 SRS（bank 模块遗留）、模拟考试、PDF 导入、苏格拉底式阅读、题库错题 LLM 解析、自动定时备份。仪表盘已有使用数据（热力图/阅读时长/Token 用量），先看费曼/题库哪个真的在用再定序。

**LLM 新功能立项闸（源于用户转发另一 AI 的评论「边界+Schema」，已结合项目实情修正）**——每个 LLM 功能立项前答四问：单一角色是什么 / 输入绑定哪些真实数据 / 输出是否可校验 JSON / 判定是否以原文为据。现有 10 个 prompt 场景（prompts/*.md + chat_json Pydantic 校验重试≤2）全部满足；「AI 学习计划」不满足，已收敛为数据派生的「今日待办」（LLM 基本不参与）。

**现存套话风险点（待改）**：评语类 prompt 的「先肯定」设计是泛泛表扬的来源；改法=优点须引用原文具体位置，或漏洞优先、无优点可省略。费曼/复习模块移除后该风险仅剩练习概念题评语（存量题触发）。

**2026-10-04 练习闯关化（已实现）**：用户拍板「不要费曼讲解、不要知识卡片，改成闯关式：给提示 + 要求输出内容，手动写代码」。落地（PRD §5.10 重写 + 附录 note 20 + README 同步）：① 同一知识点内代码关按 order_index 成链，前一关任一次通过才解锁（ever_passed 永久解锁；后端 submit 403 校验）；② 每关 = 任务 + 渐进提示 hints（第 1 条默认给，2–3 条）+ 目标输出常显，**无骨架从零手写**，通关才见 reference_code；③ 练习与 SM-2 复习卡解耦（删 _ensure_wrong_card/_auto_review_passed_card），做错只进错题本；④ exercise_gen.md 重写为全代码关卡链，默认 3 关（原 2），单选/填空/概念题不再生成（存量题作支线保留）；⑤ 随堂小测不受影响仍走骨架题。冒烟新增解锁链路用例全绿；真实渲染走查（浏览器实测通过/失败/提示展开/参考实现）通过。

**2026-10-04 移除费曼/复习模块（v0.4.0 已发布，commit c2e2fab + 6230fcb，Release/安装包/latest.json 均已上线）**：用户拍板「整个费曼讲解和复习模块删掉」。① services/models/schemas/api/prompts（feynman_tutor/eval）与前端 features/feynman、features/review、导航、路由整体删除；② `get_preferences`/`parse_dt`/`local_today`/`local_date_of` 迁至新 `services/prefs.py`（exercise/imports/pipeline/study 引用重定向）；③ 老库迁移要点：SQLite 不允许 DROP 带 FK 约束的列 → 须在 foreign_keys=OFF 的独立连接上「删 feynman 对话+消息 → DROP review_logs/review_cards/feynman_sessions → 重建 conversations 表」（init_db 内实现，新库全幂等跳过）；④ 仪表盘掌握度=练习通过率单信号，遗忘曲线/今日概览/费曼趋势随删；⑤ LLM 场景槽位收敛 generation/chat（SCENES/ScenesConfig/设置页），历史 scenes.feynman 键被 Pydantic 忽略；⑥ 每日复习提醒移除，notify.ts 保留（自动更新失败提示仍用）；⑦ PRD §5.4/§5.5/§10.1/§10.2 留编号标注移除 + 非目标 #8 + 附录 note 21，README 重写。经验：整文件重写 dashboard.py 比逐段改省事；openai_compat 未配置判定要求 api_key+model 双非空，冒烟改场景配置须同步清空，否则泄进后续 400 断言。


**2026-10-04 v0.4.1 安装钩子 + v0.4.2 深色模式修复（均已发布）**：① v0.4.1——桌面壳退出后 learnflow-backend.exe 孤儿进程锁住 backend/_internal 文件，覆盖安装/一键更新报「无法打开要写入的文件」；修法=NSIS `installerHooks`（desktop/src-tauri/installer-hooks.nsh）PREINSTALL/PREUNINSTALL 先 taskkill /F /T 后端与壳进程，真机验证通过。② v0.4.2——深色模式非阅读页右侧发灰的根因：html/body 无背景（UA 画布白），Layout 页面底是半透明 dark:bg-gray-800/50，叠白即灰；阅读页正常是因自绘不透明 dark:bg-gray-900。修法三件套：Layout 底色改 dark:bg-gray-900、index.css 给 html 加不透明背景+color-scheme 跟随（原生控件同步换色）、ui.tsx 的 Input/Textarea 补 bg-white dark:bg-gray-900（此前深色下输入框白底）。教训：**半透明深色底必须有不透明 html 背景兜底；自定义 Input 组件必须带 dark bg**——排查时先 evaluate getComputedStyle 量 html/body/root 三层背景再猜。

**2026-10-04 v0.4.3 更新弹窗（已发布）**：用户反馈「设置页点检查更新不弹横幅」且不要横幅——改为 UpdateDialog 居中弹窗（components/UpdateDialog.tsx，复用 Modal，AutoUpdateButton 从 Layout 迁入）：启动自动检查发现更新 → 弹（sessionStorage 按版本号记「稍后」，同会话不重复弹）；设置页检查有更新 → `learnflow:update-found` CustomEvent 强制弹（修复手动检查结果不驱动 UI 的断点）。无更新行内提示「已是最新版本」。跨组件通信用 window CustomEvent，测试时 evaluate dispatch 同名事件即可注入假数据验证弹窗。

**2026-10-04 v0.4.4 页面布局统一（已发布）**：用户反馈切导航页时标题左右跳——根因有二：① 各页面容器 4 种宽度（max-w-2xl/3xl/4xl/5xl）各自 mx-auto 居中；② 滚动条出现与否让可用宽度差 8px。修法：全部页面容器统一 `max-w-5xl p-8`、h1 统一 text-2xl（含课程详情/题库/搜索/导入/新建），Layout 的 main 加 `[scrollbar-gutter:stable]`；实测六页 h1 x=268 完全一致。教训：**新增页面容器必须抄首页的 max-w-5xl p-8，不要自定宽度**。

**2026-10-04 v0.4.5 课程/题库重命名 + 场景模型折叠（已发布）**：① 课程/题库改名：后端 PATCH `/courses/{id}`（支持 title）与 PATCH `/banks/{id}`（支持 title），前端课程详情页标题旁行内编辑、题库列表卡片弹窗改名；② 设置页「场景模型」高级配置默认折叠收起；③ 发版构建、签名、latest.json 与 GitHub Release 资产上传全流程验证通过。

**2026-10-04 v0.4.6 修复更新弹窗「查看发布页」在桌面端无响应（已发布）**：根因=WebView2 默认拦截/忽略 `target="_blank"` 新窗口导航且未挂载 shell/opener 插件导致超链接点击静默无反应。修法：① 后端新增 `POST /api/system/open-url`（限制仅允许 http/https，标准库 `webbrowser.open` / `os.startfile` 唤起系统浏览器）；② 前端 `updater.ts` 封装 `openExternalUrl`，并在 UpdateDialog「查看发布页」及 Layout 增加桌面壳模式下全局 `target="_blank"` 拦截兜底；③ 冒烟测试增加接口校验与浏览器唤起用例全绿，发版打包构建已上线。

**2026-10-04 Chat 到 Agent 演化全闭环（M1–M4 已全量落地并通过冒烟测试）**：
用户指出「现在还不能称为agent，只是chat」。完成系统性剖析并制定四阶段改造方案（见 brain 方案文档），现已全量交付：
① **M1 伴学感知与启发式诊断**：新增 `prompts/exercise_tutor.md`、`services/tutor.py`、`api/tutor.py`（`/api/tutor/diagnose` SSE 流式输出）；前端 `lib/api.ts` 暴露 `api.tutor.diagnoseSSE`，`ExerciseCard.tsx` 在闯关失败时浮现「💡 呼叫助教启发诊断」及追问输入框；
② **M2 动态工具链 Tool Calling 闭环**：
  - 新增 `services/agent_tools/registry.py`（注册 `run_sandbox_code` 代码沙箱实测、`render_math_plot` SymPy 函数画图、`inspect_exercise` 关卡透视）；
  - 新增 `services/agent_tools/runner.py`（`stream_agent_with_tools` 实现 LLM ↔ 工具执行自主循环）；
  - `services/llm/openai_compat.py` 增强 `chat_raw` 支持 tools，并针对三方中转模型不支持 tools 自动回退纯文本推理降级；
  - 前端实时透传 `tool_call` 事件并在 UI 显示伴学工具执行状态动画（如沙箱执行、函数绘图）；
③ **M3 双模态引导与学习者认知画像持久化**：
  - 新增数据库表 `learner_profiles`（认知背景、先验知识、启发引导偏好）与 `learner_misconceptions`（易错模式、认知漏洞证据、修复状态）；
  - 前端支持「💡 启发」/「📖 直答」双模态自由切换并透传给助教后端；
④ **M4 目标代数等价与多模态练习判定**：
  - 新增 `math` 练习题型（`models/exercise.py`、`schemas/exercise.py`、`services/exercise.py`）；
  - 基于 SymPy `simplify(u - e) == 0` 实现完全客观、确定性的代数等价自动判题（支持乘法交换、幂次变换等）；
  - 前端 `ExerciseCard.tsx` 增加数学题交互卡片、紫色徽标与代数验证响应；
⑤ **冒烟与工程验证**：`smoke_test.py` 扩充代数等价判题、错误表达式拦截、Agent 工具集独立调用、学习者认知模型读写、助教接口防御测试，全套 90+ 项断言全部绿色通过（`结果: 全部通过 ✅`），前端 Vite 打包一次性通过。

**2026-10-04 局域网访问体验优化（v0.4.7）**：
用户反馈「局域网访问（平板）通过命令行 APP_HOST=0.0.0.0 启动不方便，改成设置中的开关且默认 0.0.0.0，并去掉“（平板）”字样」。
① **落地点**：
  - `backend/app/core/config.py`：默认监听 host 改为 `"0.0.0.0"`；
  - `backend/app/services/system.py`：新增持久化文件 `lan_access_enabled.txt`，提供 `is_lan_access_enabled()` 与 `set_lan_access_enabled()`；
  - `backend/app/api/system.py`：新增 `POST /api/system/lan-access?enabled=true/false` 动态启停端点；`access-info` 增加 `lan_enabled` 状态；
  - `backend/app/main.py`：`_AccessGuard` 中间件实时检验 `is_lan_access_enabled()`，关闭时非回环来源直接拦截 403，启动提示去除非必要的“（平板）”限制描述；
  - `frontend/src/features/settings/DataSafetySection.tsx`：标题改为「局域网访问」，右侧新增原生平滑 Switch 开关（默认勾选开启），支持一键点击复制 URL 与令牌，去除了要求命令行配置的文案；
  - `scripts/smoke_test.py`：新增局域网访问默认开启、令牌轮换、动态关闭/开启测试，全量 95+ 项断言全绿通过。
- **发布状态**：已打 Tag `v0.4.7`，Push 至 GitHub，并通过 GitHub Releases API 上传 `LearnFlow_0.4.7_x64-setup.exe` 与 `latest.json`，验证通过。

**2026-10-04 紧急修复（v0.4.8）：题目生成上游Gemini 400报错 + 局域网白屏**：
① **题目生成报错定位与解决**：
  - 原因：调用出题/小测/助教时仅传入了 `[{"role": "system", "content": ...}]`。Gemini 网关（包括用户当前配置的 `gemini-3.8-flash-high`）将 system 映射到 `system_instruction`，因 contents 为空抛出 `INVALID_ARGUMENT: contents is not specified (400)`，被转译为 `LLMServiceError`；
  - 解决：`OpenAICompatAdapter` 全局增加 `_normalize_messages` 自动补齐 user 消息；`exercise_service` / `quiz_service` / `tutor_service` 规范化拆分为 `system` + `user` 提问；在真实用户数据库实测生成关卡 100% 成功。
② **局域网访问白屏定位与解决**：
  - 原因：移动端初次打开 `/?token=...` 时虽拿到 `index.html`，但随后浏览器发起的 `<script src="/assets/index-xxx.js">` 和后续 `/api` 请求无 token 无 Cookie，被 `_AccessGuard` 返回 401 JSON，导致浏览器脚本加载失败而白屏；
  - 解决：`_AccessGuard` 豁免静态打包资产（`/assets/*`、图标）；初次带 token 访问自动在响应注入 `Set-Cookie: lf_token`；前端 `main.tsx` 提取 token 存入 `localStorage`，并在 `api.ts` 和 `sse.ts` 统一附带 `x-access-token` Header；
- **发布状态**：已打 Tag `v0.4.8`，Push 至 GitHub，并通过 GitHub Releases API 发布 `LearnFlow_0.4.8_x64-setup.exe` 与 `latest.json`，验证通过。

**2026-10-04 网页端支持 PWA（v0.4.9）**：
用户需求「给网页加上pwa」。
① **落地点**：
  - `frontend/public/manifest.webmanifest`：配置独立窗口 `standalone`、应用名、主题色 `#2563eb`、图标映射；
  - `frontend/public/icons/`：生成 192/512/maskable/apple-touch-icon 全规格自适应图标与 favicon；
  - `frontend/public/sw.js`：编写 Service Worker，导航请求网络优先/离线回落，静态打包资源缓存优先/异步刷新，API与SSE流式通信强制直通网络；
  - `frontend/index.html`：增加 `<link rel="manifest">`、`<meta name="theme-color">`、Apple Mobile Web App 专属标签；
  - `frontend/src/main.tsx`：浏览器环境下自动注册 Service Worker；
  - `backend/app/main.py`：`_AccessGuard` 放行 PWA 资产，`spa_fallback` 为 `sw.js` 增加 `Service-Worker-Allowed: /` 与 `no-cache` 头；
  - `scripts/smoke_test.py`：增加 PWA 清单、Service Worker 头与图标校验，99 项全绿。
- **发布状态**：已打 Tag `v0.4.9`，Push 至 GitHub，并通过 GitHub Releases API 发布 `LearnFlow_0.4.9_x64-setup.exe` 与 `latest.json`，验证通过。

**2026-10-04 缺陷修复（v0.4.10）：点击查看发布页打开两个浏览器窗口**：
用户反馈「我发现一个bug，点击查看发布页会出来两个」。
① **根因定位**：
  - 更新弹窗 `UpdateDialog.tsx` 的 `<a>` 标签设置了 `onClick` 调用 `openExternalUrl(update.url)`，但未调用 `e.stopPropagation()`，点击事件冒泡至 `document`；
  - 全局布局 `Layout.tsx` 挂载了全局外部链接拦截器（捕获 `target="_blank"` 的 `<a>` 标签唤起系统默认浏览器），由于未判断 `e.defaultPrevented`，全局拦截器二次捕获同一链接并再次调用 `openExternalUrl`；
  - 两次连续请求发往后端 `/api/utils/open-external`，系统连续执行两次 `webbrowser.open()`，导致弹出两个浏览器窗口。
② **落地点与三重防护**：
  - `frontend/src/components/UpdateDialog.tsx`：在 `onClick` 中增加 `e.stopPropagation()`，彻底切断事件向上冒泡；
  - `frontend/src/components/Layout.tsx`：全局监听器开头增加 `if (e.defaultPrevented) return;` 保护，凡已被子组件接管处理的事件全局不再二次响应；
  - `frontend/src/lib/updater.ts`：底层 `openExternalUrl` 增加 1 秒内相同 URL 的防抖去重机制，杜绝并发调用与用户手速过快双击。
- **发布状态**：版本号三处同步 bump 至 `0.4.10`，全量 99 项测试全绿，已打 Tag `v0.4.10`，Push 至 GitHub，并通过 GitHub Releases API 上传 `LearnFlow_0.4.10_x64-setup.exe` 与 `latest.json`，验证通过。

**2026-10-04 体验与托盘优化：托盘左键唤起窗口、去开机自启、徽标单行防折行**：
用户需求「优化一下，改成左键单击托盘图标是显示窗口，然后去掉开机自启。比如标题是“C++现代化文本与字符串处理实战：从Python思维平滑过渡 可学习”，这个可学习会变成两行，改成一行的」。
① **托盘图标与自启清理**：
  - `desktop/src-tauri/src/main.rs`：`show_menu_on_left_click(false)`，监听 `TrayIconEvent::Click`（`button: Left, state: Up`）与 `DoubleClick`，左键单击/双击直接执行 `show_main` 唤起并置顶主窗口；
  - 移除托盘菜单中的 `autostart` 开机自启项（菜单仅保留「显示窗口」与「退出」）；并在 setup 启动时执行 `handle.autolaunch().disable()`，静默清除旧版本遗留在 Windows 注册表中的开机启动项；
② **课程卡片徽标单行防折行**：
  - `frontend/src/components/ui.tsx`：全局 `Badge` 原语加上 `inline-flex shrink-0 items-center whitespace-nowrap`，从根源杜绝所有徽标（可学习、草稿、生成中等）被父级挤压换行；
  - `frontend/src/features/home/HomePage.tsx` 与 `DashboardPage.tsx`：课程标题外层加入 `min-w-0 flex-1 break-words` 与 `gap-3`，即使是长标题也不会压迫右侧徽标，「可学习」始终平稳保持单行。
- **发布状态**：版本号三处同步 bump 至 `0.4.11`，全量 99 项测试全绿，已打 Tag `v0.4.11`，Push 至 GitHub，并通过 GitHub Releases API 上传 `LearnFlow_0.4.11_x64-setup.exe` 与 `latest.json`，验证通过。

**2026-10-04 安全策略调整：局域网访问改成默认关闭**：
用户需求「局域网访问改成默认关闭」。
① **落地点**：
  - `backend/app/services/system.py`：`is_lan_access_enabled()` 默认值改为 `False`，只有当存在配置标记文件且内容显式为 `"1"` 时才允许非回环设备访问；
  - `backend/app/main.py`：服务启动时根据 `is_lan_access_enabled()` 动态展示终端信息，默认关闭状态下打印安全提示与设置页开启引导；
  - `frontend/src/features/settings/DataSafetySection.tsx`：Switch 开关 fallback 默认值改为 `false`；
  - `backend/scripts/smoke_test.py`：冒烟测试断言调整为初始默认关闭，随后测试动态开启、生成令牌与再次关闭，全量 99 项测试全绿。
- **发布状态**：版本号三处同步 bump 至 `0.4.12`，全量 99 项测试全绿，已打 Tag `v0.4.12`，Push 至 GitHub，并通过 GitHub Releases API 上传 `LearnFlow_0.4.12_x64-setup.exe` 与 `latest.json`，验证通过。

**2026-10-04 侧边栏导航选中态统一 + 提示词教学表现力优化（v0.4.13 已发布）**：
用户反馈「当我点击左边的首页的时候，首页的按钮是会变灰的，但是当我点击里面的具体课程的时候却不会，但是这个课程还是在首页里面的，所以应该要统一样式」。
① **侧边栏导航选中态统一**：
  - `frontend/src/components/Layout.tsx`：`NavLinks` 引入 `useLocation`，将进入课程详情（`/courses/*`）、章节阅读（`/read/*`）、新建课程（`/courses/new`）及导入（`/import`）均判定为归属于「首页（我的课程）」的激活状态，保持全局层级高亮连贯；并补充 `dark:text-brand-300` 提升深色对比度。
② **去 AI 味与提示词教学表现力升级**：
  - 全面优化 `outline.md`、`chapter_doc.md`、`exercise_gen.md`、`exercise_tutor.md` 等核心提示词，杜绝冒号拼接副标题与机械套模板，强化痛点引入与生活化生动比喻。
③ **发布状态**：版本号三处同步 bump 至 `0.4.13`，构建 PyInstaller 独立后端与 Tauri NSIS 安装包并签名，生成 `latest.json`，打 Tag `v0.4.13` 推送并完成 GitHub Release 资产上线，验证通过。

**2026-10-05 剔除 Matplotlib 示例图片入 Windows 相册防护（v0.4.14 已发布）**：
用户反馈「项目的图片会出现在 windows 的图片中」（Grace Hopper 肖像 `grace_hopper.jpg`、logo2.png 等示例媒体被 Windows 照片应用索引）。
① **构建产物即时清理**：彻底清除了 desktop target 与 backend dist 中 matplotlib 自带的 `sample_data` 与 `images`。
② **四层长效防御构建**：
  - `backend/learnflow_backend.spec`：Analysis 阶段显式过滤 `a.datas` 中属于 matplotlib 的 `sample_data` 与 `mpl-data/images`。
  - `backend/scripts/build_backend.py`：构建结束执行 `prune_matplotlib_sample_images` 保底清理。
  - `desktop/src-tauri/installer-hooks.nsh`：`NSIS_HOOK_POSTINSTALL` 钩子增加自清理指令，老用户升级/覆盖安装时自动消除旧版残留。
  - 保留纯无头 Agg + SVG 函数绘图能力，全量冒烟测试 100% 通过。
③ **发布状态**：版本号三处同步 bump 至 `0.4.14`，构建 PyInstaller 独立后端与 Tauri NSIS 安装包并签名，生成 `latest.json`，打 Tag `v0.4.14` 推送并完成 GitHub Release 资产（exe + latest.json）上线，验证通过。

**2026-10-05 课程生成自动划重点 + 标注抽屉优化（v0.4.15 已发布）**：
用户需求「在阅读时，高亮会出现在标注中，右边会出来一个“本文标注（1）”，括号中的数字会随着标注数量递增。但是要去掉这个，只保留“本文标注”。而且“本文标注”关不掉，右上角没有关闭的按钮，请你补上。bump。然后有一个feature是在生成课程时自动划重点」。
① **生成课程自动划重点闭环**：
  - `backend/app/prompts/chapter_doc.md`：在 `<LEARNFLOW_META>` 中新增 `highlights` 契约规范，引导模型在生成章节时一字不差摘录核心定义、黄金法则或避坑要害（3-6 处）；
  - `backend/app/services/generation/knowledge.py`：`ChapterMeta` 模型补充 `highlights: list[HighlightItem] = []`；
  - `backend/app/services/generation/highlight.py`：新增自动划重点服务，提取与浏览器 DOM `textContent` 100% 对齐的纯文本，精确锚定五元组（`section_id`、`exact`、`prefix`、`suffix`、`start_offset`、`end_offset`），杜绝同节内重叠，支持加粗/避坑语句智能兜底；自动创建关联 `Conversation`，并支持重新生成章节时自动清理无对话残留；
  - `backend/app/services/generation/pipeline.py`：在 `run_chapter` 流程中落盘后调用 `create_auto_highlights`。
② **阅读标注抽屉优化**：
  - `frontend/src/features/reader/AnnotationsDrawer.tsx`：抽屉标题移除动态数量 `（数字）`，纯保留「本文标注」；右上角补齐 `✕` 关闭按钮；卡片支持重点分类（核心定义/避坑要害等）徽标展示；
  - `frontend/src/features/reader/ReaderPage.tsx`：抽屉绑定 `onClose={() => setDrawerOpen(false)}`。
③ **冒烟测试与发版**：
  - `smoke_test.py` 扩充自动划重点落库回显、五元组字段及对话绑定测试，全套 100+ 项断言全部绿色通过（`结果: 全部通过 ✅`）；
  - 版本号三处同步 bump 至 `0.4.15`，构建 PyInstaller 独立后端与 Tauri NSIS 安装包并签名，生成 `latest.json`，打 Tag `v0.4.15` 推送并完成 GitHub Release 资产（exe + latest.json）上线，验证通过。



**2026-10-05 课程生成/重生成自动划重点可选配置（v0.4.16 已发布）**：
- 支持在新建课程大纲确认弹窗及重新生成章节弹窗中勾选「自动划重点」；
- 设置页增加全局「生成时自动划重点」偏好开关，默认开启；
- 版本号三处同步 bump 至 `0.4.16`。

**2026-10-05 ADHD 阅读辅助模式（v0.4.17）**：
用户需求「在设置中加两个【ADHD模式】可选A/B（下拉框，关闭，A，B），A为开启此模式后文章内的每一段使用不同的背景颜色（在这一段的周围，使用圆角），B为开启后鼠标移到那一段的区域就给那一段显示某一个颜色的背景，切换时需要有流程的动效」。
① **设置项与数据持久化**：
  - `backend/app/schemas/settings.py`：`Preferences` 增加 `adhd_mode: Literal["off", "a", "b"] = "off"`，向后兼容默认回退 `"off"`；
  - `backend/app/models/settings.py` 与 `api/settings.py`：默认偏好字典补充 `"adhd_mode": "off"`；
  - `frontend/src/features/settings/SettingsPage.tsx`：学习偏好区域添加 ADHD 模式下拉选择器（关闭 / 模式 A / 模式 B）与即时微缩预览卡片。
② **阅读器模式 A / 模式 B 渲染与动效**：
  - `frontend/src/styles/index.css`：`.adhd-para` 定义 12px 圆角及 `transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1)`；6 色循环护眼柔和调色板（支持深色模式低饱和度自适应）；`.adhd-mode-b:hover` 悬停聚焦高亮、微位移与阴影；
  - `frontend/src/features/reader/BlockView.tsx`：正文各段落（`<p>`）根据 `pIndex` 动态挂载交替底色或悬停聚焦类，标题与代码块保持原生排版；
  - `frontend/src/features/reader/ReaderPage.tsx`：为正文段落生成序号；顶部操作栏增设 `🧠 ADHD: 关/A/B` 快捷药丸切换按钮。
③ **发布状态**：版本号三处同步 bump 至 `0.4.17`。

**2026-10-05 划线提问卡片动效与正文平移避让联动（v0.4.18 已发布）**：
- 划线唤起提问卡片时，卡片由右往左平滑滑入；
- 桌面端阅读正文容器同步向左平移避让（`md:mr-[420px]`，300ms ease-out），避免遮挡文字与公式；
- 关闭提问卡片时卡片平滑滑出，正文平滑向右复位全宽；
- 版本号三处同步 bump 至 `0.4.18`。

**2026-10-05 目录固定独立滚动 + 侧栏折叠展开动效（v0.4.19 已发布）**：
- **目录固定独立滚动**：重构双栏架构，左侧大纲树固定在视口左侧独立滚动，不随右侧正文滚动而位移；
- **侧栏折叠展开动效**：增加折叠按钮与全局快捷键 <kbd>Ctrl</kbd> + <kbd>B</kbd>（Mac: <kbd>Cmd</kbd> + <kbd>B</kbd>），支持平滑左滑折叠隐藏与右滑展开，正文容器平滑铺满/复原，折叠状态记住至 LocalStorage；
- 版本号三处同步 bump 至 `0.4.19`。

**2026-10-06 检查更新自动无缝回退国内镜像通道（v0.4.20 已发布）**：
- 在 `UpdateDialog` 与检查更新服务中，若 GitHub 官方源（`api.github.com`）连接超时或被墙，自动无缝切换到备用国内镜像加速通道（`ghproxy / fastgit`）；
- 确保国内网络环境下客户端升级无感可用；
- 版本号三处同步 bump 至 `0.4.20`。

**2026-10-06 右侧全部面板动效与避让联动 + 划线提问 0ms 乐观显示与流式打字机（v0.4.21 已发布）**：
- **右侧全部面板动效与正文自适应避让**：全面将「🎮 闯关练习抽屉」、「🖍 本文标注抽屉」、「💡 知识点抽屉」以及划线提问卡片纳入统一动效与避让体系；打开任意右侧面板时，面板从右滑入，正文自适应平移避让；关闭时平滑复位；
- **划线提问 0ms 乐观显示与现代流式打字机**：修复提问输入后不显示的 Bug，点击发送 0ms 立即在卡片内渲染用户问题气泡与思考动画；底层升级为现代原生 `ReadableStream` 逐块解码，结合后端无缓冲响应头，呈现毫秒级流式打字机输出；
- 版本号三处同步 bump 至 `0.4.21`。

**2026-10-06 刷题模块错题 AI 流式解答与题库提示词自定义/一键润色（v0.4.22 已发布）**：
- **错题 AI 深度流式解答**：答题卡片判错时提供「🤖 获取 AI 深度解析」，原生 SSE 毫秒级流式打字机输出错因诊断、核心考点、逐项辨析与举一反三；支持 Markdown 排版与 KaTeX 数学公式动态渲染；支持一键重新生成；
- **题库级提示词自由配置 + 启发式名师提示词兜底**：`question_banks` 表新增 `ai_prompt` 字段并自动热迁移；未设置或留空时自动回退内置黄金名师提示词 `DEFAULT_BANK_AI_PROMPT`；列表页与模式选择页均提供入口与状态指示；
- **AI 润色提示词原地无缝替换**：提示词弹窗内置「✨ AI 润色提示词」按钮，调用大模型对当前提示词进行结构化规范优化，并在当前页面 Textarea 内原地替换内容，无需关闭重开即可直接保存；
- 版本号三处同步 bump 至 `0.4.22`。

**2026-10-06 修复查看小结选项显示与错题 AI 解析保留持久化（v0.4.23 已发布）**：
- **修复查看小结选项显示异常**：重构轮末错题列表的选项渲染逻辑，引入统一的 `visibleOptions(question)` 解析器，完美支持单选、多选（A~H 映射与空项过滤）与判断题（补齐 A 正确 / B 错误），精准高亮用户的作答（错选红底）与标准答案（绿底）；
- **错题 AI 深度解析全流程保留与数据库持久化**：
  - `bank_questions` 表扩展 `ai_explanation` 字段，流式解答完毕后自动写入持久化数据库；
  - 轮中作答生成的 AI 解析即刻同步写入本地草稿（`aiExplains`）与上下文；
  - 点击「查看小结」时，已生成过 AI 解析的错题**默认自动展开**并标明「已保留」，无需重新请求与二次消耗 Token；
  - 支持随时收起、0ms 瞬时秒开查看，或在卡片内一键「↻ 重新生成」刷新解析；
- 版本号三处同步 bump 至 `0.4.23`。


**2026-10-06 ADHD 辅助阅读模式全块级覆盖与视觉内衬优化（v0.4.24 已发布）**：
- **全内容块类型支持（消除“重点段落无背景色”死角）**：
  - 将 ADHD 卡片生效范围从单一纯段落（`paragraph`）全面拓展至所有正文内容块（Content Blocks：`paragraph` 普通段落、`list` 知识点与步骤列表、`quote` 核心重点与避坑引用块、`table` 表格、`math` 公式块）；
  - 仅跳过结构大标题（`heading`，保留清晰层级）与代码沙箱容器（`code`，保留自带深色终端与交互功能），彻底解决章节知识点、核心提醒等高价值重点段落因属于 `list` 或 `quote` 而遗漏着色的排版断层；
- **精细化 CSS 间距与卡片内衬**：
  - 重置卡片内列表（`ul`/`ol`）、引用块（`blockquote`）的外边距，确保圆角内衬均匀工整；
  - 引用块（`blockquote`）内部底色设为透明，让 ADHD 轮换背景色（模式 A）或悬停聚焦色（模式 B）自然透出，同时保留左侧重点竖条装饰；
- **组件属性补齐**：通用 `Badge` 组件支持接收 `title` 浮动提示属性；
- 版本号三处同步 bump 至 `0.4.24`。

**2026-10-07 课程与刷题独立字号调节、跨版本更新日志聚合及下载源测速智能路由（v0.4.25 已发布）**：
- **课程与刷题独立字号调节**：
  - 课程阅读页（`ReaderPage`）顶栏增加微型紧凑字号步进调节器（`[ A- ] 16px [ A+ ]`），范围 13px–24px，默认 16px；
  - 题库刷题页（`BankDrillPage`）在作答、错题小结与模式选择顶栏常驻独立字号调节器，默认 15px；
  - 两处字号互不干扰，满足长文细读与高强度刷题的不同视觉需求；
- **即时持久化与设置页联动**：
  - LocalStorage 零延迟即时缓存，页面加载无字体跳变，并静默持久化至服务端 `Preferences.course_font_size` 与 `drill_font_size`；
  - 设置页「学习偏好」新增课程与刷题字号配置项及双卡片微缩实时预览，支持一键点击数字重置默认；
- **数学公式与全元素相对等比缩放**：
  - CSS 排版规则升级：大纲标题（`h1`~`h4`）、正文（`p`）、列表（`ul`/`ol`）、表格（`table`）及代码块（`code-block`/`code-cell`）全面采用相对 `em` 规则；
  - KaTeX 数学公式（行内 `$ ... $` 与独立块 `$$ ... $$`）依赖外层字号，根号、分式、下标上标完美等比自适应缩放；
  - 题库题目题干与选项增加 KaTeX 自动识别渲染并支持字号缩放；
- **检测更新速度与下载源智能路由**：
  - **并发测速服务**：`download_mirrors.py` 支持并发探测 GitHub 官方直连与国内各大主流加速镜像（GH-Proxy, GHFast, GHProxy, Moeyy 等），测量实时毫秒延迟；
  - **自动择优与手动锁定**：支持「🚀 自动择优（哪个快用哪个）」与手动指定特定镜像，彻底解决更新下载慢或超时问题；
  - **Tauri Updater 极速更新直链注入**：`/update/fast-latest.json` 自动将安装包下载链接替换为最优镜像直链，实现桌面端客户端一键满速更新；
  - **设置页卡片**：`DownloadMirrorsSection` 提供「⚡ 立即测速」、延迟数值与状态徽章展示；
- **更新检测跨版本日志聚合与过滤展示**：
  - **跨版本自动拼接**：检测到更新时拉取 Releases 列表，筛选出处于 `(current, latest]` 区间内的所有有效版本并降序排列（最新版本在上）；若跨越多个小版本（例如从 0.0.1 升级到 0.0.4），自动将 0.0.4、0.0.3、0.0.2 的更新日志按 Markdown `---` 分割线优雅拼接；
  - **空版本与未发布跳过**：若中间某版本未发布或日志为空，自动智能跳过，杜绝多余空内容或占位符；
  - **弹窗 Markdown 排版**：`UpdateDialog.tsx` 通过 `MarkdownLite` 渲染富文本更新日志，并设最大高度内嵌滚动条，同时顶部显示生效的加速源徽章与「⚡ 极速下载安装包」直链；
- 版本号三处同步 bump 至 `0.4.25`。
- **2026-10-08 紧急修复 Tauri v2 Updater 端点协议强约束致桌面闪退（v0.4.26 已发布）**：
  - **根本原因**：Tauri v2 的 `tauri-plugin-updater` 在反序列化配置时，对所有 `endpoints` 强制校验必须采用 `https://` 协议，遇 `http://` 直接触发 Rust 致命 Panic，由于 Release 采用无控制台 GUI 子系统，表现为毫秒级闪退无任何报错；
  - **修复措施**：剔除 `desktop/src-tauri/tauri.conf.json` 中配置的本地 `http://` 端点，恢复合规的 GitHub Releases 与 HTTPS 国内加速镜像，极速更新下载仍由 UpdateDialog 「⚡ 极速下载安装包」直接走后端智能优选链路；
  - **版本更新**：版本号三处同步 bump 至 `0.4.26`，完成全量打包、签名与 GitHub Release 发布。
- **2026-10-08 优化更新弹窗下载链路与修复手动下载源锁定交互（v0.4.27 已发布）**：
  - **更新弹窗双通道与视觉防呆**：
    - 明确区分「⬇ 一键自动更新」（应用内全自动静默下载并重启）与「⚡ 浏览器极速下载」（调用系统默认浏览器通过当前最优加速镜像直链拉取安装包进行手动覆盖）；
    - 修复 Windows 下通过系统接口唤起默认浏览器下载的问题（改用 `cmd.exe /c start` 穿透子进程环境），并在点击时触发即时 Toast 提示，彻底解决“点击无反应”与意图混淆的问题；
  - **修复下载源「手动指定源」锁定交互**：
    - 修复由于 `status.selected_id` 初始为 `"auto"` 导致前端 `isAuto` 计算恒为 true、单选框无法切至手动的逻辑缺陷；
    - 优化后端 `set_mirror_selection` 容错，未传或误传 auto 时自动继承当前最快节点 ID；
    - 卡片交互升级：任何模式下直接点击镜像卡片或「锁定此源」按钮，均可立即无缝切换至手动锁定模式并生效该镜像；
  - **版本更新**：版本号三处同步 bump 至 `0.4.27`，完成全量打包、签名与 GitHub Release 发布。
- **2026-10-09 ADHD 辅助阅读模式升级 12 色柔和调色板（v0.4.28 待发布）**：
  - **12 色柔和护眼循环调色板**：
    - 调色板从 6 色扩展为 12 种柔和马卡龙色系（天空蓝、薄荷翠绿、暖琥珀金、薰衣草紫、浅玫瑰粉、水鸭青绿、蜜桃暖橙、靛蓝紫罗兰、青柠嫩绿、洋红莓果、冰晶天青、暖奶杏沙）；
    - 模式 A（多色段落交替）循环周期扩展至 12，相邻色彩温差交替，消除长文阅读时的单调感与串行疲劳；
  - **色彩辨识度与层次感调优**：
    - 浅色模式背景与边框微调至 0.80 / 0.75，文字对比度与卡片边缘更清晰；深色模式微调至 0.32 / 0.35，柔和不刺眼；
  - **设置页预览与文案联动**：
    - 设置页增加第 3 段预览示例，完整展示多色流水轮换与悬停微光动效；说明文案同步更新为 12 种柔和护眼底色；
  - **版本更新**：版本号三处同步 bump 至 `0.4.28`，完成全量构建、签名与 GitHub Release 发布。
- **2026-10-09 学习者画像与因材施教认知档案全链路闭环（v0.4.29）**：
  - **核心模型与服务**：激活闲置的 `LearnerProfile` 与 `LearnerMisconception` 表，实现 `format_profile_for_prompt` 与异步提炼服务 `evolve_profile_from_interaction`；
  - **RESTful API**：支持画像获取、修改、盲区移除及一键重置（`GET/PUT/DELETE /api/study/profile*`）；
  - **全链路 Prompt 注入**：大纲设计、教材章节撰写、划线问答、助教伴学及题库错题 AI 原地解析 5 大链路全覆盖；
  - **异步无感动态演进**：划线问答、助教诊断与错题解析完成后，后台协程自动提炼并沉淀用户背景与认知漏洞；
  - **前端设置页管理面板**：新增「🧑‍🎓 学习者画像与认知档案」卡片，背景描述可视化可编辑、教学模式单选切换、盲区标签移除与一键重置；
  - **版本更新**：版本号三处同步 bump 至 `0.4.29`。
