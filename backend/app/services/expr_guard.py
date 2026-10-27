"""数学表达式安全守卫：sympify 的 parse 阶段会原生求值属性链/下标/调用，
`().__class__.__bases__[0].__subclasses__()` 这类 gadget 拦不住（locals 限制无效）。
在 sympify 前用 AST 白名单确保表达式只含算术运算与白名单数学函数。
"""
import ast


class UnsafeExpression(ValueError):
    """表达式包含不允许的语法结构或调用。"""


_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)

_ALLOWED_FUNCS = frozenset(
    """
    sin cos tan cot sec csc
    asin acos atan acot asec acsc atan2
    sinh cosh tanh asinh acosh atanh
    exp log log2 log10 ln sqrt cbrt root
    Abs abs sign floor ceiling ceiling frac
    factorial binomial gamma beta erf erfc
    Min Max re im arg conjugate
    zeta LambertW Ei Si Ci Shi Chi li li2
    simplify expand factor trigsimp radsimp nsimplify
    pi E oo zoo I
    Symbol
    """.split()
)

def assert_math_expr_safe(expr: str, max_len: int = 500) -> None:
    """校验表达式只含白名单语法；不安全时抛 UnsafeExpression。"""
    if len(expr) > max_len:
        raise UnsafeExpression(f"表达式过长（>{max_len} 字符）")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"表达式语法错误：{e}") from e

    def _const_abs(node) -> float | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return abs(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return _const_abs(node.operand)
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load, *_ALLOWED_BINOPS, *_ALLOWED_UNARYOPS)):
            # 运算符/加载上下文节点本身（ast.walk 会把 op 节点也单独吐出）
            continue
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINOPS):
                raise UnsafeExpression(f"不允许的运算符：{type(node.op).__name__}")
            if isinstance(node.op, ast.Pow):
                # 幂塔（9**9**9 → 9**(9**9)）与超大常量指数会让 sympy 整数爆炸挂死线程
                if isinstance(node.right, ast.BinOp) and isinstance(node.right.op, ast.Pow):
                    raise UnsafeExpression("表达式包含嵌套幂运算（幂塔），会导致计算爆炸")
                mag = _const_abs(node.right)
                if mag is not None and mag > 10_000:
                    raise UnsafeExpression("指数过大，会导致计算爆炸")
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARYOPS):
                raise UnsafeExpression(f"不允许的一元运算符：{type(node.op).__name__}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise UnsafeExpression("只允许调用白名单内的数学函数")
            if node.keywords:
                raise UnsafeExpression("函数调用不允许关键字参数")
        elif isinstance(node, (ast.Name, ast.Constant)):
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                raise UnsafeExpression("只允许数字常量")
        else:
            raise UnsafeExpression(f"表达式包含不允许的语法：{type(node).__name__}")
