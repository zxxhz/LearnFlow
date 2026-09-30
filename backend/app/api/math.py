"""高数图形化（PRD §5.9 / 实现备注 14）：SymPy 解析 + Matplotlib 渲染 SVG。

POST /api/math/render {expressions: "sin(x)/x\nf2(x)=cos(x)", x_min, x_max}
每行一个函数：`f名(x)=表达式` 或裸表达式；绘图结果是即时渲染，不持久化。
"""
import asyncio
import io
import logging

import matplotlib

matplotlib.use("Agg")  # 无显示环境
import matplotlib.pyplot as plt  # noqa: E402
import sympy as sp  # noqa: E402
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/math", tags=["math"])

MAX_LINES = 6
MAX_POINTS = 600


class PlotRequest(BaseModel):
    expressions: str
    x_min: float = -10.0
    x_max: float = 10.0

    @field_validator("expressions")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("表达式为空")
        return v

    @field_validator("x_max")
    @classmethod
    def _range(cls, v: float, info):
        x_min = info.data.get("x_min", -10.0)
        if not (v > x_min):
            raise ValueError("x_max 必须大于 x_min")
        if v - x_min > 10_000:
            raise ValueError("绘图区间过大")
        return v


def _parse_line(line: str, x: sp.Symbol) -> sp.Expr:
    expr = line.strip()
    if "=" in expr and not line.strip().startswith(("=", "<", ">")):
        lhs, _, rhs = expr.partition("=")
        # 允许 f(x)=... / y=... 形式，取等号右侧
        if "(" in lhs or lhs.strip() in ("y", "f", "g", "h"):
            expr = rhs
    expr = expr.strip()
    if not expr:
        raise ValueError("存在空表达式行")
    try:
        parsed = sp.sympify(expr, locals={"x": x})
    except (sp.SympifyError, SyntaxError, TypeError) as e:
        raise ValueError(f"无法解析的表达式「{line.strip()}」：{e}")
    unknown = parsed.free_symbols - {x}
    if unknown:
        # sympify 会把任意标识符当自由符号（如中文"这不是数学"），必须拒绝
        names = "、".join(sorted(str(s) for s in unknown))
        raise ValueError(f"表达式「{line.strip()}」含未知符号：{names}（只能使用 x）")
    return parsed


def render_sync(expressions: str, x_min: float, x_max: float) -> str:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    x = sp.Symbol("x")
    lines = [l for l in expressions.strip().splitlines() if l.strip()][:MAX_LINES]
    if not lines:
        raise ValueError("表达式为空")

    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=110)
    xs = [x_min + (x_max - x_min) * i / MAX_POINTS for i in range(MAX_POINTS + 1)]
    try:
        for line in lines:
            expr = _parse_line(line, x)
            f = sp.lambdify(x, expr, modules=["numpy"])
            ys = []
            for xv in xs:
                try:
                    yv = float(f(xv))
                except (TypeError, ValueError, ZeroDivisionError):
                    yv = None  # 奇点/定义域外断开
                ys.append(yv)
            # 分离断点（如 tan、1/x 的奇点）
            seg_x, seg_y = [], []
            for xv, yv in zip(xs, ys):
                if yv is None or abs(yv) > 1e6:
                    if len(seg_x) > 1:
                        ax.plot(seg_x, seg_y, linewidth=1.8)
                    seg_x, seg_y = [], []
                    continue
                seg_x.append(xv)
                seg_y.append(yv)
            if len(seg_x) > 1:
                ax.plot(seg_x, seg_y, linewidth=1.8, label=line.strip())
    except (sp.SympifyError, TypeError, SyntaxError) as e:
        plt.close(fig)
        raise HTTPException(status_code=400, detail=f"表达式无法解析：{e}")

    ax.axhline(0, color="#9ca3af", linewidth=0.8)
    ax.axvline(0, color="#9ca3af", linewidth=0.8)
    ax.grid(True, alpha=0.25)
    ax.set_xlabel("x")
    if len(lines) > 1:
        ax.legend(fontsize=9)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue().decode("utf-8")


@router.post("/render")
async def render(body: PlotRequest):
    try:
        svg = await asyncio.to_thread(render_sync, body.expressions, body.x_min, body.x_max)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("math render failed")
        raise HTTPException(status_code=400, detail=f"绘图失败：{e}")
    return {"svg": svg}
