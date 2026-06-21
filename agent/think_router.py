"""
agent/think_router.py — Agent 思考链可视化接口（新增路由，不动旧接口）

提供两个新端点：
  POST /agent/think         — 非流式，返回完整思考链 JSON（含可视化元数据）
  POST /agent/think/stream  — SSE 流式，逐步推送思考过程

思考链格式：
  每个节点包含:
    - step:         步骤序号 (1, 2, 3, ...)
    - type:         事件类型: thinking | tool_call | tool_result | final | error
    - display:      {icon, label, description} 前端渲染友好字段
    - data:         原始事件数据
    - elapsed_ms:   本步骤耗时（毫秒）
    - timestamp:    ISO 时间戳

使用方法（main.py 中新增一行，不动已有路由）：
  from agent.think_router import router as think_router
  app.include_router(think_router)   # POST /agent/think, /agent/think/stream
"""

import time as _time
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from .agent_core import AgentCore

# ---------- 新路由器（前缀 /agent，不会与旧 /agent/chat/stream 冲突）----------
router = APIRouter(prefix="/agent", tags=["Agent 思考链可视化"])

# 全局 Agent 实例（与旧路由复用同一个实例，保持消息历史一致）
agent = AgentCore()


# ---------- 请求模型 ----------
class ThinkRequest(BaseModel):
    message: str = Field(..., description="用户问题", min_length=1, max_length=4096)
    include_history: bool = Field(
        default=False,
        description="是否在返回中包含完整消息历史（用于调试）"
    )


# ---------- 思考链显示映射 ----------
DISPLAY_MAP = {
    "thinking":     {"icon": "💭", "label": "思考中",       "color": "#6B7280"},
    "tool_call":    {"icon": "🔧", "label": "调用工具",     "color": "#3B82F6"},
    "tool_result":  {"icon": "📋", "label": "工具返回",     "color": "#10B981"},
    "final":        {"icon": "✅", "label": "最终回答",     "color": "#8B5CF6"},
    "error":        {"icon": "❌", "label": "出错",         "color": "#EF4444"},
}

# 工具名称 → 友好名称映射
TOOL_DISPLAY_NAMES = {
    "run_sql":            {"icon": "📊", "label": "SQL 查询"},
    "kubectl_exec":       {"icon": "☸️", "label": "K8s 命令"},
    "list_k8s_resources": {"icon": "🔍", "label": "K8s 资源列表"},
    "create_ticket":      {"icon": "🎫", "label": "创建工单"},
    "calculator":         {"icon": "🧮", "label": "计算器"},
    "web_search":         {"icon": "🌐", "label": "网页搜索"},
}


def _build_step(
    step: int,
    event: Dict[str, Any],
    elapsed_ms: float,
    t_start: float,
) -> Dict[str, Any]:
    """将原始 Agent 事件包装为可视化思考链节点"""
    ev_type = event.get("type", "unknown")
    display = dict(DISPLAY_MAP.get(ev_type, {"icon": "❓", "label": "未知", "color": "#9CA3AF"}))

    node = {
        "step": step,
        "type": ev_type,
        "display": display,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": round(elapsed_ms),
    }

    if ev_type == "thinking":
        node["data"] = {
            "message": event.get("content", "正在思考..."),
        }

    elif ev_type == "tool_call":
        tool_name = event.get("name", "")
        tool_display = TOOL_DISPLAY_NAMES.get(tool_name, {"icon": "🔧", "label": tool_name})
        node["display"] = {
            **display,
            "icon": tool_display["icon"],
            "description": f"调用 {tool_display['label']}: {tool_name}({json.dumps(event.get('arguments', {}), ensure_ascii=False)})",
        }
        node["data"] = {
            "tool_name": tool_name,
            "tool_label": tool_display["label"],
            "arguments": event.get("arguments", {}),
            "reasoning": event.get("thought", ""),
        }

    elif ev_type == "tool_result":
        tool_name = event.get("name", "")
        tool_display = TOOL_DISPLAY_NAMES.get(tool_name, {"icon": "📋", "label": tool_name})
        raw_result = event.get("content", "")
        # 尝试解析 JSON 结果，方便前端展示
        try:
            parsed = json.loads(raw_result)
            display_result = parsed
        except (json.JSONDecodeError, TypeError):
            display_result = raw_result

        node["display"] = {
            **display,
            "description": f"{tool_display['label']} 返回结果",
        }
        node["data"] = {
            "tool_name": tool_name,
            "tool_label": tool_display["label"],
            "result_raw": raw_result,
            "result_display": display_result,
        }

    elif ev_type == "final":
        node["data"] = {
            "answer": event.get("content", ""),
        }

    elif ev_type == "error":
        node["data"] = {
            "error": event.get("content", ""),
        }

    return node


# ---------- 1. 非流式接口：POST /agent/think ----------
@router.post(
    "/think",
    response_model=None,
    summary="获取完整思考链（非流式）",
    description="执行一次 Agent 推理，返回结构化的思考链 JSON，适合前端一次性渲染思考过程面板。",
)
def agent_think(req: ThinkRequest):
    """
    返回完整思考链：
      {
        "question": "用户问题",
        "total_steps": 4,
        "total_elapsed_ms": 2340,
        "chain": [
          {step: 1, type: "thinking", display: {...}, data: {...}, ...},
          {step: 2, type: "tool_call", ...},
          {step: 3, type: "tool_result", ...},
          {step: 4, type: "final", ...},
        ],
        "final_answer": "最终回答文本",
        "history_size": 2   // (可选)消息历史条数
      }
    """
    chain: List[Dict[str, Any]] = []
    final_answer: Optional[str] = None
    t_overall_start = _time.time()
    step_counter = 0

    try:
        for event in agent.run(req.message):
            step_counter += 1
            t_step_start = _time.time()

            node = _build_step(step_counter, event, 0, t_step_start)
            chain.append(node)

            if event["type"] == "final":
                final_answer = event.get("content", "")
            elif event["type"] == "error":
                raise HTTPException(status_code=500, detail=event.get("content", "Agent 执行错误"))

            # 记录步骤耗时
            node["elapsed_ms"] = round((_time.time() - t_step_start) * 1000)

    except HTTPException:
        raise
    except Exception as e:
        chain.append({
            "step": step_counter + 1,
            "type": "error",
            "display": DISPLAY_MAP["error"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": 0,
            "data": {"error": str(e)},
        })

    total_elapsed = round((_time.time() - t_overall_start) * 1000)

    response = {
        "question": req.message,
        "total_steps": len(chain),
        "total_elapsed_ms": total_elapsed,
        "chain": chain,
        "final_answer": final_answer,
    }

    if req.include_history:
        response["history_size"] = len(agent.messages)

    return JSONResponse(content=response)


# ---------- 2. 流式接口：POST /agent/think/stream ----------
@router.post(
    "/think/stream",
    summary="获取思考链（流式 SSE）",
    description="实时推送 Agent 推理的每一步，适合前端逐步渲染思考过程动画。",
)
async def agent_think_stream(req: ThinkRequest):
    """SSE 流式推送思考链节点"""

    async def event_generator():
        t_overall_start = _time.time()
        step_counter = 0

        try:
            for event in agent.run(req.message):
                step_counter += 1
                t_start = _time.time()
                await asyncio.sleep(0)  # 让出异步控制权

                node = _build_step(step_counter, event, 0, t_start)
                node["elapsed_ms"] = round((_time.time() - t_start) * 1000)

                yield f"data: {json.dumps(node, ensure_ascii=False)}\n\n"

                if event["type"] == "error":
                    break

        except Exception as e:
            error_node = {
                "step": step_counter + 1,
                "type": "error",
                "display": DISPLAY_MAP["error"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": 0,
                "data": {"error": str(e)},
            }
            yield f"data: {json.dumps(error_node, ensure_ascii=False)}\n\n"

        total_elapsed = round((_time.time() - t_overall_start) * 1000)
        # 推送汇总元数据
        meta = {
            "step": -1,
            "type": "meta",
            "display": {"icon": "📊", "label": "汇总", "color": "#6B7280"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "total_steps": step_counter,
                "total_elapsed_ms": total_elapsed,
            },
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )
