# -*- mode: python ; coding: utf-8 -*-
"""LearnFlow 后端 PyInstaller 打包配置（onedir）。

产物：dist/learnflow-backend/{learnflow-backend.exe, _internal/}
- _internal/app/static      前端构建产物（需先构建前端，见 scripts/build_backend.py）
- _internal/python-runtime  用户代码沙箱用的独立 Python（scripts/build_backend.py 从
                            uv 管理的解释器精简复制而来）

构建：cd backend && uv run python scripts/build_backend.py
"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    "aiosqlite",
    # 题库导入（services/bank.py 函数内 import）：显式声明防漏收
    "xlrd",
    "openpyxl",
    "anyio._backends._asyncio",
    # matplotlib 后端运行时才选定（math.py 里 matplotlib.use("Agg")），钩子收集不到：
    # 渲染走 Agg，savefig(format="svg") 走 backend_svg
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_svg",
]
# uvicorn 程序化启动按需动态导入 loops/protocols/lifespan 子模块，全量收进去
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("openai")
# 工具链一键安装解压 7z 用（py7zr 内部动态加载编解码器，全量收；LZMA2 需要 pyppmd + Cryptodome）
hiddenimports += collect_submodules("py7zr")
hiddenimports += ["pyppmd", "Cryptodome.Cipher.AES"]

a = Analysis(
    ["run_backend.py"],
    pathex=[SPECPATH],
    binaries=[],
    datas=[
        ("app/static", "app/static"),
        # prompt 模板是运行时按路径读取的数据文件（PyInstaller 不会自动收集）：
        # 漏掉会导致配置 LLM 后所有走 render_prompt 的接口 500（如导入 md、建课）
        ("app/prompts", "app/prompts"),
        ("build/python-runtime", "python-runtime"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

# 过滤掉 matplotlib 自带的 sample_data 示例数据（如 grace_hopper.jpg 等图片）以及 GUI 工具栏 images 图标：
# 1. LearnFlow 高数绘图走 Agg + backend_svg 无头渲染，完全不需要 sample_data 和 GUI 工具栏图片。
# 2. 如果打包进去，Windows 照片/图片应用（Photos）会递归扫描索引该目录，导致用户的系统照片中莫名出现 Grace Hopper 等示例图片。
a.datas = [
    d
    for d in a.datas
    if not (
        ("matplotlib" in d[0].lower() or "matplotlib" in str(d[1]).lower())
        and (
            "sample_data" in d[0].replace("\\", "/").lower()
            or "mpl-data/images" in d[0].replace("\\", "/").lower()
            or "sample_data" in str(d[1]).replace("\\", "/").lower()
            or "mpl-data/images" in str(d[1]).replace("\\", "/").lower()
        )
    )
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="learnflow-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="learnflow-backend",
)
