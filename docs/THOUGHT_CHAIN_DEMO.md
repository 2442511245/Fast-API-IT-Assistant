# Agent 思考链可视化 — 演示文档

> 面试展示用 | 接口：`POST /agent/think` | 日期：2026-06-21

---

## 一句话说明

这是我们 Agent 的**思考链可视化**能力——Agent 的每一步推理（思考 → 调用工具 → 分析结果 → 最终回答）都有完整的结构化追踪，前端可以直接渲染成"思考过程面板"。

---

## 演示案例：排查 Pod 状态

**用户输入**：`帮我查一下 Pod 状态`

**总耗时**：14.8 秒 | **思考步骤**：8 步

### 思考链全览

| Step | 类型 | 耗时 | 说明 |
|------|------|------|------|
| 1 | 💭 思考中 | — | Agent 开始分析用户意图：需要查 K8s Pod 状态 |
| 2 | 🔧 调用工具 | — | `kubectl get pods` — 列出所有 Pod |
| 3 | 📋 工具返回 | — | 返回 5 个 Pod 状态，发现 `user-svc-jkl` 处于 CrashLoopBackOff |
| 4 | 💭 思考中 | — | Agent 发现异常 Pod，决定深入排查日志 |
| 5 | 🔧 调用工具 | — | `kubectl logs user-svc-jkl` — 查看异常 Pod 日志 |
| 6 | 📋 工具返回 | — | 日志显示 "FATAL out of memory" 和 "container terminated" |
| 7 | 💭 思考中 | — | 综合分析日志内容，定位根因 |
| 8 | ✅ 最终回答 | — | 诊断结论 + 可执行建议 |

### 第 3 步工具返回（关键数据）

```
NAME              STATUS            RESTARTS
payment-svc-abc   Running           5
payment-svc-def   Running           1
user-svc-ghi      Running           0
user-svc-jkl      CrashLoopBackOff  12    ← Agent 自动识别异常
order-svc-mno     Running           2
```

### 第 6 步工具返回（根因日志）

```
[2025-06-01 07:59:59] FATAL out of memory
[2025-06-01 08:00:00] ERROR container terminated
```

### Agent 最终回答

> `user-svc-jkl` 的日志显示它遇到了致命错误："out of memory"（内存不足），随后容器被终止。这表明该 Pod 在运行时可能没有足够的内存资源，导致崩溃。
>
> 为了解决这个问题，我们可以尝试以下步骤：
> 1. **增加内存限制**：调整 `user-svc` 的资源配置，为其分配更多的内存。
> 2. **检查内存泄漏**：调查 `user-svc` 是否存在内存泄漏问题。
> 3. **监控重启次数**：user-svc-jkl 已重启 12 次，需要关注。

---

## 技术架构

```
用户输入 "帮我查一下 Pod 状态"
        │
        ▼
┌───────────────────────────────────┐
│         POST /agent/think         │  ← 新增接口（非流式 JSON）
│         think_router.py           │
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│         AgentCore.run()           │  ← 复用现有 Agent 引擎
│    thinking → tool_call →         │
│    tool_result → final            │
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│    _build_step()                  │  ← 每个事件包装为结构化节点
│    {step, type, display, data,    │
│     timestamp, elapsed_ms}        │
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│    JSON 响应                       │
│    {question, total_steps,        │
│     chain: [...], final_answer}    │
└───────────────────────────────────┘
```

---

## API 接口

| 端点 | 方法 | 类型 | 用途 |
|------|------|------|------|
| `/agent/think` | POST | 非流式 JSON | 一次性返回完整思考链 |
| `/agent/think/stream` | POST | SSE 流式 | 逐步推送，前端动画渲染 |
| `/agent/chat/stream` | POST | SSE 流式 | 原有接口（不变） |

### 请求示例

```bash
curl -X POST http://localhost:8000/agent/think \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我查一下 Pod 状态"}'
```

### 响应结构

```json
{
  "question": "帮我查一下 Pod 状态",
  "total_steps": 8,
  "total_elapsed_ms": 14768,
  "chain": [
    {
      "step": 1,
      "type": "thinking",
      "display": {"icon": "💭", "label": "思考中", "color": "#6B7280"},
      "elapsed_ms": 0,
      "data": {"message": "正在思考..."}
    },
    {
      "step": 2,
      "type": "tool_call",
      "display": {"icon": "☸️", "label": "K8s 命令", "color": "#3B82F6", "description": "调用 K8s 命令: kubectl get pods"},
      "elapsed_ms": 0,
      "data": {
        "tool_name": "kubectl_exec",
        "tool_label": "K8s 命令",
        "arguments": {"command": "kubectl get pods"},
        "reasoning": "..."
      }
    }
    // ... 完整链路见 tests/fixtures/thought_chain_demo.json
  ],
  "final_answer": "..."
}
```

---

## 面试讲解要点

1. **可观测性**：每一步推理都有 timestamp + elapsed_ms，可以定位性能瓶颈
2. **前端友好**：`display` 字段（icon / label / color）前端直接用，无需二次映射
3. **自动化测试**：原始 JSON 存为 fixture（`tests/fixtures/thought_chain_demo.json`），CI 可以做回归对比
4. **不破坏旧接口**：`/agent/chat/stream` 保持不变，新路由独立于 `think_router.py`
5. **Agent 决策链可追溯**：你能看到 Agent 先调了什么工具、看到了什么结果、基于什么信息做出了最终判断

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `agent/think_router.py` | 新路由实现（POST /agent/think + /think/stream） |
| `agent/agent_core.py` | Agent 引擎（不变） |
| `tests/fixtures/thought_chain_demo.json` | 原始 JSON fixture，用于回归测试 |
| `main.py` | 注册 think_router |
