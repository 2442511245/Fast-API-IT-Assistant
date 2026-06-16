from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .agent_core import AgentCore
import asyncio
import json

router = APIRouter(prefix="/agent")

# 全局创建一个 agent 实例（简单做法，可后续优化）
agent = AgentCore()

class AgentRequest(BaseModel):
    message: str

@router.post("/chat/stream")
async def agent_chat_stream(req: AgentRequest):
    async def event_generator():
        for event in agent.run(req.message):
            # 每个 event 是 dict，直接序列化发给前端
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)  # 让出异步控制权
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")