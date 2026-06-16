import json
import time

def create_ticket(question):
    ticket = {
        "time": time.ctime(),
        "question": question,
        "status": "pending"
    }
    with open("tickets.json", "a", encoding="utf-8") as f:
        f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    return "✅ 已创建IT工单"