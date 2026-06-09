import json
import os
from datetime import datetime
from . import register_tool
from ..config import config

@register_tool(
    name="create_ticket",
    description="创建 IT 工单，用于上报无法自动处理的问题，请求人工介入。",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "工单标题"},
            "description": {"type": "string", "description": "详细问题描述"},
            "priority": {"type": "string", "description": "优先级：low, normal, high", "default": "normal"}
        },
        "required": ["title", "description"]
    }
)
def create_ticket(title: str, description: str, priority: str = "normal") -> str:
    if config.env == "real":
        # 调用 Jira / 飞书 / 企业微信 API
        raise NotImplementedError("真实工单系统未接入")
    else:
        os.makedirs(os.path.dirname(config.tickets_path), exist_ok=True)
        tickets = []
        if os.path.exists(config.tickets_path):
            with open(config.tickets_path, "r") as f:
                content = f.read().strip()
                tickets = json.loads(content) if content else []
        ticket_id = len(tickets) + 1
        ticket = {
            "id": ticket_id,
            "title": title,
            "description": description,
            "priority": priority,
            "created_at": datetime.now().isoformat(),
            "status": "open"
        }
        tickets.append(ticket)
        with open(config.tickets_path, "w") as f:
            json.dump(tickets, f, ensure_ascii=False, indent=2)
        return f"工单 #{ticket_id} 已创建（{priority}优先级）"