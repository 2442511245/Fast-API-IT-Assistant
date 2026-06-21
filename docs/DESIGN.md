# FastAPI AI 运维助手 — 技术选型设计文档

> 版本：v1.0
> 日期：2026-06-21
> 作者：2442511245
---

## 一、项目概述

### 1.1 项目定位

面向企业 IT 运维场景的智能助手后端服务，统一提供：

- **知识库问答（RAG）**：基于企业文档的精准检索与生成回答
- **自动化运维（Agent）**：模拟运维工程师的多工具调用决策链
- **多轮对话（Chat）**：通用自然语言交互
- **意图路由（Orchestrator）**：智能识别用户意图并调度到对应模块

### 1.2 核心目标

| 目标 | 说明 |
|------|------|
| 一处入口，多种能力 | 意图识别中枢自动分流，用户无需关心底层模块 |
| 知识闭环 | RAG 检索 → 回答 → 工单 → 反馈 → 知识回流 |
| 安全演示 | Agent 通过 mock/real 模式一键切换，演示零风险 |
| 容器即服务 | Dockerfile 一键部署，适配 Railway 等 PaaS 平台 |

---

## 二、总体架构

### 2.1 架构图（文字描述）

```
┌─────────────────────────────────────────────────────────┐
│                      客户端 (Web / CLI / Streamlit)       │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP / SSE
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI 入口 (main.py)                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │         意图识别调度层 (Orchestrator)               │   │
│  │         classify_intent() → chat/rag/agent/mixed   │   │
│  └────┬──────────┬──────────┬───────────────────────┘   │
│       │          │          │                            │
│       ▼          ▼          ▼                            │
│  ┌────────┐ ┌────────┐ ┌────────┐                       │
│  │ Chat   │ │  RAG   │ │ Agent  │                       │
│  │ 模块   │ │  模块  │ │  模块  │                       │
│  └────────┘ └────────┘ └────────┘                       │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                    外部服务                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │DashScope │  │ChromaDB  │  │HuggingFace (Embedding)│   │
│  │(qwen-max)│  │(向量存储) │  │(bge-small-zh)        │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 分层职责

| 层 | 目录 | 职责 |
|-----|------|------|
| 入口层 | `main.py` | FastAPI app 创建、路由注册、API Key 初始化 |
| 调度层 | `orchestrator/` | LLM 意图分类 + 请求分流 |
| 业务层 | `rag/` `agent/` `chat/` | 各自领域逻辑，独立可部署 |
| 基础设施层 | `agent/tools/` `rag/core/` | 工具注册框架、RAG 链式调用 |
| 数据层 | `chroma_db/` `data/` | 向量存储、工单/反馈 JSON 持久化 |

---

## 三、模块设计

### 3.1 RAG 模块（检索增强生成）

#### 3.1.1 数据流水线

```
文档上传 → PDF/TXT 加载 → 文本切块(500字,50重叠)
→ bge-small-zh 向量化 → ChromaDB 持久化
→ 用户提问 → 相似度检索(k=3, 阈值0.6)
→ Prompt 模板注入 → qwen-max 生成 → 返回答案
```

#### 3.1.2 核心接口

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_embedding()` | `-> HuggingFaceEmbeddings` | 全局单例，首次加载自动下载 bge-small-zh |
| `load_document(file_path)` | `-> List[Document]` | 支持 PDF (PyPDFLoader) / TXT (TextLoader) |
| `split_docs(docs, chunk_size, chunk_overlap)` | `-> List[Document]` | 递归字符分割，中文友好分隔符 |
| `build_vector_store(chunks, persist_dir)` | `-> Chroma` | 构建 ChromaDB 并持久化 |
| `get_llm()` | `-> ChatOpenAI` | DashScope 兼容 OpenAI 接口，temperature=0.1 |
| `build_rag_chain(vector_db)` | `-> Tuple[Chain, Retriever]` | LCEL 链：检索→拼接→提示→LLM→解析 |
| `init_rag(file_path)` | `-> Tuple[Chain, Retriever]` | 一站式初始化入口 |
| `ask_question(chain, retriever, question)` | `-> Tuple[str, List[Document]]` | 问答并返回来源 |

#### 3.1.3 业务闭环

- **命中**：检索到相关片段 → 生成回答 → 用户反馈（有用/无用）
- **未命中**：相似度低于 0.6 → 自动创建工单 → 记录高频问题
- **知识回流**：高质量反馈 → 整理新文档 → 重新上传入库

#### 3.1.4 技术选型理由

| 组件 | 选择 | 理由 |
|------|------|------|
| 向量数据库 | **ChromaDB** | 轻量级，零配置，Python 原生，适合中小规模知识库 |
| 嵌入模型 | **bge-small-zh** | 中文语义检索 SOTA，体积小(约100MB)，本地运行无需 GPU |
| LLM | **通义千问 qwen-max** | 中文理解能力强，DashScope API 稳定，兼容 OpenAI SDK |
| 框架 | **LangChain LCEL** | 链式声明式 API，类型安全，可组合性强 |
| 文档加载 | **PyPDFLoader + TextLoader** | LangChain 官方支持，开箱即用 |
| 切分策略 | **RecursiveCharacterTextSplitter 500/50** | 保持语义完整性，50 字重叠减少信息断裂 |

#### 3.1.5 检索策略

- **相似度阈值 0.6**：平衡召回率和精确率，低于阈值触发工单机制
- **Top-K = 3**：提供足够上下文但不超出 LLM token 限制
- **search_type = similarity_score_threshold**：仅返回高于阈值的结果，天然避免低质量幻觉

---

### 3.2 Agent 模块（多工具智能体）

#### 3.2.1 架构设计

```
┌──────────────────────────────────────┐
│           AgentCore                   │
│  ┌────────────────────────────────┐  │
│  │  System Prompt (角色+规则)      │  │
│  │  Messages History (多轮记忆)    │  │
│  │  思考-工具调用 循环             │  │
│  └──────────┬─────────────────────┘  │
│             │                         │
│  ┌──────────▼─────────────────────┐  │
│  │  事件生成器 (Generator)          │  │
│  │  thinking→tool_call→tool_result │  │
│  │  →final / error                 │  │
│  └─────────────────────────────────┘  │
└──────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│         工具框架 (tools/)              │
│  @register_tool 装饰器 → 全局注册表   │
│  JSON Schema 自动生成                 │
│  execute_tool() 统一执行入口           │
└──────────────────────────────────────┘
         │
         ├── sql_tool (SQL 查询)
         ├── k8s_tool (kubectl 操作)
         ├── ticket_tool (工单创建)
         ├── calculator_tool (计算器)
         └── search_tool (网页搜索)
```

#### 3.2.2 核心接口

| 类/函数 | 签名 | 说明 |
|---------|------|------|
| `AgentCore.__init__(system_prompt)` | 初始化消息历史+工具注册 | system_prompt 可选，默认内置 IT 运维角色 |
| `AgentCore.run(user_input)` | `-> Generator[Dict]` | 事件生成器：thinking/tool_call/tool_result/final/error |
| `register_tool(name, description, parameters)` | 装饰器工厂 | 自动注册函数并生成 OpenAI 兼容 Function Schema |
| `get_all_tool_schemas()` | `-> List[Dict]` | 返回所有注册工具的 JSON Schema |
| `execute_tool(name, arguments)` | `-> str` | 按名称执行工具，返回 JSON 字符串结果 |

#### 3.2.3 事件类型

| 事件类型 | 字段 | 说明 |
|---------|------|------|
| `thinking` | `content: str` | 模型正在思考（触发新一轮 LLM 调用前） |
| `tool_call` | `name, arguments, thought` | 模型决定调用工具，含思考过程 |
| `tool_result` | `name, content` | 工具执行返回结果 |
| `final` | `content: str` | 最终回答（模型不再调用工具） |
| `error` | `content: str` | API 调用失败 |

#### 3.2.4 环境切换设计

```yaml
# agent/config.yaml
model: "qwen-max"
env: "mock"           # mock → 模拟工具，演示零风险
db_path: "data/demo.db"
tickets_path: "data/tickets.json"
```

- **mock 模式**：所有工具使用内存模拟数据（K8s 模拟集群、SQLite 测试库）
- **real 模式**：通过 `AGENT_ENV=real` 环境变量激活真实 kubectl 调用和数据库连接
- 优先级：环境变量 `AGENT_ENV` > `config.yaml`

#### 3.2.5 技术选型理由

| 组件 | 选择 | 理由 |
|------|------|------|
| Agent 架构 | **单 Agent + Function Calling** | 运维场景工具数量有限(5个)，单 Agent 足够，避免多 Agent 通信开销 |
| LLM 调用 | **DashScope Generation.call(tools=...)** | 原生支持 Function Calling，兼容 OpenAI tool_calls 格式 |
| 工具注册 | **自研装饰器模式** | 零外部依赖，代码简洁，新增工具仅需 3 行装饰器 |
| 配置管理 | **dataclass + YAML** | 类型安全，支持环境变量覆盖，适合单文件小项目 |
| 流式输出 | **SSE (Server-Sent Events)** | 单向推送，比 WebSocket 更轻量，浏览器原生支持 |

#### 3.2.6 工具注册模式

不使用 LangChain Agent，自研轻量框架的原因：

1. **LangChain Agent 版本迭代快**：API 频繁变动，维护成本高
2. **工具数量少**：5 个工具不需要复杂的 Agent 编排
3. **完全控制**：自定义事件流格式，前端展示更灵活
4. **学习成本**：团队成员无需学习 LangChain Agent 抽象层

---

### 3.3 Chat 模块（多轮对话）

#### 3.3.1 设计

- **非流式** (`/chat/send`)：保留完整消息历史，支持多轮上下文
- **流式** (`/chat/stream`)：SSE 逐 token 推送，提升用户体验
- **模型**：qwen-max，通过 DashScope Generation API

#### 3.3.2 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/send` | POST | 非流式，消息历史累积在服务端 |
| `/chat/stream` | POST | 流式输出，无状态（每次新建消息） |

---

### 3.4 Orchestrator 模块（意图调度）

#### 3.4.1 意图分类

使用 LLM (qwen-max) 将用户输入分到四类：

| 意图 | 处理模块 | 示例 |
|------|---------|------|
| `chat` | Chat | "你好"、"今天天气怎么样" |
| `rag` | RAG | "如何重置密码？"、"公司请假流程是什么" |
| `agent` | Agent | "payment 服务最近有什么错误"、"查一下销售额" |
| `mixed` | RAG → Agent | 先查文档再执行操作 |

#### 3.4.2 调度流程

```
用户输入 → classify_intent() 返回意图标签 → 路由分发
  ├─ chat  → chat_send()
  ├─ rag   → ask_question()（需要知识库已初始化）
  ├─ agent → AgentCore.run()（提取 final 事件）
  └─ mixed → ask_question() → 结果注入 AgentCore.run()
```

#### 3.4.3 技术选型理由

使用 LLM 而非规则分类器的原因：
- 中文表达多样，规则难以覆盖
- qwen-max 对中文意图理解准确率 >95%
- 分类 prompt 极简（仅 15 行），token 消耗可忽略

---

## 四、API 设计

### 4.1 已实现接口总览

| 接口 | 方法 | 请求体 | 响应 | 说明 |
|------|------|--------|------|------|
| `/` | GET | - | `{"message": "..."}` | 健康检查 |
| `/rag/upload` | POST | `multipart/form-data` | `{"status", "filename"}` | 上传文档构建知识库 |
| `/rag/ask` | POST | `{"question": str}` | `{"answer", "sources", "auto_ticket"}` | 知识库问答 |
| `/rag/feedback` | POST | `{"question", "answer", "feedback_type"}` | `{"status"}` | 用户反馈 |
| `/rag/stats` | GET | - | `{"total", "recent"}` | 工单统计 |
| `/agent/chat/stream` | POST | `{"message": str}` | SSE 事件流 | Agent 流式推理 |
| `/chat/send` | POST | `{"message": str}` | `{"reply"}` | 非流式对话 |
| `/chat/stream` | POST | `{"message": str}` | SSE 事件流 | 流式对话 |
| `/orchestrator/assist` | POST | `{"message": str}` | `{"intent", "result"}` | 统一智能入口 |

### 4.2 错误处理

- **400**：知识库未初始化
- **500**：服务端异常（构建失败、LLM 调用失败）
- **SSE error 事件**：流式场景的 API 错误

### 4.3 Pydantic 模型

```python
class QuestionRequest(BaseModel):
    question: str

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    feedback_type: str  # "useful" | "useless"

class AgentRequest(BaseModel):
    message: str

class ChatRequest(BaseModel):
    message: str

class UserRequest(BaseModel):
    message: str
```

---

## 五、数据存储

### 5.1 存储选型

| 数据类型 | 存储方式 | 理由 |
|---------|---------|------|
| 向量嵌入 | ChromaDB（本地文件） | 零运维，适合小规模知识库 |
| 工单记录 | JSON Lines 文件 (`tickets.json`) | 简单可读，无需数据库 |
| 用户反馈 | JSON Lines 文件 (`feedback.json`) | 同上 |
| 测试数据 | SQLite (`data/demo.db`) | 模拟真实数据库，无需安装 |

### 5.2 未来演进

当数据量增长到 10 万条以上时，建议迁移路径：
- ChromaDB → **Milvus** 或 **Qdrant**（生产级向量数据库）
- JSON 文件 → **PostgreSQL**（关系型 + 全文检索）
- SQLite 模拟 → 直连企业 MySQL/PostgreSQL

---

## 六、部署架构

### 6.1 Docker 部署

```dockerfile
FROM python:3.10-slim
# 清华镜像源加速
# 端口 8000
# 支持 Railway $PORT 变量
```

### 6.2 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `DASHSCOPE_API_KEY` | 是 | 阿里云 DashScope API 密钥 |
| `AGENT_ENV` | 否 | Agent 环境切换 (mock/real)，默认 mock |
| `PORT` | 否 | Railway 部署端口，默认 8000 |

### 6.3 本地开发

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# Swagger UI: http://localhost:8000/docs
```

---

## 七、关键设计决策

### 7.1 为什么不用 LangChain Agent？

| 维度 | LangChain Agent | 自研 Agent |
|------|----------------|-----------|
| 学习成本 | 高（AgentExecutor、Tool、各种 Agent 类型） | 低（Python 生成器 + 装饰器） |
| 可控性 | 黑盒，难以定制事件流 | 完全透明，自定义事件格式 |
| 依赖 | 重（langchain + langgraph + 大量子包） | 轻（仅 DashScope SDK） |
| 适用场景 | 复杂多 Agent 编排 | 5 个工具的单 Agent |
| 版本稳定性 | API 频繁 breaking change | 自控，不受外部影响 |

### 7.2 为什么用 ChromaDB 而不用 FAISS？

- ChromaDB 内置持久化（FAISS 需额外序列化逻辑）
- ChromaDB Python 原生 API 更简洁
- 当前数据量级别（< 10 万条）ChromaDB 性能完全够用
- 内置元数据过滤，未来可扩展

### 7.3 为什么 embedding 用本地模型而不是 DashScope API？

- **成本**：免费，无 API 调用费用
- **延迟**：本地推理，无网络往返
- **隐私**：敏感文档不出服务器
- **离线可用**：不依赖外部服务

### 7.4 为什么选择 SSE 而不是 WebSocket？

- SSE 是单向推送（服务端→客户端），Agent 推理流恰好是单向的
- SSE 比 WebSocket 更轻量（HTTP 协议，无需升级握手）
- 浏览器 `EventSource` API 原生支持
- 自动重连机制

### 7.5 为什么用 DashScope 而不是直接 OpenAI？

- 阿里云国内网络延迟低（项目面向中文用户）
- 中文理解和生成能力优于 GPT-4（中文基准测试）
- 价格更低
- 兼容 OpenAI SDK 格式，迁移成本低

---

## 八、技术债务与改进方向

### 8.1 短期改进

| 问题 | 建议 |
|------|------|
| API Key 明文存储 | 迁移到环境变量 + Secret Manager |
| 全局状态 (`global_chain`) | 使用 FastAPI 依赖注入或单例模式 |
| 无单元测试 | 补充 pytest 测试（P2 计划） |
| 消息历史无限增长 | 增加滑动窗口或 token 截断 |

### 8.2 中期规划

- [ ] RAG 支持多文档、文档更新/删除
- [ ] Agent 支持更多工具（告警、日志、监控 API）
- [ ] 增加用户认证（JWT / API Key）
- [ ] 请求限流（Rate Limiting）
- [ ] 思考链可视化（Task 7）
- [ ] RAG 流式输出（Task 8）
- [ ] RAG 评估框架（Task 6）

### 8.3 长期愿景

- [ ] 多 Agent 协作（分派器 + 专业 Agent 群）
- [ ] 模型热切换（qwen-max / qwen-plus / deepseek 等）
- [ ] A/B 测试框架
- [ ] 可观测性（OpenTelemetry + 日志 + 指标面板）

---

## 九、目录结构（完整版）

```
FastAPI-IT-Assistant/
├── main.py                    # FastAPI 入口，路由注册
├── requirements.txt           # Python 依赖
├── Dockerfile                 # 生产部署镜像
├── Dockerfile.local           # 本地开发镜像（清华源）
├── config.txt                 # API Key（仅本地开发）
├── .env.txt                   # 环境变量模板
├── README.md                  # 项目说明
├── docs/                      # 文档
│   ├── DESIGN.md              # ← 本文档
│   └── SECURITY.md            # 安全设计
├── scripts/                   # 工具脚本
│   └── seed_knowledge_base.py # 知识库冷启动
├── tests/                     # 测试
│   ├── test_rag_retriever.py
│   ├── test_agent_tools.py
│   └── test_orchestrator.py
├── data/                      # 数据文件
│   └── eval_qa.json           # 评估数据集
├── rag/                       # RAG 模块
│   ├── router.py              # API 路由
│   ├── core/                  # 核心逻辑
│   │   ├── rag.py             # RAG 链
│   │   ├── ticket.py          # 工单
│   │   ├── feedback.py        # 反馈
│   │   └── stats.py           # 统计
│   └── models/                # 本地嵌入模型
├── agent/                     # Agent 模块
│   ├── router.py              # API 路由
│   ├── agent_core.py          # Agent 核心
│   ├── config.py              # 配置数据类
│   ├── config.yaml            # 配置文件
│   └── tools/                 # 工具集合
│       ├── __init__.py        # 工具框架
│       ├── sql_tool.py        # SQL 查询
│       ├── k8s_tool.py        # K8s 运维
│       ├── ticket_tool.py     # 工单创建
│       ├── calculator_tool.py # 计算器
│       └── search_tool.py     # 搜索
├── chat/                      # 对话模块
│   └── router.py              # API 路由
├── orchestrator/              # 调度模块
│   ├── router.py              # API 路由
│   └── classifier.py          # 意图分类
└── chroma_db/                 # 向量存储（持久化）
```

---

## 十、附录

### A. 参考资料

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [LangChain 文档](https://python.langchain.com/)
- [ChromaDB 文档](https://docs.trychroma.com/)
- [DashScope 文档](https://help.aliyun.com/zh/model-studio/)
- [BGE 嵌入模型](https://huggingface.co/BAAI/bge-small-zh)

### B. 术语对照

| 缩写 | 全称 | 说明 |
|------|------|------|
| RAG | Retrieval-Augmented Generation | 检索增强生成 |
| LCEL | LangChain Expression Language | LangChain 表达式语言 |
| SSE | Server-Sent Events | 服务端推送事件 |
| LLM | Large Language Model | 大语言模型 |
| K8s | Kubernetes | 容器编排平台 |
