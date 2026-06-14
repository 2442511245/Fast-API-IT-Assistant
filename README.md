# AI Backend Service (RAG + Agent + Chat)

一个基于 FastAPI 的 AI 后端服务，集成 **RAG 知识库问答**、**多工具智能体**和**多轮对话**三个核心模块，并通过意图驱动的调度层实现智能路由。

## 系统架构

```mermaid
graph TD
    A[用户请求] --> B{FastAPI 入口}
    B --> C[意图识别]
    C --> D[聊天模块]
    C --> E[RAG 模块]
    C --> F[多 Agent 编排]
    D --> G[统一响应]
    E --> G
    F --> G
    G --> A
## 技术栈
FastAPI / LangChain / ChromaDB / DashScope / Docker / Railway

## 快速开始
### 1. 克隆仓库
git clone https://github.com/2442511245/Fast API-IT-Assistant.git
cd 仓库名

### 2. 安装依赖
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt

### 3. 设置环境变量
export DASHSCOPE_API_KEY="你的阿里云API Key"
# 或者创建一个 config.txt 写入 Key（仅本地开发）

### 4. 启动服务
uvicorn main:app --reload
# 访问 http://localhost:8000/docs

### 5. Docker 部署
docker build -t my-ai-backend .
docker run -p 8000:8000 -e DASHSCOPE_API_KEY="your-key" my-ai-backend

## 在线演示
部署在 Railway: [https://你的域名.railway.app/docs](https://你的域名.railway.app/docs)

## 接口说明
- `POST /rag/upload` - 上传文档构建知识库
- `POST /rag/ask` - 知识库问答
- `POST /agent/chat` - Agent 工具调用
- `POST /chat/send` - 多轮对话
- `POST /orchestrator/assist` - 意图驱动的统一入口
