import json

def get_ticket_stats():
    try:
        with open("tickets.json", encoding="utf-8") as f:
            tickets = [json.loads(line) for line in f if line.strip()]
    except:
        tickets = []
    return {
        "total": len(tickets),
        "recent": [t["question"] for t in tickets[-5:]]
    }