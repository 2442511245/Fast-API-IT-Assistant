from . import register_tool

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
    allowed = set("0123456789.+-*/() ")
    if not all(c in allowed for c in expression):
        return "表达式包含不允许的字符"
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误：{str(e)}"