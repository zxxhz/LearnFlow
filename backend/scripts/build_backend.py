"""构建 LearnFlow 后端独立可执行文件（PyInstaller onedir）。

用法：cd backend && uv run python scripts/build_backend.py

产物：dist/learnflow-backend/{learnflow-backend.exe, _internal/}
- 桌面安装包不再需要用户机器安装 Python / uv
- _internal/python-runtime：随包分发的独立 Python（stdlib），供"文档内代码运行"
  沙箱使用（沙箱以 -I 隔离模式运行用户代码，不带第三方依赖）

步骤：
1. 前端构建产物（app/static/index.html）缺失时先构建前端
2. 从 .venv/pyvenv.cfg 找到 uv 管理的基础解释器，精简复制到 build/python-runtime
3. PyInstaller 按 learnflow_backend.spec 打包
"""
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STATIC_INDEX = BACKEND_ROOT / "app" / "static" / "index.html"
RUNTIME_STAGE = BACKEND_ROOT / "build" / "python-runtime"

# 沙箱运行时不带的目录/文件：体积大头且与 -I 隔离运行无关
PRUNE = shutil.ignore_patterns(
    "__pycache__", "*.pyc",
    "site-packages",
    "test", "tests", "idlelib", "turtledemo", "lib2to3",
    "ensurepip", "venv", "tkinter", "tcl", "include", "Tools",
)


def build_frontend() -> None:
    print(">>> 前端产物缺失，先构建前端（npm run build → backend/app/static）…")
    npm = shutil.which("npm")
    if not npm:
        sys.exit("未找到 npm：请先安装 Node 18+，或手动执行 cd frontend && npm install && npm run build")
    subprocess.run([npm, "run", "build"], cwd=BACKEND_ROOT.parent / "frontend", check=True)
    if not STATIC_INDEX.exists():
        sys.exit("前端构建后仍缺少 app/static/index.html")


def stage_python_runtime() -> None:
    venv_cfg = BACKEND_ROOT / ".venv" / "pyvenv.cfg"
    if not venv_cfg.exists():
        sys.exit("缺少 backend/.venv：请先在 backend/ 下运行 uv sync")
    base = None
    for line in venv_cfg.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("home"):
            base = Path(line.split("=", 1)[1].strip())
            break
    if not base or not (base / "python.exe").exists():
        sys.exit(f"无法从 {venv_cfg} 解析基础解释器路径")
    if RUNTIME_STAGE.exists():
        shutil.rmtree(RUNTIME_STAGE)
    shutil.copytree(base, RUNTIME_STAGE, ignore=PRUNE)
    size_mb = sum(f.stat().st_size for f in RUNTIME_STAGE.rglob("*") if f.is_file()) / 1e6
    print(f">>> python-runtime 就绪（{size_mb:.0f} MB）：{RUNTIME_STAGE}")


def main() -> None:
    if not STATIC_INDEX.exists():
        build_frontend()
    stage_python_runtime()
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "learnflow_backend.spec",
         "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build/work"],
        cwd=BACKEND_ROOT,
        check=True,
    )
    out = BACKEND_ROOT / "dist" / "learnflow-backend"
    size_mb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f">>> 打包完成（{size_mb:.0f} MB）：{out / 'learnflow-backend.exe'}")


if __name__ == "__main__":
    main()
