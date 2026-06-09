# core/rag.py
import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough



# ---------- 1. 全局初始化 embedding（避免重复加载） ----------
from pathlib import Path
from langchain_community.embeddings import HuggingFaceEmbeddings

EMBEDDING = None

def get_embedding():
    global EMBEDDING
    if EMBEDDING is None:
        current_dir = Path(__file__).parent.resolve()          # rag/core/
        model_dir = current_dir.parent / "models" / "bge-small-zh"
        model_dir = model_dir.resolve()

        if not model_dir.exists():
            print("本地模型不存在，正在从 Hugging Face 下载...")
            from sentence_transformers import SentenceTransformer
            # 下载到 rag/models/ 下面，会自动创建 bge-small-zh 文件夹
            SentenceTransformer("BAAI/bge-small-zh", cache_folder=str(model_dir.parent))
            print("下载完成。")

        print("正在加载 Embedding 模型...")
        EMBEDDING = HuggingFaceEmbeddings(
            model_name=str(model_dir),
            model_kwargs={'device': 'cpu', 'local_files_only': True},
            encode_kwargs={'normalize_embeddings': True}
        )
        print("模型加载完成。")
    return EMBEDDING

# ---------- 2. 加载文档 ----------
def load_document(file_path):
    if file_path.endswith(".pdf"):
        loader = PyPDFLoader(file_path)
    elif file_path.endswith(".txt"):
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError("不支持的文件格式，请上传 .pdf 或 .txt 文件")
    return loader.load()

# ---------- 3. 文本分块 ----------
def split_docs(docs, chunk_size=500, chunk_overlap=50):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\\\\n\\\\n", "\\\\n", "。", "？", "！"]
    )
    return splitter.split_documents(docs)

# ---------- 4. 构建向量库 ----------
def build_vector_store(chunks, persist_dir="./chroma_db"):
    db = Chroma.from_documents(
        documents=chunks,
        embedding=get_embedding(),
        persist_directory=persist_dir
    )
    # db.persist()  # 新版 Chroma 自动持久化，可省略
    return db

# ---------- 5. 大模型（通义千问） ----------
def get_llm():
    return ChatOpenAI(
        model="qwen-max",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.1
    )

# ---------- 6. RAG 链（LCEL） ----------
def build_rag_chain(vector_db):
    # 注意：必须设置 search_type 才能启用 score_threshold
    retriever = vector_db.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={"k": 3, "score_threshold": 0.6}
    )
    llm = get_llm()

    template = """你是企业IT智能助手，只能基于以下上下文回答问题。如果上下文里没有答案，直接说“无法从知识库中找到答案，已自动创建工单”。

上下文：{context}
问题：{question}
"""
    prompt = ChatPromptTemplate.from_template(template)

    # 构建链：检索 -> 拼接上下文 -> 提问
    rag_chain = (
        {"context": retriever | (lambda docs: "\\\\n\\\\n".join(doc.page_content for doc in docs)),
         "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return rag_chain, retriever

# ---------- 7. 对外接口 ----------
def init_rag(file_path):
    docs = load_document(file_path)
    chunks = split_docs(docs)
    db = build_vector_store(chunks)
    chain, retriever = build_rag_chain(db)
    return chain, retriever

def ask_question(chain, retriever, question):
    answer = chain.invoke(question)
    sources = retriever.invoke(question)
    return answer, sources