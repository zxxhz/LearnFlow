"""Prompt 模板加载与渲染。

模板存放在 backend/app/prompts/*.md，占位符使用 [[VAR]] 语法
（避免与正文中的花括号冲突），禁止在业务代码里内联长 prompt（PRD §7.3）。
"""
import sys
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_cache: dict[str, str] = {}


def _prompts_dir() -> Path:
    # PyInstaller 打包后模板来自 datas（_internal/app/prompts）；__file__ 相对解析
    # 通常已指向那里，_MEIPASS 仅作目录缺失时的兜底（见 learnflow_backend.spec datas）
    if getattr(sys, "frozen", False) and not _PROMPTS_DIR.exists():
        return Path(sys._MEIPASS) / "app" / "prompts"  # noqa: SLF001
    return _PROMPTS_DIR


def load_prompt(name: str) -> str:
    if name not in _cache:
        path = _prompts_dir() / f"{name}.md"
        _cache[name] = path.read_text(encoding="utf-8")
    return _cache[name]


def render_prompt(name: str, **variables: str) -> str:
    text = load_prompt(name)
    for key, value in variables.items():
        text = text.replace(f"[[{key}]]", value)
    return text
