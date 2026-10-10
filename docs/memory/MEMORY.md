# Memory Index

- [题库刷题模块](bank-drill-module-plan.md) — 独立刷题模块(v0.3.0完成，v0.4.22-v0.4.23演进)：463题导入、动态错题池、错题 AI 流式解答、题库专属提示词与 AI 原地润色、已生成解析持久化与全链路保留、小结选项精准渲染
- [功能路线图与PRD对照](feature-roadmap-prd-alignment.md) — 产品决策与版本日志：v0.4.0–v0.4.36全版本迭代（题库刷题新增做新题模式与做题模式、同一套题严格去重与未做新题统计看板、内置一键更新全链路镜像加速与实时网速、静默安装防卡死、自定义下载源编辑、学习者画像因材施教全链路闭环等）

- [Windows时间戳平局坑](windows-timestamp-monotonic.md) — time.time()粒度15.6ms致排序随机，utcnow_iso已单调化；smoke末尾自清理勿误判丢数据
- [发版全流程](release-process.md) — 版本bump三处、双构建、签名私钥路径、latest.json手工生成、API发布七步
- [后端数据目录隔离](dev-backend-data-isolation.md) — 桌面端数据在%APPDATA%\com.learnflow.desktop,源码后端落backend/data;agent测试必须APP_DATA_DIR隔离
- [Matplotlib示例图片入Windows相册排查](matplotlib-sample-images-leak.md) — PyInstaller默认全量收mpl-data致Grace Hopper等示例图片入相册；spec过滤+build保底+NSIS自清理
