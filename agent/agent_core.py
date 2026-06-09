import json
import time
from typing import Generator, Dict, Any, List
import dashscope
from dashscope import Generation
from .tools import get_all_tool_schemas, execute_tool
from .config import config

class AgentCore:
    def __init__(self, system_prompt: str = ""):
        default_system = """你是一个企业智能助手。当前连接的测试环境中有以下可用资源：
       
        
        【数据库】
        - 表名：sales
        - 字段：region(地区), product(产品), revenue(营收), quarter(季度)
        - 数据覆盖：华南、华北、华东、西南，Q1/Q2

        【Kubernetes 集群】
        - 可用服务：payment-service, user-service, order-service
        - 你可以执行：get pods, logs <pod>, scale deployment <name> --replicas=N
        
- run_sql：查询数据库
- kubectl_exec：执行 Kubernetes 运维命令
- create_ticket：创建工单请求人工处理
- calculator：数学计算
- web_search：搜索互联网
重要规则：
1. 排查问题时，先通过 list_k8s_resources 或 get pods 确认资源名称，再用精确名称查日志。
2. 必须实际查到的日志中包含 database/error/timeout 等关键词，才可执行 scale 或创建工单。
3. 如果首次 logs 查询返回空，尝试用 list_k8s_resources 获取真实 Pod 名后重新查询。
4. 创建工单时，标题和描述必须基于实际查到的错误内容，不得推测。
"""
        self.messages = [{"role": "system", "content": system_prompt or default_system}]
        # 强制导入工具模块
        from .tools import sql_tool
        from .tools import k8s_tool
        from .tools import ticket_tool
        from .tools import calculator_tool
        from .tools import search_tool
        
        self.tool_schemas = get_all_tool_schemas()
        print(f"[DEBUG] 已注册工具数量: {len(self.tool_schemas)}")
        print(f"[DEBUG] 工具名称: {[t['function']['name'] for t in self.tool_schemas]}")

    def run(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """运行 Agent，返回事件生成器"""
        # 添加用户消息
        self.messages.append({"role": "user", "content": user_input})

        while True:
            yield {"type": "thinking", "content": "正在思考..."}
            start = time.time()

            # 调用 LLM
            resp = Generation.call(
                model=config.model,
                messages=self.messages,
                tools=self.tool_schemas if self.tool_schemas else None,
                result_format="message"
            )
            elapsed = time.time() - start

            if resp.status_code != 200:
                yield {"type": "error", "content": f"API 调用失败：{resp.message}"}
                return

            output = resp.output.choices[0].message

            # 检查是否需要调用工具
            # 检查是否需要调用工具
            tool_calls = output.get('tool_calls')
            if tool_calls:
                # 构建助手的 tool_calls 消息（兼容 dict 和对象）
                assistant_msg = {
                    "role": "assistant",
                    "content": output.content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"] if isinstance(tc, dict) else tc.id,
                            "type": tc["type"] if isinstance(tc, dict) else tc.type,
                            "function": {
                                "name": tc["function"]["name"] if isinstance(tc, dict) else tc.function.name,
                                "arguments": tc["function"]["arguments"] if isinstance(tc,
                                                                                       dict) else tc.function.arguments
                            }
                        } for tc in tool_calls
                    ]
                }
                self.messages.append(assistant_msg)

                # 执行每个工具调用
                for tc in tool_calls:
                    # 统一提取函数名和参数（兼容 dict 和对象）
                    if isinstance(tc, dict):
                        func_name = tc["function"]["name"]
                        func_args = json.loads(tc["function"]["arguments"])
                        tc_id = tc["id"]
                    else:
                        func_name = tc.function.name
                        func_args = json.loads(tc.function.arguments)
                        tc_id = tc.id

                    yield {
                        "type": "tool_call",
                        "name": func_name,
                        "arguments": func_args,
                        "thought": output.content or ""
                    }

                    # 实际执行工具
                    result = execute_tool(func_name, func_args)
                    yield {"type": "tool_result", "name": func_name, "content": result}

                    # 追加工具结果消息（使用统一提取的 tc_id）
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result
                    })

                continue  # 继续循环，让模型根据工具结果生成回答

            # 没有工具调用，最终回复
            final_answer = output.content
            self.messages.append({"role": "assistant", "content": final_answer})
            yield {"type": "final", "content": final_answer}
            return