from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import dashscope
from dashscope import Generation
import asyncio
import json

router = APIRouter(prefix="/chat")

# 请求体模型
class ChatRequest(BaseModel):
    message: str

# 非流式接口（保留多轮记忆的简单版本）
messages_history = []

@router.post("/send")
def chat_send(req: ChatRequest):
    messages_history.append({"role": "user", "content": req.message})
    resp = Generation.call(
        model="qwen-max",
        messages=messages_history,
        result_format="message"
    )
    if resp.status_code == 200:
        reply = resp.output.choices[0].message.content
        messages_history.append({"role": "assistant", "content": reply})
        return {"reply": reply}
    else:
        return {"error": resp.message}

# 流式接口
@router.post("/stream")
async def chat_stream(req: ChatRequest):
    messages_local = [{"role": "user", "content": req.message}]

    async def event_gen():
        resp = Generation.call(
            model="qwen-max",
            messages=messages_local,
            stream=True,
            result_format="message"
        )
        for chunk in resp:
            if chunk.status_code == 200:
                content = chunk.output.choices[0].message.content
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\\n\\n"
                await asyncio.sleep(0.01)
            else:
                yield f"data: {json.dumps({'error': chunk.message})}\\n\\n"
        yield "data: [DONE]\\n\\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")