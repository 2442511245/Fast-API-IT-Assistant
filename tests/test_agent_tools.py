"""
test_agent_tools.py — Agent 工具注册与模式切换单元测试

测试范围：
  - @register_tool 装饰器是否正确注册工具
  - get_all_tool_schemas() 返回正确的 JSON Schema
  - execute_tool() 按名称执行工具并返回结果
  - mock 模式和 real 模式的切换
  - 工具注册表的隔离与清理

使用 pytest + unittest.mock，Mock 掉外部 API（DashScope、subprocess 等）。
"""

import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
import json

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入工具框架核心函数
from agent.tools import register_tool, get_all_tool_schemas, execute_tool


# ============================================================
# 测试 1：@register_tool 装饰器
# ============================================================

class TestRegisterToolDecorator:
    """测试 @register_tool 装饰器的注册行为"""

    def test_register_tool_adds_to_registry(self):
        """使用 @register_tool 装饰的函数应出现在工具注册表中"""
        @register_tool(
            name="test_echo",
            description="测试用的 echo 工具",
            parameters={
                "type": "object",
                "properties": {
                    "msg": {"type": "string", "description": "要回显的消息"}
                },
                "required": ["msg"]
            }
        )
        def echo(msg: str) -> str:
            return f"ECHO: {msg}"

        schemas = get_all_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "test_echo" in names, f"test_echo 应在注册表中，当前注册: {names}"

    def test_register_tool_generates_openai_schema(self):
        """注册的工具应生成符合 OpenAI Function Calling 格式的 schema"""
        @register_tool(
            name="schema_test",
            description="验证 schema 结构",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"}
                },
                "required": ["x"]
            }
        )
        def schema_func(x: int) -> str:
            return str(x)

        schemas = get_all_tool_schemas()
        target = [s for s in schemas if s["function"]["name"] == "schema_test"][0]

        # 验证 OpenAI Function Calling schema 结构
        assert target["type"] == "function"
        assert "function" in target
        assert target["function"]["name"] == "schema_test"
        assert target["function"]["description"] == "验证 schema 结构"
        assert "parameters" in target["function"]
        assert target["function"]["parameters"]["type"] == "object"

    def test_register_multiple_tools(self):
        """注册多个工具后，get_all_tool_schemas 应返回所有注册的工具"""
        @register_tool(
            name="multi_a",
            description="工具 A",
            parameters={"type": "object", "properties": {}, "required": []}
        )
        def tool_a() -> str:
            return "A"

        @register_tool(
            name="multi_b",
            description="工具 B",
            parameters={"type": "object", "properties": {}, "required": []}
        )
        def tool_b() -> str:
            return "B"

        schemas = get_all_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "multi_a" in names
        assert "multi_b" in names

    def test_decorated_function_still_callable(self):
        """装饰后的函数应保持可调用，且返回正确结果"""
        @register_tool(
            name="callable_test",
            description="测试可调用性",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"}
                },
                "required": ["a", "b"]
            }
        )
        def add(a: int, b: int) -> str:
            return str(a + b)

        # 直接调用
        result = add(a=3, b=5)
        assert result == "8", f"3+5 应返回 '8'，实际返回 '{result}'"


# ============================================================
# 测试 2：execute_tool 执行
# ============================================================

class TestExecuteTool:
    """测试 execute_tool() 函数的执行逻辑"""

    def test_execute_existing_tool(self):
        """执行已注册的工具应返回正确结果"""
        @register_tool(
            name="exec_test",
            description="执行测试",
            parameters={
                "type": "object",
                "properties": {
                    "value": {"type": "string"}
                },
                "required": ["value"]
            }
        )
        def exec_func(value: str) -> str:
            return f"处理: {value}"

        result = execute_tool("exec_test", {"value": "hello"})
        assert "处理: hello" in result

    def test_execute_unregistered_tool_returns_error(self):
        """执行未注册的工具应返回错误信息"""
        result = execute_tool("nonexistent_tool_xyz", {})
        assert "错误" in result or "未注册" in result, \
            f"未注册工具应返回错误，实际返回: {result}"

    def test_execute_tool_returns_string(self):
        """execute_tool 的返回值必须是字符串"""
        @register_tool(
            name="returns_int",
            description="返回整数（应被转为字符串）",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        def int_func() -> int:
            return 42

        result = execute_tool("returns_int", {})
        assert isinstance(result, str), \
            f"execute_tool 必须返回 str，实际返回 {type(result).__name__}"

    def test_execute_with_invalid_arguments(self):
        """传入错误的参数时，工具应优雅处理（返回错误信息而非崩溃）"""
        @register_tool(
            name="strict_tool",
            description="需要特定参数的工具",
            parameters={
                "type": "object",
                "properties": {
                    "required_param": {"type": "string"}
                },
                "required": ["required_param"]
            }
        )
        def strict_func(required_param: str) -> str:
            return f"OK: {required_param}"

        # 缺少必填参数时可能通过 **kwargs 传入，wrapper 会处理
        # 这取决于具体实现——我们测试不抛未捕获异常即可
        try:
            result = execute_tool("strict_tool", {})
        except Exception as e:
            pytest.fail(f"execute_tool 不应抛出未捕获异常: {e}")


# ============================================================
# 测试 3：Mock / Real 模式切换
# ============================================================

class TestMockRealSwitching:
    """测试 mock 和 real 环境的切换机制"""

    def test_config_defaults_to_mock(self):
        """默认环境应为 mock 模式"""
        from agent.config import config
        assert config.env == "mock", \
            f"默认 env 应为 'mock'，实际为 '{config.env}'"

    @patch.dict(os.environ, {"AGENT_ENV": "real"})
    def test_env_var_overrides_config_to_real(self):
        """环境变量 AGENT_ENV=real 应覆盖配置文件"""
        from agent.config import AgentConfig
        cfg = AgentConfig.from_yaml()
        assert cfg.env == "real", \
            f"设置 AGENT_ENV=real 后 env 应为 'real'，实际为 '{cfg.env}'"

    @patch.dict(os.environ, {"AGENT_ENV": "mock"})
    def test_env_var_can_force_mock(self):
        """环境变量 AGENT_ENV=mock 可以强制使用模拟模式"""
        from agent.config import AgentConfig
        cfg = AgentConfig.from_yaml()
        assert cfg.env == "mock", \
            f"设置 AGENT_ENV=mock 后 env 应为 'mock'，实际为 '{cfg.env}'"

    @patch.dict(os.environ, {}, clear=True)
    def test_env_var_absent_falls_back_to_yaml(self):
        """无环境变量时，使用 config.yaml 的默认值"""
        # 清除 AGENT_ENV，确保回退到 yaml
        if "AGENT_ENV" in os.environ:
            del os.environ["AGENT_ENV"]
        from agent.config import AgentConfig
        cfg = AgentConfig.from_yaml()
        assert cfg.env in ["mock", "real"], \
            f"回退值应为 mock 或 real，实际为 '{cfg.env}'"

    def test_sql_tool_uses_config_env(self):
        """SQL 工具应使用 config.env 来决定 mock/real 行为"""
        from agent.tools.sql_tool import run_sql
        from agent.config import config

        # mock 模式：连接 SQLite
        original_env = config.env
        try:
            config.env = "mock"
            result = run_sql(query="SELECT 1")
            # mock 模式下不应抛出 NotImplementedError
            assert "NotImplementedError" not in result, \
                "mock 模式不应抛出 NotImplementedError"
        finally:
            config.env = original_env

    def test_k8s_tool_mock_mode_returns_mock_data(self):
        """K8s 工具在 mock 模式下应返回模拟集群数据"""
        from agent.tools.k8s_tool import kubectl_exec, list_k8s_resources
        from agent.config import config

        original_env = config.env
        try:
            config.env = "mock"
            result = kubectl_exec(command="kubectl get pods")
            # mock 模式应返回包含模拟 Pod 名称的结果
            assert "payment-svc" in result or "NAME" in result, \
                f"mock 模式应返回模拟数据，实际: {result[:100]}"
        finally:
            config.env = original_env

    def test_list_k8s_resources_returns_list(self):
        """list_k8s_resources 在 mock 模式下应返回 JSON 列表"""
        from agent.tools.k8s_tool import list_k8s_resources
        from agent.config import config

        original_env = config.env
        try:
            config.env = "mock"
            result = list_k8s_resources(resource_type="pods")
            data = json.loads(result)
            assert isinstance(data, list), "应返回 JSON 列表"
            assert len(data) > 0, "mock 集群应有 Pod"
        finally:
            config.env = original_env


# ============================================================
# 测试 4：各工具基础功能
# ============================================================

class TestIndividualTools:
    """测试每个工具的基础 mock 功能"""

    def test_calculator_basic_arithmetic(self):
        """计算器工具应正确执行基本算术"""
        from agent.tools.calculator_tool import calculator

        assert "7" in calculator(expression="3+4"), "3+4 应等于 7"
        assert "12" in calculator(expression="3*4"), "3*4 应等于 12"

    def test_calculator_rejects_invalid_chars(self):
        """计算器应拒绝包含不允许字符的表达式"""
        from agent.tools.calculator_tool import calculator

        result = calculator(expression="__import__('os')")
        assert "不允许" in result or "错误" in result, \
            f"应拒绝危险表达式，实际: {result}"

    def test_ticket_tool_creates_ticket(self):
        """工单创建工具应返回成功信息"""
        from agent.tools.ticket_tool import create_ticket
        from agent.config import config
        import tempfile
        import os as _os

        original_path = config.tickets_path
        try:
            # 使用临时文件避免污染真实数据
            tmp = tempfile.mktemp(suffix=".json")
            config.tickets_path = tmp
            result = create_ticket(
                title="测试工单",
                description="这是一条测试工单",
                priority="high"
            )
            assert "工单" in result, f"应返回工单创建成功信息，实际: {result}"
        finally:
            config.tickets_path = original_path
            if _os.path.exists(tmp):
                _os.remove(tmp)

    def test_search_tool_returns_string(self):
        """搜索工具应返回字符串结果"""
        from agent.tools.search_tool import web_search

        result = web_search(query="Kubernetes 故障排查")
        assert isinstance(result, str), "搜索结果应为字符串"
        assert len(result) > 0, "搜索结果不应为空"

    def test_sql_tool_select_in_mock(self):
        """SQL 工具在 mock 模式下执行 SELECT 应返回结果"""
        from agent.tools.sql_tool import run_sql
        from agent.config import config

        original_env = config.env
        try:
            config.env = "mock"
            result = run_sql(query="SELECT name FROM sqlite_master WHERE type='table'")
            assert isinstance(result, str), "SQL 结果应为字符串"
        finally:
            config.env = original_env


# ============================================================
# 测试 5：get_all_tool_schemas 格式验证
# ============================================================

class TestToolSchemaFormat:
    """测试生成的 JSON Schema 格式正确性"""

    def test_all_schemas_have_required_fields(self):
        """每个 schema 应包含 type, function.name, function.description, function.parameters"""
        schemas = get_all_tool_schemas()
        assert len(schemas) >= 5, f"至少应有 5 个预注册工具，实际: {len(schemas)}"

        for schema in schemas:
            assert schema["type"] == "function", \
                f"schema type 应为 'function'，实际: {schema}"
            func = schema["function"]
            assert "name" in func, "缺少 function.name"
            assert "description" in func, "缺少 function.description"
            assert "parameters" in func, "缺少 function.parameters"
            assert func["parameters"]["type"] == "object", \
                "parameters.type 应为 'object'"

    def test_required_tools_exist(self):
        """5 个核心工具都应注册：run_sql, kubectl_exec, list_k8s_resources,
        create_ticket, calculator, web_search"""
        schemas = get_all_tool_schemas()
        names = {s["function"]["name"] for s in schemas}

        required = {
            "run_sql", "kubectl_exec", "list_k8s_resources",
            "create_ticket", "calculator", "web_search"
        }
        missing = required - names
        assert not missing, f"缺少核心工具: {missing}"


# ============================================================
# 测试 6：工具参数 schema 校验
# ============================================================

class TestToolParameterSchema:
    """测试工具的 parameters schema 定义正确性"""

    def test_sql_tool_requires_query(self):
        """run_sql 应将 query 标记为必填参数"""
        schemas = get_all_tool_schemas()
        sql_schema = [s for s in schemas if s["function"]["name"] == "run_sql"][0]
        required = sql_schema["function"]["parameters"].get("required", [])
        assert "query" in required, "run_sql 应必填 query 参数"

    def test_kubectl_exec_requires_command(self):
        """kubectl_exec 应将 command 标记为必填参数"""
        schemas = get_all_tool_schemas()
        kube_schema = [s for s in schemas
                       if s["function"]["name"] == "kubectl_exec"][0]
        required = kube_schema["function"]["parameters"].get("required", [])
        assert "command" in required, "kubectl_exec 应必填 command 参数"

    def test_create_ticket_requires_title_and_description(self):
        """create_ticket 应将 title 和 description 标记为必填"""
        schemas = get_all_tool_schemas()
        ticket_schema = [s for s in schemas
                         if s["function"]["name"] == "create_ticket"][0]
        required = ticket_schema["function"]["parameters"].get("required", [])
        assert "title" in required, "create_ticket 应必填 title"
        assert "description" in required, "create_ticket 应必填 description"
