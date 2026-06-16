import json
import time

def save_feedback(question, answer, feedback):
    data = {
        "time": time.ctime(),
        "question": question,
        "answer": answer,
        "feedback": feedback
    }
    with open("feedback.json", "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")