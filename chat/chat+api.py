import dashscope
from dashscope import Generation

with open("config.txt","r",encoding="utf-8") as f:
    dashscope.api_key = f.read().strip()

def chat_with_memory():
    messages = []
    print("🤖 通义千问AI聊天机器人（输入 quit 退出）\n")
    while True:
        user_input = input("你：")
        if user_input.lower() == "quit":
            print("👋 再见！")
            break
        messages.append({"role":"user","content":user_input})
        resp = Generation.call(
            model="qwen-max",
            messages=messages,
            result_format="message"
        )
        if resp.status_code == 200:
            res = resp.output.choices[0].message.content
            print(f"AI：{res}\n")
            messages.append({"role":"assistant","content":res})
        else:
            print("出错：",resp.message)

if __name__ == "__main__":
    chat_with_memory()