# rag_workflow/router.py
import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional

# 导入你原来的核心函数（路径根据实际搬过来的位置调整）
from .core.rag import init_rag, ask_question
from .core.ticket import create_ticket
from .core.feedback import save_feedback
from .core.stats import get_ticket_stats

router = APIRouter(prefix="/rag")

# ---------- 全局“状态”（模拟 Streamlit 的 st.session_state） ----------
global_chain: Optional[object] = None
global_retriever: Optional[object] = None
# 如果需要保存最后一次问答（为反馈使用），可以记录
last_interaction = {"q": None, "a": None, "sources": None}

# ---------- 请求体模型 ----------
class QuestionRequest(BaseModel):
    question: str

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    feedback_type: str  # "useful" 或 "useless"

# ---------- 1. 上传文档并构建知识库 ----------
@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    global global_chain, global_retriever
    # 保存临时文件（与原代码类似）
    suffix = file.filename.split('.')[-1]
    tmp_path = f"./tmp.{suffix}"
    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        # 调用核心初始化函数
        global_chain, global_retriever = init_rag(tmp_path)
        return {"status": "知识库构建完成", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构建失败：{str(e)}")

# ---------- 2. 提问接口 ----------
@router.post("/ask")
def ask(req: QuestionRequest):
    global global_chain, global_retriever, last_interaction
    if global_chain is None or global_retriever is None:
        raise HTTPException(status_code=400, detail="知识库未初始化，请先上传文档")
    try:
        answer, sources = ask_question(global_chain, global_retriever, req.question)
        # 记录本次交互，方便后续反馈
        last_interaction = {"q": req.question, "a": answer, "sources": sources}
        # 如果没找到来源，自动创建工单（原逻辑）
        if not sources:
            create_ticket(req.question)
        return {
            "answer": answer,
            "sources": [s.page_content[:300] for s in sources[:2]],  # 只返回片段摘要
            "auto_ticket": not sources  # 告知前端是否自动创建了工单
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- 3. 反馈接口 ----------
@router.post("/feedback")
def feedback(req: FeedbackRequest):
    save_feedback(req.question, req.answer, req.feedback_type)
    return {"status": "反馈已记录"}

# ---------- 4. 统计接口 ----------
@router.get("/stats")
def stats():
    stats = get_ticket_stats()
    return stats