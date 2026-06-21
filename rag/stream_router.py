"""
rag/stream_router.py — RAG 流式问答接口（新增路由，不动旧接口）

新增端点：
  POST /rag/ask/stream    — SSE 流式 RAG 问答

事件格式（SSE）：
  1. sources  — 检索到的来源文档摘要
  2. token    — 逐 token 输出 LLM 生成内容
  3. done     — 流结束
  4. error    — 错误信息

与旧接口的关系：
  - POST /rag/ask          保持不动（非流式）
  - POST /rag/ask/stream   新增（流式，SSE）

使用方法（main.py 中新增一行）：
  from rag.stream_router import router as rag_stream_router
  app.include_router(rag_stream_router)   # POST /rag/ask/stream
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_community.vectorstores import Chroma

from .core.rag import get_embedding, build_rag_chain

# ---------- 新路由器 ----------
router = APIRouter(prefix="/rag", tags=["RAG 流式问答"])


# ---------- 请求模型（与原有 QuestionRequest 兼容）----------
class QuestionRequest(BaseModel):
    question: str = Field(..., description="用户问题", min_length=1, max_length=4096)


# ---------- 从磁盘加载已有向量库 ----------
def _load_existing_chain(persist_dir: str = "./chroma_db"):
    """
    从已有 ChromaDB 加载向量库并构建 RAG chain。
    与 rag/router.py 的 upload → init_rag 互补：
      - upload 接口负责写入（创建/更新向量库）
      - 本接口负责读取（直接加载已有向量库）
    """
    chroma_dir = Path(persist_dir)
    if not chroma_dir.exists():
        raise FileNotFoundError(
            f"向量库目录不存在：{persist_dir}。请先通过 POST /rag/upload 上传文档构建知识库。"
        )

    embedding = get_embedding()
    db = Chroma(
        persist_directory=str(persist_dir),
        embedding_function=embedding,
    )
    chain, retriever = build_rag_chain(db)
    return chain, retriever


# ---------- POST /rag/ask/stream ----------
@router.post(
    "/ask/stream",
    summary="流式 RAG 问答（SSE）",
    description=(
        "基于已有知识库进行流式问答。"
        "先返回检索到的来源文档，再逐 token 输出 LLM 生成内容。"
    ),
)
async def rag_ask_stream(req: QuestionRequest):
    """
    SSE 事件流格式：
      {"type": "sources", "data": ["片段1", "片段2"]}
      {"type": "token",   "content": "Nginx"}
      {"type": "token",   "content": "的"}
      ...
      {"type": "done"}
      [DONE]
    """

    # 校验向量库是否就绪
    try:
        chain, retriever = _load_existing_chain()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"知识库加载失败：{str(e)}")

    async def event_generator():
        try:
            # --- 阶段 1：检索来源 ---
            sources = retriever.invoke(req.question)

            if sources:
                source_data = [s.page_content[:300] for s in sources[:3]]
                yield f"data: {json.dumps({'type': 'sources', 'data': source_data, 'count': len(source_data)}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
            else:
                # 无来源也通知前端
                yield f"data: {json.dumps({'type': 'sources', 'data': [], 'count': 0, 'note': '未找到相关知识，已自动创建工单'}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)

            # --- 阶段 2：流式生成 ---
            full_answer = ""
            for chunk in chain.stream(req.question):
                full_answer += chunk
                yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)  # 模拟流式节奏

            # --- 阶段 3：完成 ---
            yield f"data: {json.dumps({'type': 'done', 'full_length': len(full_answer)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
