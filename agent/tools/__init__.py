from functools import wraps
from typing import Dict, Any, Callable, List
import json

_registered_tools: Dict[str, dict] = {}

def register_tool(name: str, description: str, parameters: Dict[str, Any]):
    """装饰器工厂：将函数注册为工具，自动生成 OpenAI 兼容的 JSON Schema"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(**kwargs):
            return func(**kwargs)

        _registered_tools[name] = {
            "func": wrapper,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters
                }
            }
        }
        return wrapper
    return decorator

def get_all_tool_schemas() -> List[Dict[str, Any]]:
    """返回所有工具的 JSON Schema 列表"""
    return [tool["schema"] for tool in _registered_tools.values()]

def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """执行指定工具，返回字符串结果"""
    if name not in _registered_tools:
        return f"错误：未注册的工具 '{name}'"
    try:
        result = _registered_tools[name]["func"](**arguments)
        # 确保返回字符串
        return json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result
    except Exception as e:
        return f"工具执行异常：{str(e)}"
    # 导入所有工具模块，触发 @register_tool 装饰器的执行
from . import sql_tool
from . import k8s_tool
from . import ticket_tool
from . import calculator_tool
from . import search_tool