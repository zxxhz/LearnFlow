---
name: windows-timestamp-monotonic
description: Windows time.time() 粒度 ~15.6ms 导致 created_at 平局、排序不确定的坑与 utcnow_iso
  单调修复（2026-10-03）
metadata:
  node_type: memory
  type: project
  originSessionId: sess_0b5c7156-6e49-41b8-bf2c-a8276d5cc84d
---

学习agent（LearnFlow）踩坑记录：Windows 上 `datetime.now()` 依赖的 `time.time()` 粒度约 15.6ms，快速连续写入（无沙箱的毫秒级请求）会拿到**完全相同**的 created_at，任何"按 created_at 取最新一条"的窗口函数排序（错题本 row_number、最新作答回显）在平局时结果随机——表现为 smoke 5 轮挂 2 轮的 flaky。

**修复**：`backend/app/models/base.py utcnow_iso()` 进程内严格单调（撞车 +1µs），并固定 `isoformat(timespec="microseconds")`（整秒时 isoformat 会省略小数，字符串长度不一破坏字典序）。新增"按时间取最新"查询时不要再依赖 created_at 唯一性。

**排查教训**：① smoke_test.py 末尾会通过 API 删除自己种的数据（课程级联清零），跑完查库是空的不是数据丢失；② `APP_DATA_DIR` 生效（pydantic-settings env_prefix=APP_），隔离跑用 `APP_DATA_DIR=data-smoke APP_PORT=8431 PYTHONPATH=. uv run python scripts/smoke_test.py`，跑完目录会被服务端建出、数据行被末尾清理，属正常。关联 [[bank-drill-module-plan]]。
