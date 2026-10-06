---
name: dev-backend-data-isolation
description: 源码后端与桌面端数据目录是两套;启动后端测试必须设 APP_DATA_DIR 隔离
metadata:
  node_type: memory
  type: project
  originSessionId: sess_78f62d42-afb8-4451-afe0-9a3be6e31a9d
---

LearnFlow 存在两套互不相通的数据目录:桌面端安装版由 Tauri main.rs 设 `APP_DATA_DIR=%APPDATA%\com.learnflow.desktop`;源码 `uv run python -m app.main` 不带该变量时落 `backend/data`(config.py 默认)。2026-10-04 诊断「桌面端与浏览器后台对不上」即源于此——用户以为"桌面端后台没更新(没有做题)",实际安装版后端是最新 v0.3.3 且前端含题库 UI,缺的是题库**数据**:题库只导入到了源码后端的 backend/data(测试库 test_bank),桌面端库 0 题库 0 题。backend/data 全是开发/测试残留(7 门冒烟课程 + test_bank 11 题),删除前须先取出 banks/*/original.xlsx 题库原件。

**Why:** 同机 8420 端口只有一个实例能活:桌面端检测到 8420 已占用会直接复用外部后端(main.rs backend_ready),源码后端被占则 uvicorn 直接报错退出;谁先启动谁的数据被看到,两套数据永不合并。

**How to apply:** agent 启动源码后端做开发/测试时一律加 `APP_DATA_DIR=<临时目录>` 隔离,绝不裸跑污染 backend/data、也绝不指向桌面端真实数据;若需联调桌面端数据,先从托盘退出桌面端,再 `APP_DATA_DIR="C:/Users/Emoing/AppData/Roaming/com.learnflow.desktop" uv run python -m app.main`。相关:[[bank-drill-module-plan]]、[[windows-timestamp-monotonic]]
