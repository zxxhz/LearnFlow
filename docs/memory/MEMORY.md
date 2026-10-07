# Memory Index

- [题库刷题模块](bank-drill-module-plan.md) — 独立刷题模块(v0.3.0完成，v0.4.22-v0.4.23演进)：463题导入、动态错题池、错题 AI 流式解答、题库专属提示词与 AI 原地润色、已生成解析持久化与全链路保留、小结选项精准渲染
- [功能路线图与PRD对照](feature-roadmap-prd-alignment.md) — 产品决策与版本日志：v0.4.0–v0.4.26全版本迭代（紧急修复Tauri v2 Updater端点协议强约束致桌面闪退、课程与刷题独立字号调节及公式全等比缩放、跨版本更新日志拼接聚合、下载源并发测速与智能路由、ADHD辅助阅读全内容块覆盖与圆角内衬、划线提问平移避让联动与现代流式打字机、目录固定独立滚动与折叠动效Ctrl+B、国内更新镜像回退、右侧全景面板统一动效避让、题库AI深度答疑与提示词自定制、错题解析跨状态保留持久化等）

- [Windows时间戳平局坑](windows-timestamp-monotonic.md) — time.time()粒度15.6ms致排序随机，utcnow_iso已单调化；smoke末尾自清理勿误判丢数据
- [发版全流程](release-process.md) — 版本bump三处、双构建、签名私钥路径、latest.json手工生成、API发布七步
- [后端数据目录隔离](dev-backend-data-isolation.md) — 桌面端数据在%APPDATA%\com.learnflow.desktop,源码后端落backend/data;agent测试必须APP_DATA_DIR隔离
- [Matplotlib示例图片入Windows相册排查](matplotlib-sample-images-leak.md) — PyInstaller默认全量收mpl-data致Grace Hopper等示例图片入相册；spec过滤+build保底+NSIS自清理
