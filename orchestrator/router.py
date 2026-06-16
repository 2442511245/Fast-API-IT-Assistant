from fastapi import APIRouter
from pydantic import BaseModel
from orchestrator.classifier import classify_intent

# 直接导入各个模块的 core 函数（本地调用）
from rag.core.rag import ask_question, init_rag
from agent.agent_core import AgentCore
from chat.router import chat_send, ChatRequest   # ← 增加导入 ChatRequest 类

router = APIRouter(prefix="/orchestrator")


class UserRequest(BaseModel):
    message: str


# 全局初始化（实际项目可用依赖注入）
rag_chain, rag_retriever = None, None
agent = AgentCore()


@router.post("/assist")
def intelligent_assist(req: UserRequest):
    intent = classify_intent(req.message)

    if intent == "chat":
        # 纯闲聊：构造 ChatRequest 对象再传入
        chat_req = ChatRequest(message=req.message)
        result = chat_send(chat_req)
        return {"intent": "chat", "result": result}

    elif intent == "rag":
        # 知识库检索
        if not rag_chain:
            return {"error": "知识库未初始化，请先上传文档"}
        answer, sources = ask_question(rag_chain, rag_retriever, req.message)
        return {"intent": "rag", "answer": answer, "sources": sources[:2]}

    elif intent == "agent":
        # 工具调用
        final_answer = ""
        for event in agent.run(req.message):
            if event["type"] == "final":
                final_answer = event["content"]
        return {"intent": "agent", "answer": final_answer}

    elif intent == "mixed":
        # 先 RAG 再 Agent 协同
        rag_answer = ""
        if rag_chain:
            rag_answer, _ = ask_question(rag_chain, rag_retriever, req.message)

        # 修正：移除多余的转义反斜杠，让 \\n 真正成为换行符
        enhanced_prompt = f"参考文档信息：{rag_answer}\n\n用户问题：{req.message}"
        final_answer = ""
        for event in agent.run(enhanced_prompt):
            if event["type"] == "final":
                final_answer = event["content"]

        return {"intent": "mixed", "rag_context": rag_answer, "final_answer": final_answer}

    # 兜底：未识别意图
    return {"intent": intent, "error": "无法识别意图，请重试"}