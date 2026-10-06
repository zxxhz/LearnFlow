---
name: release-process
description: LearnFlow 发版全流程（v0.3.2 起含自动更新签名）——版本 bump 三处、双构建、latest.json、API 发布
metadata:
  node_type: memory
  type: project
  originSessionId: sess_0b5c7156-6e49-41b8-bf2c-a8276d5cc84d
---

LearnFlow 发版步骤（gh CLI 未安装，用 git credential 里的 PAT 走 GitHub API）：

1. 版本号三处同步 bump：`backend/app/core/config.py APP_VERSION`、`desktop/src-tauri/tauri.conf.json`、`desktop/package.json`
2. `cd frontend && npm run build`（产物进 backend/app/static）→ `cd backend && uv run python scripts/build_backend.py`（PyInstaller → backend/dist/learnflow-backend）
3. `cd desktop && export TAURI_SIGNING_PRIVATE_KEY="<仓库>/desktop/src-tauri/keys/learnflow.key" && export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="" && npx tauri build` → NSIS exe + 同名 .sig（私钥 gitignored，无密码；**丢失则无法签名更新，须换公钥重发一版手动安装**）
4. 按 .sig 内容手工生成 `latest.json`（version/pub_date/platforms.windows-x86_64.{signature,url}）——Tauri v2 不会自动生成
5. 提交+打 tag（vX.Y.Z）+ push main 和 tag
6. GitHub API 发布：`git credential fill` 取 PAT → POST /repos/zxxhz/LearnFlow/releases → 上传 exe + latest.json 两个资产；发布说明中文 markdown
7. 验证：`curl -sL github.com/zxxhz/LearnFlow/releases/latest/download/latest.json`

自动更新链路：应用横幅「⬇ 一键更新」→ tauri-plugin-updater（端点 latest/download/latest.json，版本与 tauri.conf 比对）→ 签名校验 → NSIS 静默装 → relaunch。浏览器/局域网模式回退发布页链接。capability 需 `remote.urls` 放行 http://127.0.0.1:* 才能让 :8420 页面调插件。关联 [[windows-timestamp-monotonic]]。

**v0.4.1 起（2026-10-04）**：NSIS 安装器带 `installerHooks`（desktop/src-tauri/installer-hooks.nsh），PREINSTALL/PREUNINSTALL 先 `taskkill /F /T` learnflow-backend.exe 与 LearnFlow.exe——桌面壳退出后后端孤儿进程会锁住 backend/_internal 文件，不杀会导致覆盖安装/一键更新报「无法打开要写入的文件」（0.4.0 实测踩中）。POSTINSTALL 自动清理旧版残留的 `matplotlib/mpl-data/{sample_data,images}`（防止 Grace Hopper 示例图泄漏入 Windows 相册，详见 [[matplotlib-sample-images-leak]]）。GitHub 直连下载在本网络时好时坏：latest.json 等小文件 curl 可拉，大文件走 API（带 PAT、Accept: application/octet-stream）更稳；上传资产用 urllib POST uploads.github.com。发版时若本地裸跑过后端 exe，注意它默认落 backend/data（安装目录）——桌面壳正常总是设 APP_DATA_DIR 指向 %APPDATA%\com.learnflow.desktop，两处数据互不相干。

