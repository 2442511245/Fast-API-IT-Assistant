import ast
import operator

from . import register_tool

# ---------- 安全运算器（仅允许 + - * / ** ( )）----------
_SAFE_OPS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.Pow:      operator.pow,
    ast.USub:     operator.neg,
    ast.UAdd:     operator.pos,
}

_MAX_EXPR_LEN = 200


def _eval_ast(node):
    """递归求值 AST，仅允许安全运算符"""
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_ast(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](
            _eval_ast(node.left),
            _eval_ast(node.right)
        )
    raise ValueError("不支持的运算")


@register_tool(
    name="calculator",
    description="执行数学计算，输入表达式字符串，返回计算结果。仅支持数字、+、-、*、/、()。",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '3*4+2'"}
        },
        "required": ["expression"]
    }
)
def calculator(expression: str) -> str:
    # 1. 字符白名单
    allowed = set("0123456789.+-*/() ")
    if not all(c in allowed for c in expression):
        return "表达式包含不允许的字符"

    # 2. 长度限制，防止超大计算 DoS
    if len(expression.strip()) > _MAX_EXPR_LEN:
        return f"表达式过长（最多 {_MAX_EXPR_LEN} 字符）"

    # 3. 用 ast.parse 安全解析并求值
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval_ast(tree)
        return str(result)
    except SyntaxError:
        return "表达式语法错误"
    except Exception as e:
        return f"计算错误：{str(e)}"