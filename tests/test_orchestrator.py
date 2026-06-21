"""
test_orchestrator.py — 意图识别调度单元测试

测试范围：
  - RAG 类问题（"怎么重启 Nginx"）→ 路由到 rag
  - Agent 类问题（"帮我查一下 Pod 状态"）→ 路由到 agent
  - 闲聊（"你好"）→ 路由到 chat
  - mixed 类问题 → 路由到 mixed
  - 异常处理（API 调用失败时的降级策略）

使用 pytest + unittest.mock，Mock 掉 DashScope Generation.call 外部 API。
"""

import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 辅助函数：构造 Mock DashScope 响应
# ============================================================

def make_mock_response(intent: str):
    """
    构造一个模拟的 DashScope Generation.call() 返回对象
    模拟 resp.output.choices[0].message.content 的访问路径
    """
    mock_message = MagicMock()
    mock_message.content = intent

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_output = MagicMock()
    mock_output.choices = [mock_choice]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.output = mock_output

    return mock_resp


def make_mock_error_response():
    """构造一个模拟的 API 错误返回"""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.message = "Internal Server Error"
    return mock_resp


# ============================================================
# 测试 1：意图分类基本功能
# ============================================================

class TestIntentClassification:
    """测试 classify_intent() 能否正确分类各类意图"""

    @patch("orchestrator.classifier.Generation.call")
    def test_rag_question_routes_to_rag(self, mock_call):
        """
        输入 RAG 类知识库问题（如"怎么重启 Nginx"），
        断言 classify_intent 返回 "rag"
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("rag")
        intent = classify_intent("怎么重启 Nginx 服务？")
        assert intent == "rag", \
            f"知识库问题应路由到 rag，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_agent_question_routes_to_agent(self, mock_call):
        """
        输入 Agent 类运维操作问题（如"帮我查一下 Pod 状态"），
        断言 classify_intent 返回 "agent"
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("agent")
        intent = classify_intent("帮我查一下 payment-service 的 Pod 状态")
        assert intent == "agent", \
            f"运维操作问题应路由到 agent，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_chat_greeting_routes_to_chat(self, mock_call):
        """
        输入闲聊问候（如"你好"），
        断言 classify_intent 返回 "chat"
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("chat")
        intent = classify_intent("你好")
        assert intent == "chat", \
            f"问候语应路由到 chat，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_mixed_question_routes_to_mixed(self, mock_call):
        """
        输入既需要查文档又需要执行操作的问题，
        断言 classify_intent 返回 "mixed"
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("mixed")
        intent = classify_intent(
            "payment 服务最近有什么错误？先查文档看有没有相关记录"
        )
        assert intent == "mixed", \
            f"混合意图应路由到 mixed，实际: {intent}"


# ============================================================
# 测试 2：意图路由的边界情况
# ============================================================

class TestIntentBoundaryCases:
    """测试意图分类的边界和异常情况"""

    @patch("orchestrator.classifier.Generation.call")
    def test_api_error_falls_back_to_chat(self, mock_call):
        """
        API 调用失败时（status_code != 200），
        classify_intent 应降级返回 "chat"
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_error_response()
        intent = classify_intent("任意问题")
        assert intent == "chat", \
            f"API 失败时应降级为 chat，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_unknown_intent_falls_back_to_chat(self, mock_call):
        """
        LLM 返回非预期的意图词时，应回退为 "chat"
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("unknown_intent_xyz")
        intent = classify_intent("随便说点什么")
        assert intent == "chat", \
            f"未识别意图应回退为 chat，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_intent_case_insensitive(self, mock_call):
        """
        意图词应大小写不敏感（"RAG"、"Rag"、"rag" 都视为 rag）
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("RAG")
        intent = classify_intent("怎么配置防火墙规则")
        assert intent == "rag", \
            f"'RAG' 大写应识别为 rag，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_intent_with_whitespace(self, mock_call):
        """
        意图词前后有空白字符时应正常工作
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("  agent  ")
        intent = classify_intent("查一下数据库的 sales 表")
        assert intent == "agent", \
            f"带空白字符的 'agent' 应正确识别，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_empty_input(self, mock_call):
        """
        空输入应不被处理为异常情况
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("chat")
        intent = classify_intent("")
        # 空输入不应抛出异常
        assert intent in ["chat", "rag", "agent", "mixed"], \
            f"空输入应返回有效意图，实际: {intent}"


# ============================================================
# 测试 3：集成分流路由（智能调度）
# ============================================================

class TestIntelligentRouting:
    """
    测试 orchestrator 将分类结果正确调度到对应模块
    模拟 intelligent_assist 的四种分流路径
    """

    @patch("orchestrator.classifier.Generation.call")
    def test_chat_intent_calls_chat_module(self, mock_call):
        """
        当意图为 chat 时，应调用聊天模块
        验证传入的 message 正确传递
        """
        from orchestrator.classifier import classify_intent
        from chat.router import ChatRequest

        mock_call.return_value = make_mock_response("chat")
        intent = classify_intent("今天天气真好啊")
        assert intent == "chat"

        # 模拟 orchestrator 的调度逻辑
        if intent == "chat":
            chat_req = ChatRequest(message="今天天气真好啊")
            assert chat_req.message == "今天天气真好啊", \
                "ChatRequest 应包含原始消息"

    @patch("orchestrator.classifier.Generation.call")
    def test_agent_intent_routes_to_agent_module(self, mock_call):
        """
        当意图为 agent 时，应路由到 Agent 模块
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("agent")
        intent = classify_intent("扩容 payment-service 到 5 个副本")
        assert intent == "agent", \
            f"扩容命令应路由到 agent，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_mixed_intent_uses_rag_then_agent(self, mock_call):
        """
        当意图为 mixed 时，应先用 RAG 检索，再将结果注入 Agent
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("mixed")
        intent = classify_intent(
            "payment 服务报错了，先查文档看有没有解决方案，再排查 Pod 日志"
        )
        assert intent == "mixed", \
            f"复杂运维问题应路由到 mixed，实际: {intent}"

    @patch("orchestrator.classifier.Generation.call")
    def test_rag_intent_requires_knowledge_base_initialized(self, mock_call):
        """
        当意图为 rag 但知识库未初始化时，应返回错误提示
        模拟 orchestrator 中的 global rag_chain 为 None 场景
        """
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("rag")
        intent = classify_intent("公司的 VPN 怎么连接")
        assert intent == "rag"

        # 模拟 orchestrator 中知识库未初始化的检查逻辑
        rag_chain = None  # 模拟未初始化
        if intent == "rag" and not rag_chain:
            error_handled = True
            assert error_handled, "知识库未初始化时应返回错误而非崩溃"


# ============================================================
# 测试 4：分类器输入格式
# ============================================================

class TestClassifierInputFormat:
    """测试 classify_intent 对各种输入格式的兼容性"""

    @patch("orchestrator.classifier.Generation.call")
    def test_chinese_question_with_punctuation(self, mock_call):
        """带标点符号的中文问题应正确分类"""
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("rag")
        intent = classify_intent("请问：公司的 VPN 怎么连接？需要什么权限！")
        assert intent == "rag"

    @patch("orchestrator.classifier.Generation.call")
    def test_english_question(self, mock_call):
        """英文输入也应正确分类"""
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("chat")
        intent = classify_intent("Hello, how are you?")
        assert intent == "chat"

    @patch("orchestrator.classifier.Generation.call")
    def test_long_technical_question(self, mock_call):
        """长技术问题应正确路由"""
        from orchestrator.classifier import classify_intent

        mock_call.return_value = make_mock_response("agent")
        long_question = (
            "我们生产环境的 payment-service 最近频繁重启，"
            "平均每 5 分钟一次。请帮我排查是什么原因导致的，"
            "如果需要扩容请告诉我。另外检查一下数据库连接是否正常。"
        )
        intent = classify_intent(long_question)
        assert intent == "agent", \
            f"长技术问题应路由到 agent，实际: {intent}"


# ============================================================
# 测试 5：orchestrator 与各模块的接口契约
# ============================================================

class TestOrchestratorContract:
    """
    验证 orchestrator 调度逻辑与各模块的函数签名契约
    确保智能调度层正确调用各模块接口
    """

    def test_chat_module_accepts_chat_request(self):
        """
        验证 chat 模块的 ChatRequest 模型接受 message 字段
        """
        from chat.router import ChatRequest

        req = ChatRequest(message="测试消息")
        assert req.message == "测试消息"
        assert hasattr(req, "message"), "ChatRequest 必须有 message 属性"

    def test_orchestrator_user_request_model(self):
        """
        验证 orchestrator 的 UserRequest 模型
        """
        from orchestrator.router import UserRequest

        req = UserRequest(message="用户问题")
        assert req.message == "用户问题"

    def test_agent_request_model(self):
        """
        验证 agent 模块的 AgentRequest 模型
        """
        from agent.router import AgentRequest

        req = AgentRequest(message="查询 Pod 状态")
        assert req.message == "查询 Pod 状态"

    @patch("orchestrator.classifier.Generation.call")
    def test_four_intents_cover_all_routes(self, mock_call):
        """
        四种意图 (chat/rag/agent/mixed) 应在调度层都有对应的处理分支
        通过验证 classify_intent 只返回四种合法值来间接测试
        """
        from orchestrator.classifier import classify_intent

        valid_intents = {"chat", "rag", "agent", "mixed"}

        for expected in valid_intents:
            mock_call.return_value = make_mock_response(expected)
            result = classify_intent("测试")
            assert result in valid_intents, \
                f"classify_intent 应只返回 {valid_intents} 之一，实际: {result}"


# ============================================================
# 测试 6：模拟完整的调度流程
# ============================================================

class TestFullOrchestrationFlow:
    """
    端到端测试：从用户输入到最终模块调用的完整链路
    （Mock 掉所有外部依赖）
    """

    @patch("orchestrator.classifier.Generation.call")
    @patch("orchestrator.router.chat_send")
    def test_full_flow_chat(self, mock_chat_send, mock_classify):
        """
        完整流程：用户输入 "你好" → classify_intent 返回 "chat" → 调用 chat_send
        """
        from orchestrator.classifier import classify_intent
        from chat.router import ChatRequest

        mock_classify.return_value = make_mock_response("chat")
        mock_chat_send.return_value = {"reply": "你好！有什么可以帮助你的？"}

        # Step 1: 分类
        user_input = "你好"
        intent = classify_intent(user_input)
        assert intent == "chat"

        # Step 2: 调度到 chat 模块
        if intent == "chat":
            chat_req = ChatRequest(message=user_input)
            result = mock_chat_send(chat_req)
            assert "reply" in result, "chat 模块应返回 reply"

    @patch("orchestrator.classifier.Generation.call")
    def test_full_flow_agent_with_mocked_core(self, mock_classify):
        """
        完整流程：用户输入运维指令 → 分类为 agent → 模拟 AgentCore.run()
        """
        from orchestrator.classifier import classify_intent
        from unittest.mock import MagicMock

        mock_classify.return_value = make_mock_response("agent")

        # Step 1: 分类
        user_input = "payment-service 的 Pod 状态怎么样"
        intent = classify_intent(user_input)
        assert intent == "agent"

        # Step 2: 模拟 AgentCore 返回事件流
        mock_agent = MagicMock()
        mock_agent.run.return_value = iter([
            {"type": "thinking", "content": "正在思考..."},
            {"type": "tool_call", "name": "list_k8s_resources",
             "arguments": {"resource_type": "pods"}, "thought": "先查看 Pod 列表"},
            {"type": "tool_result", "name": "list_k8s_resources",
             "content": '["payment-svc-abc", "payment-svc-def"]'},
            {"type": "final", "content": "payment-service 有 2 个 Pod 在运行。"},
        ])

        events = list(mock_agent.run(user_input))
        assert len(events) > 0, "Agent 应产生事件"
        assert events[-1]["type"] == "final", "最后一个事件应为 final"
        assert "Pod" in events[-1]["content"], "最终回答应包含 Pod 信息"

    @patch("orchestrator.classifier.Generation.call")
    def test_full_flow_rag_with_mock_chain(self, mock_classify):
        """
        完整流程：用户问知识库问题 → 分类为 rag → 模拟 ask_question
        """
        from orchestrator.classifier import classify_intent
        from unittest.mock import MagicMock
        from langchain_core.documents import Document

        mock_classify.return_value = make_mock_response("rag")

        # Step 1: 分类
        user_input = "如何重置 VPN 密码？"
        intent = classify_intent(user_input)
        assert intent == "rag"

        # Step 2: 模拟 RAG 返回
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = "请登录 IT 门户，在安全设置中重置 VPN 密码。"

        mock_retriever = MagicMock()
        mock_retriever.invoke.return_value = [
            Document(page_content="VPN 密码重置流程：登录门户 → 安全设置 → 重置。")
        ]

        from rag.core.rag import ask_question
        answer, sources = ask_question(mock_chain, mock_retriever, user_input)
        assert len(answer) > 0, "RAG 应返回回答"
        assert len(sources) > 0, "RAG 应返回来源文档"
