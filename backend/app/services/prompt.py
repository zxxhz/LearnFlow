"""Prompt 模板加载与渲染。

模板存放在 backend/app/prompts/*.md，占位符使用 [[VAR]] 语法
（避免与正文中的花括号冲突），禁止在业务代码里内联长 prompt（PRD §7.3）。
"""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_cache: dict[str, str] = {}


def load_prompt(name: str) -> str:
    if name not in _cache:
        path = _PROMPTS_DIR / f"{name}.md"
        _cache[name] = path.read_text(encoding="utf-8")
    return _cache[name]


def render_prompt(name: str, **variables: str) -> str:
    text = load_prompt(name)
    for key, value in variables.items():
        text = text.replace(f"[[{key}]]", value)
    return text
