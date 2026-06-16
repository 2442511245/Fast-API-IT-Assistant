from rag.core.rag import init_rag, ask_question
print(f"向量库中现有文档数: {vectorstore._collection.count()}")
# 用一个小测试文件（可以用你已有的 PDF/TXT 放进来）
test_file = "企业IT服务管理规范测试文档.txt"   # 先在根目录放一个测试文件

print("正在构建知识库...")
chain, retriever = init_rag(test_file)
print("构建完成！")

question = "你的测试问题"
answer, sources = ask_question(chain, retriever, question)
print(f"回答：{answer}")
print(f"来源：{sources}")