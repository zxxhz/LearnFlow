---
name: matplotlib-sample-images-leak
description: Matplotlib 自带示例图片与图标导致出现在 Windows 照片流中的排查、根因与全链路规避（2026-10-05）
metadata:
  node_type: memory
  type: project
---

# Matplotlib 示例图片出现在 Windows 照片应用排查与修复

### 问题背景
用户反馈安装或运行 LearnFlow 后，Windows 系统的「照片 / 图片」应用（Photos）中莫名出现了项目的图片（如 Grace Hopper 肖像 `grace_hopper.jpg`、Matplotlib 官方 logo `logo2.png`、以及 GUI 按钮图标等）。

### 根本原因
1. **PyInstaller 默认收集机制**：PyInstaller 自带的 `hook-matplotlib.py` 会将 `matplotlib.get_data_path()`（即整个 `mpl-data` 目录）完整作为数据文件打包到 `_internal/matplotlib/mpl-data` 中。
2. **包含大量测试/示例图片**：`mpl-data/sample_data` 中包含 `grace_hopper.jpg`、`logo2.png`、`Minduka_Present_Blue_Pack.png` 等示例媒体文件；`mpl-data/images` 中包含桌面端 GUI 工具栏图标（如 `matplotlib.png`, `filesave.png` 等）。
3. **Windows 照片应用的主动索引机制**：
   - Windows 照片应用默认会递归索引用户的「图片」、「桌面（Desktop）」以及 `%LOCALAPPDATA%` 应用安装目录。
   - 当开发者在桌面运行/构建（`desktop/src-tauri/target/release/backend/...`）或用户通过安装包安装至 `%LOCALAPPDATA%\Programs\LearnFlow` 时，Windows 照片应用扫描到这些图片并将其自动展示在用户的相册时间线中。
4. **业务无依赖**：LearnFlow 仅在高数绘图（`app/api/math.py`）中使用 `matplotlib.use("Agg")` 进行纯无头（headless）SVG 矢量渲染，完全不需要任何 `sample_data` 示例数据和 GUI 交互工具栏 `images` 图标。

### 修复与防护方案（四层防御）

1. **即时文件清理**：
   - 彻底删除 `desktop/src-tauri/target/release/backend/_internal/matplotlib/mpl-data/{sample_data,images}`。
   - 彻底删除 `desktop/src-tauri/target/debug/backend/_internal/matplotlib/mpl-data/{sample_data,images}`。
   - 彻底删除 `backend/dist/learnflow-backend/_internal/matplotlib/mpl-data/{sample_data,images}`。

2. **PyInstaller Spec 文件源头过滤（`backend/learnflow_backend.spec`）**：
   在 `Analysis(...)` 之后，显式对 `a.datas` 进行过滤，移除所有目标路径或源路径中属于 `matplotlib` 下 `sample_data` 与 `mpl-data/images` 的条目，杜绝在打包产物生成阶段漏入。

3. **后端构建脚本保底防御（`backend/scripts/build_backend.py`）**：
   在 PyInstaller 运行完成后增加 `prune_matplotlib_sample_images` 函数，若 `dist/learnflow-backend/_internal/matplotlib/mpl-data` 下存在 `sample_data` 或 `images`，强制将其物理删除。

4. **NSIS 安装器升级自清理（`desktop/src-tauri/installer-hooks.nsh`）**：
   在 `NSIS_HOOK_POSTINSTALL` 钩子中增加 `RMDir /r "$INSTDIR\backend\_internal\matplotlib\mpl-data\sample_data"` 和 `RMDir /r "$INSTDIR\backend\_internal\matplotlib\mpl-data\images"`。
   即便老版本用户（历史版本已包含该图片）通过一键更新/覆盖安装升级，安装器在装完后也会主动从用户安装目录中删除旧残留图片，避免老用户受扰。

关联：[[release-process]]
