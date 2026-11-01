"""Prompt 模板加载与渲染。

模板存放在 backend/app/prompts/*.md，占位符使用 [[VAR]] 语法
（避免与正文中的花括号冲突），禁止在业务代码里内联长 prompt（PRD §7.3）。
"""
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_cache: dict[str, str] = {}

# 单遍渲染：只替换模板文本里的 [[VAR]]，变量值中的 [[…]] 不再二次替换
_PLACEHOLDER_RE = re.compile(r"\[\[([A-Z_0-9]+)\]\]")
# 任何 [[…]] 形态的记号（用于预加载检查）
_ANY_BRACKET_RE = re.compile(r"\[\[([^\[\]]+)\]\]")


def _prompts_dir() -> Path:
    # PyInstaller 打包后模板来自 datas（_internal/app/prompts）；__file__ 相对解析
    # 通常已指向那里，_MEIPASS 仅作目录缺失时的兜底（见 learnflow_backend.spec datas）
    if getattr(sys, "frozen", False) and not _PROMPTS_DIR.exists():
        return Path(sys._MEIPASS) / "app" / "prompts"  # noqa: SLF001
    return _PROMPTS_DIR


def load_prompt(name: str) -> str:
    if name not in _cache:
        path = _prompts_dir() / f"{name}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"Prompt 模板缺失：{name}（{path}）：{e}") from e
        if not text.strip():
            raise RuntimeError(f"Prompt 模板为空：{name}（{path}）")
        _cache[name] = text
    return _cache[name]


def render_prompt(name: str, **variables: str) -> str:
    """单遍渲染：缺变量保持 [[VAR]] 占位符原样（与旧 replace 行为一致）；
    变量值里若本身含 [[…]] 字样不会被二次替换。"""
    text = load_prompt(name)
    return _PLACEHOLDER_RE.sub(lambda m: variables.get(m.group(1), m.group(0)), text)


def preload_prompts() -> None:
    """启动预加载：逐个加载全部模板（缺失/空白即刻暴露），并静态检查占位符形态。

    render_prompt 只替换 [[大写变量]]：模板里出现其它形态的 [[…]] 记号（小写/带连字符等）
    永远不会被替换，渲染后会原样残留并与用户内容混淆——发现即告警。
    """
    try:
        names = sorted(p.stem for p in _prompts_dir().glob("*.md"))
    except OSError as e:
        logger.warning("prompts 目录不可读，跳过预加载：%s", e)
        return
    for name in names:
        try:
            text = load_prompt(name)
        except RuntimeError as e:
            logger.error("%s", e)
            continue
        bad = sorted(
            {tok for tok in _ANY_BRACKET_RE.findall(text) if not _PLACEHOLDER_RE.fullmatch(f"[[{tok}]]")}
        )
        if bad:
            logger.warning("prompt 模板 %s 含永远不会被渲染替换的 [[…]] 记号：%s", name, bad)


# 导入即预加载：模板缺失/空白在启动期就通过日志暴露（内部已兜底，不影响导入成功）
preload_prompts()
