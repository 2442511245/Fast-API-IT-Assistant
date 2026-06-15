# AI Backend Service (RAG + Agent + Chat)

一个基于 FastAPI 的 AI 后端服务，集成 **RAG 知识库问答**、**多工具智能体**和**多轮对话**三个核心模块，并通过意图驱动的调度层实现智能路由。

## 系统架构

```mermaid
graph TD
    A[用户请求] --> B{FastAPI 入口}
    B --> C[意图识别]
    C --> D[聊天模块]
    C --> E[RAG 模块]
    C --> F[Agent多工具调用]
    D --> G[统一响应]
    E --> G
    F --> G
    G --> A
 ```
 ## 模块架构设计

### RAG 知识检索模块

<details>
<summary>点击展开 RAG 内部流水线架构</summary>

```mermaid
graph LR
    A[文档上传] --> B[文档加载]
    B --> C[文本分割]
    C --> D[向量嵌入<br/>bge-small-zh]
    D --> E[ChromaDB 存储]

    F[用户提问] --> G[意图识别路由]
    G --> H[检索器<br/>相似度 > 0.6, top-3]
    H --> I[构造 Prompt<br/>注入检索片段]
    I --> J[LLM 生成<br/>通义千问]
    J --> K[答案输出]

    E -.-> H
    K --> L[无答案时自动创建工单]
  ```
  ### Agent多工具智能体模块
  graph TD
    subgraph 用户界面
        UI[CLI / Streamlit]
    end

    subgraph Agent 核心
        A[消息管理]
        B[System Prompt]
        C[工具调用循环]
        D[事件生成器]
    end

    subgraph 工具注册与执行
        E[装饰器自动注册]
        F[Schema 生成]
        G[统一执行入口]
    end

    subgraph 工具实现
        H[run_sql]
        I[kubectl_exec]
        J[list_k8s_resources]
        K[create_ticket]
        L[calculator]
        M[web_search]
    end

    subgraph 配置层
        N[config.yaml<br/>mock / real 切换]
    end

    UI --> A
    A --> B
    B --> C
    C --> D
    D -->|工具调用| G
    G --> E
    G --> F
    G --> H & I & J & K & L & M
    H & I & J & K & L & M --> N
    
  
## 技术栈
FastAPI / LangChain / ChromaDB / DashScope / Docker / Railway

## 快速开始
1. 克隆仓库
git clone https://github.com/2442511245/Fast API-IT-Assistant.git
cd 仓库名

2. 安装依赖
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt

3. 设置环境变量
export DASHSCOPE_API_KEY="你的阿里云API Key"
# 或者创建一个 config.txt 写入 Key（仅本地开发）

4. 启动服务
uvicorn main:app --reload
# 访问 http://localhost:8000/docs

5. Docker 部署
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
