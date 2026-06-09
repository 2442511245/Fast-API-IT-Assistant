from sentence_transformers import SentenceTransformer
# 下载到 rag/models/bge-small-zh
model = SentenceTransformer("BAAI/bge-small-zh", cache_folder="./models")
