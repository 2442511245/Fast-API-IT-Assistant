from fastapi import FastAPI

# 导入各个插头的路由
from rag.router import router as rag_router
from agent.router import router as agent_router
from chat.router import router as chat_router
from orchestrator.router import router as orch_router


# 将来还有 cli_chat 或别的模块，继续加

import os
import dashscope

# 优先从环境变量读取，读不到再用 config.txt 兜底（方便本地开发）
api_key = os.getenv("DASHSCOPE_API_KEY")
if api_key:
    dashscope.api_key = api_key
else:
    try:
        with open("config.txt", "r", encoding="utf-8") as f:
            dashscope.api_key = f.read().strip()
    except FileNotFoundError:
        print("警告：未找到 config.txt，也未设置环境变量 DASHSCOPE_API_KEY")
app = FastAPI()

# 把所有插头插上
app.include_router(rag_router)      # 所有 /rag/... 的接口
app.include_router(agent_router)    # 所有 /agent/... 的接口
app.include_router(chat_router)    # 所有 /chat/... 的接口
app.include_router(orch_router)
# 保留一个根路径测试，证明服务在跑
@app.get("/")
def root():
    return {"message": "AI 后端已启动，包含 RAG 和 Agent 和chat模块"}