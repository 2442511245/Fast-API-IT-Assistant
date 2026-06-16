import dashscope
from dashscope import Generation

INTENT_PROMPT = """你是一个意图分类器。根据用户输入，判断意图属于以下哪一类：
- chat：普通闲聊、问候、无关技术的问题
- rag：询问文档内容、知识库问题、IT流程、内部规定
- agent：需要执行具体操作（查数据库、查K8s、创建工单、计算、搜索）
- mixed：既需要查文档，又需要执行操作

只返回一个单词：chat、rag、agent 或 mixed。

示例：
"你好" → chat
"如何重置密码？" → rag
"payment服务最近有什么错误？" → agent
"payment服务最近有什么错误？先查文档看有没有相关记录" → mixed
"""

def classify_intent(user_input: str) -> str:
    resp = Generation.call(
        model="qwen-max",
        messages=[
            {"role": "system", "content": INTENT_PROMPT},
            {"role": "user", "content": user_input}
        ],
        result_format="message"
    )
    if resp.status_code == 200:
        intent = resp.output.choices[0].message.content.strip().lower()
        return intent if intent in ["chat", "rag", "agent", "mixed"] else "chat"
    return "chat"