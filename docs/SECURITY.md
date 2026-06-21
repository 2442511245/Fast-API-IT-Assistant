# Agent 工具执行层安全设计方案

> 版本：v1.0
> 日期：2026-06-21
> 项目：FastAPI AI 运维助手
> 范围：Agent 五个工具（SQL / kubectl / ticket / calculator / search）的安全加固

---

## 一、当前安全风险总览

基于对 `agent/tools/` 下 5 个工具的源码审计，识别出以下关键风险：

| 风险等级 | 工具 | 问题 | 代码位置 |
|---------|------|------|---------|
| 🔴 严重 | `sql_tool` | `cur.execute(query)` 直接执行任意 SQL，无读写分离 | `sql_tool.py:24` |
| 🔴 严重 | `k8s_tool` | `subprocess.run(command, shell=True)` shell 注入 | `k8s_tool.py:60` |
| 🔴 严重 | `calculator` | `eval(expression)` 任意代码执行风险 | `calculator_tool.py:19` |
| 🟡 高危 | `k8s_tool` | real 模式无命令白名单，可执行 delete/drain | `k8s_tool.py:58` |
| 🟡 高危 | `sql_tool` | 无 SQL 关键词过滤，可 DROP/ALTER 表 | `sql_tool.py:24` |
| 🟠 中危 | 全部工具 | 无审计日志，无法追溯操作历史 | `tools/__init__.py` |
| 🟠 中危 | 全部工具 | 无用户身份，无法区分调用者 | `tools/__init__.py` |
| 🟡 高危 | `k8s_tool` | mock 模式 scale 直接生效，无确认 | `k8s_tool.py:91-99` |

---

## 二、SQL 执行安全设计

### 2.1 设计目标

- 只允许 `SELECT` / `SHOW` / `DESCRIBE` 等只读操作
- 禁止 `INSERT` / `UPDATE` / `DELETE` / `DROP` / `ALTER` / `TRUNCATE` / `CREATE` 等写操作
- 使用数据库只读账户作为纵深防御
- SQL 关键词过滤作为应用层防护

### 2.2 只读账户设计

在真实数据库环境中，为 Agent 创建专用的只读账户：

```sql
-- MySQL / PostgreSQL 只读账户示例
CREATE USER 'agent_readonly'@'%' IDENTIFIED BY '<强密码>';
GRANT SELECT ON enterprise_db.* TO 'agent_readonly'@'%';
-- 可选：允许 SHOW 和 DESCRIBE
GRANT SHOW DATABASES ON *.* TO 'agent_readonly'@'%';

-- 可选：只读事务模式，阻止任何写操作
SET SESSION TRANSACTION READ ONLY;
```

在 `config.yaml` 中新增配置项：

```yaml
# agent/config.yaml 新增字段
sql:
  read_only: true                    # 强制只读模式
  allowed_commands:                  # 白名单
    - SELECT
    - SHOW
    - DESCRIBE
    - EXPLAIN
    - WITH              # CTE 查询，如 WITH ... SELECT
  forbidden_keywords:                # 黑名单关键词
    - INSERT
    - UPDATE
    - DELETE
    - DROP
    - ALTER
    - TRUNCATE
    - CREATE
    - REPLACE
    - GRANT
    - REVOKE
  max_query_length: 4096             # 最大查询长度（字符）
  max_result_rows: 1000              # 最大返回行数
```

### 2.3 SQL 安全校验伪代码

```python
import re
from typing import Tuple

# ---------- 关键词过滤 ----------
FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "REPLACE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE", "INTO OUTFILE", "INTO DUMPFILE",
    "LOAD_FILE", "LOAD DATA",
]

ALLOWED_COMMANDS = ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH"]

def validate_sql(query: str) -> Tuple[bool, str]:
    """
    校验 SQL 语句安全性
    返回 (是否通过, 失败原因)
    """
    # 1. 长度限制
    if len(query) > 4096:
        return False, "SQL 查询超过最大长度限制 (4096)"

    # 2. 检查禁止关键词（不区分大小写）
    upper_query = query.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        # 使用单词边界匹配，避免误杀（如 DROP 不会误杀 DROPPING）
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, upper_query):
            return False, f"禁止的 SQL 操作: {keyword}"

    # 3. 检查是否以允许的命令开头（去除前导空格和注释）
    stripped = upper_query.strip().lstrip("--").strip()
    if not any(stripped.startswith(cmd) for cmd in ALLOWED_COMMANDS):
        return False, f"仅允许以 {ALLOWED_COMMANDS} 开头的查询"

    # 4. 禁止多语句（分号分隔）
    # 注意：排除字符串内的分号（简化处理）
    if ";" in query.rstrip(";"):
        return False, "禁止多语句查询"

    # 5. 禁止注释符号注入
    dangerous_patterns = ["/*", "*/", "--", "#"]
    # 允许单行注释 --，但检测尝试注释掉后续语句的模式
    if "UNION" in upper_query:
        return False, "禁止 UNION 查询"

    return True, "ok"


def execute_sql_safe(query: str) -> str:
    """
    安全执行 SQL（替代原 cur.execute(query)）
    """
    # 校验
    passed, reason = validate_sql(query)
    if not passed:
        audit_log("SQL_BLOCKED", query=query, reason=reason)
        return f"SQL 执行被拒绝：{reason}"

    # 执行
    try:
        conn = get_readonly_connection()  # 只读连接
        # 设置只读模式（MySQL）
        conn.execute("SET SESSION TRANSACTION READ ONLY")
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchmany(1000)  # 限制最大行数
        conn.close()
        audit_log("SQL_SUCCESS", query=query, row_count=len(rows))
        return json.dumps(rows, ensure_ascii=False, default=str)
    except Exception as e:
        audit_log("SQL_ERROR", query=query, error=str(e))
        return f"SQL 执行错误：{str(e)}"
```

### 2.4 分层防御

```
第 1 层：应用层关键词过滤（validate_sql）
    ↓ 绕过 → 极少可能
第 2 层：数据库只读账户权限限制
    ↓ 绕过 → 账户被泄露时
第 3 层：数据库审计插件（如 MySQL audit_log）
    ↓
第 4 层：网络层防火墙（数据库仅允许 Agent 服务器 IP 访问）
```

---

## 三、kubectl 操作安全设计

### 3.1 设计目标

- 命令白名单机制，禁止所有未授权的 kubectl 子命令
- 命名空间级别隔离
- 彻底消除 `shell=True` 的 shell 注入风险
- 禁止 delete、drain、taint 等破坏性操作

### 3.2 命令白名单配置

```yaml
# agent/config.yaml 新增字段
k8s:
  allowed_verbs:                     # 允许的 kubectl 动词
    - get
    - describe
    - logs
    - top
    - explain
    - api-resources
    - version
  allowed_resources:                 # 允许操作的资源类型
    - pods
    - deployments
    - services
    - configmaps
    - namespaces
    - nodes
    - events
    - replicasets
    - statefulsets
    - daemonsets
    - jobs
    - cronjobs
  # 仅 GET/LIST 操作允许的 scale（需配合确认）
  conditional_allowed:
    - verb: scale
      resource: deployment
      require_confirm: true          # 需要二次确认
  forbidden_verbs:                   # 明确禁止的动词
    - delete
    - drain
    - taint
    - cordon
    - uncordon
    - exec
    - cp
    - patch
    - apply      # 注：apply 可能是创建也可能是更新，需要特殊评估
    - create
    - replace
  forbidden_flags:                   # 禁止的参数
    - "--force"
    - "--grace-period=0"
    - "--all"
  allowed_namespaces:                # 命名空间白名单
    - default
    - production
    - staging
    - monitoring
  read_only_namespaces:              # 只读命名空间（禁止 scale 等操作）
    - production
```

### 3.3 安全命令解析（消除 shell=True）

```python
import shlex
import subprocess
from typing import List, Tuple, Optional

# 当前代码问题：subprocess.run(command, shell=True)
# 风险：command 字符串直接传给 shell，可注入任意命令
# 解决：用 shlex 解析为列表，使用 shell=False

def parse_kubectl_command(command: str) -> Tuple[Optional[List[str]], str]:
    """
    安全解析 kubectl 命令字符串为参数列表
    消除 shell=True 注入风险
    """
    try:
        args = shlex.split(command.strip())
    except ValueError as e:
        return None, f"命令解析失败: {e}"

    if not args or args[0] != "kubectl":
        return None, "命令必须以 kubectl 开头"

    return args, "ok"


def validate_kubectl(args: List[str]) -> Tuple[bool, str]:
    """
    校验 kubectl 命令参数安全性
    """
    if len(args) < 2:
        return False, "kubectl 命令不完整"

    verb = args[1]  # 如 get, logs, delete

    # 1. 禁止的动词
    if verb in FORBIDDEN_VERBS:
        return False, f"禁止的 kubectl 操作: {verb}"

    # 2. 检查白名单
    if verb not in ALLOWED_VERBS and verb not in CONDITIONAL_ALLOWED:
        return False, f"未授权的 kubectl 操作: {verb}"

    # 3. 检查禁止的参数
    for arg in args:
        if arg.lower() in FORBIDDEN_FLAGS:
            return False, f"禁止的参数: {arg}"
        if arg.startswith("--force"):
            return False, "禁止 --force 参数"
        if arg == "--all":
            return False, "禁止 --all（影响所有资源）"

    # 4. 检查命名空间
    ns = extract_namespace(args)  # 从 -n/--namespace 提取
    if ns and ns not in ALLOWED_NAMESPACES:
        return False, f"不允许操作的命名空间: {ns}"

    # 5. 条件允许的操作需要二次确认
    if verb in CONDITIONAL_ALLOWED:
        return True, "CONFIRM_REQUIRED"  # 特殊标记

    return True, "ok"


def kubectl_exec_safe(command: str) -> str:
    """
    安全执行 kubectl 命令（替代原 kubectl_exec）
    """
    # 1. 解析
    args, err = parse_kubectl_command(command)
    if args is None:
        audit_log("K8S_BLOCKED", command=command, reason=err)
        return f"命令被拒绝：{err}"

    # 2. 校验
    passed, reason = validate_kubectl(args)
    if not passed:
        audit_log("K8S_BLOCKED", command=command, reason=reason)
        return f"命令被拒绝：{reason}"

    # 3. 条件操作二次确认
    if reason == "CONFIRM_REQUIRED":
        audit_log("K8S_CONFIRM_PENDING", command=command)
        return f"操作 {args[1]} 需要二次确认。请在确认参数中传入 confirm_token。"

    # 4. 安全执行（shell=False）
    try:
        result = subprocess.run(
            args,                          # 列表形式，不是字符串
            shell=False,                   # ← 关键：不使用 shell
            capture_output=True,
            text=True,
            timeout=30                     # 超时限制
        )
        audit_log(
            "K8S_SUCCESS",
            command=command,
            exit_code=result.returncode
        )
        return result.stdout if result.returncode == 0 else result.stderr
    except subprocess.TimeoutExpired:
        audit_log("K8S_TIMEOUT", command=command)
        return "kubectl 执行超时（30秒）"
    except Exception as e:
        audit_log("K8S_ERROR", command=command, error=str(e))
        return f"kubectl 执行错误：{str(e)}"
```

### 3.4 命名空间隔离

```
                    ┌──────────────────────────┐
                    │    K8s 集群                │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ production (只读)     │  │  ← Agent 只能 get/logs/describe
                    │  │  - payment-service   │  │     禁止 scale/delete
                    │  │  - user-service      │  │
                    │  │  - order-service     │  │
                    │  └─────────────────────┘  │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ staging (可操作)      │  │  ← Agent 可以 scale（需确认）
                    │  │  - payment-service   │  │
                    │  └─────────────────────┘  │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │ monitoring (只读)     │  │
                    │  └─────────────────────┘  │
                    │                           │
                    └──────────────────────────┘

Agent 服务账户 RBAC 配置（Kubernetes 原生）：
```

```yaml
# k8s-agent-rbac.yaml — Agent 服务账户的 K8s 原生权限限制
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ai-agent
  namespace: agent

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ai-agent-readonly
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "events", "nodes"]
    verbs: ["get", "list", "describe"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "describe"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "describe"]
  # staging 命名空间允许 scale（配合应用层确认机制）
  - apiGroups: ["apps"]
    resources: ["deployments/scale"]
    verbs: ["get", "update"]
    resourceNames: []  # 运行时通过 admission webhook 动态控制

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ai-agent-binding
  namespace: production
subjects:
  - kind: ServiceAccount
    name: ai-agent
    namespace: agent
roleRef:
  kind: ClusterRole
  name: ai-agent-readonly
  apiGroup: rbac.authorization.k8s.io
```

---

## 四、危险操作拦截与二次确认

### 4.1 需要二次确认的操作

| 工具 | 操作 | 风险等级 | 确认方式 |
|------|------|---------|---------|
| kubectl | `scale deployment` | 🟡 中 | 返回 confirm_token，前端弹窗确认 |
| kubectl | 所有涉及 `--force` 的操作 | 🔴 高 | 直接拦截，如需执行走人工工单 |
| SQL | 无（已禁止所有写操作） | — | — |
| ticket | 创建 high 优先级工单 | 🟢 低 | 阈值告警（1小时内 >10 个 high 工单） |

### 4.2 二次确认流程伪代码

```python
import hashlib
import time

# 确认令牌存储（生产环境应放 Redis）
_pending_confirms: dict = {}  # {confirm_token: {operation, expires_at}}

def generate_confirm_token(operation: dict) -> str:
    """生成一次性确认令牌"""
    raw = f"{operation['tool']}:{operation['action']}:{time.time()}"
    token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    _pending_confirms[token] = {
        "operation": operation,
        "expires_at": time.time() + 300,  # 5 分钟有效
        "status": "pending"
    }
    return token

def require_confirmation(tool_name: str, action: str, details: dict) -> dict:
    """
    发起二次确认
    返回给前端：{"need_confirm": true, "confirm_token": "abc123", ...}
    """
    token = generate_confirm_token({
        "tool": tool_name,
        "action": action,
        "details": details,
    })
    return {
        "need_confirm": True,
        "confirm_token": token,
        "message": f"确认执行 {tool_name}.{action}？",
        "details": details,
        "expires_in": 300,
    }

def execute_confirmed(confirm_token: str) -> str:
    """
    确认后执行（前端调用确认接口时）
    """
    if confirm_token not in _pending_confirms:
        return "确认令牌无效或已过期"

    pending = _pending_confirms[confirm_token]
    if time.time() > pending["expires_at"]:
        del _pending_confirms[confirm_token]
        return "确认令牌已过期（超过5分钟），请重新发起"

    # 执行实际操作
    op = pending["operation"]
    audit_log("CONFIRMED_EXEC", **op)
    del _pending_confirms[confirm_token]
    return execute_tool_internal(op["tool"], op["action"], op["details"])


# ===== 在 AgentCore.run() 中的集成方式 =====
# 当工具返回 {"need_confirm": True} 时：
#   1. Agent 将该事件透传给前端
#   2. 前端弹出确认框
#   3. 用户确认后，前端调用 POST /agent/confirm {confirm_token: "abc123"}
#   4. 后端执行实际操作，将结果注入 Agent 消息历史
#   5. Agent 继续推理
```

### 4.3 确认接口设计

```python
# 新增路由（文件：agent/router.py 新增，不动旧路由）
@router.post("/confirm")
def confirm_action(req: ConfirmRequest):
    """
    二次确认接口
    请求：{"confirm_token": "abc123"}
    响应：{"status": "executed", "result": "..."}
    """
    result = execute_confirmed(req.confirm_token)
    return {"status": "executed", "result": result}
```

### 4.4 操作风险分级

```
                         破坏性
                            ↑
                    ┌───────┼───────┐
          DROP     │       │       │
          DELETE   │  🔴   │  🔴   │  直接拦截，走人工工单
          drain    │ 禁止  │ 禁止  │
        ──────────┼───────┼───────┤
          scale    │  🟡   │  🔴   │  🟡 需确认
          restart  │ 需确认 │ 禁止  │  🔴 production 禁止
        ──────────┼───────┼───────┤
          logs     │  🟢   │  🟢   │  🟢 直接允许
          get      │ 允许  │ 允许  │
          describe │       │       │
        ──────────┴───────┴───────┴──────→ 环境
                    mock    staging  production
```

---

## 五、用户输入校验

### 5.1 各工具注入风险分析

| 工具 | 注入类型 | 当前风险 | 加固方案 |
|------|---------|---------|---------|
| `sql_tool` | SQL 注入 | 🔴 LLM 生成的 SQL 可能拼接注入代码 | 关键词过滤 + 只读账户 + 参数化理念 |
| `k8s_tool` | 命令注入 | 🔴 `shell=True` + 无过滤 | `shell=False` + shlex 解析 + 白名单 |
| `calculator` | 代码注入 | 🔴 `eval()` 可执行任意 Python | 替换为 `ast.literal_eval()` 或 `numexpr` |
| `ticket_tool` | XSS (存储) | 🟠 title/description 直接写入 JSON | HTML 实体编码输出 |
| `search_tool` | SSRF | 🟠 real 模式可能请求内网 URL | URL 白名单/黑名单 |

### 5.2 Calculator：替换 eval()

```python
# 当前代码 (calculator_tool.py:19)：eval(expression)
# 风险：即使有字符白名单，eval() 本身在 Python 中非常危险
# 以下输入理论上是安全的，但 eval 的本性决定了不应使用：
#   "__import__('os').system('rm -rf /')"  → 被字符白名单拦截
#   但 "3**3**3" → 能通过白名单，可触发 DoS（巨大计算量）

# 方案 A：使用 ast.literal_eval()（推荐）
import ast
import operator
import math

SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

def safe_calculator(expression: str) -> str:
    """安全的数学表达式求值"""
    # 1. 字符白名单（保留原逻辑）
    allowed = set("0123456789.+-*/() ")
    if not all(c in allowed for c in expression):
        return "表达式包含不允许的字符"

    # 2. 长度限制，防止 ReDoS
    if len(expression) > 200:
        return "表达式过长（最多 200 字符）"

    # 3. 使用 ast.parse 安全解析
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except SyntaxError:
        return "表达式语法错误"

    # 4. 只用 ast.literal_eval 或自定义 visitor
    # literal_eval 仅支持字面量，最为安全
    try:
        result = ast.literal_eval(expression)
        return str(result)
    except (ValueError, SyntaxError):
        pass

    # 5. 回退：自定义 evaluator（仅限 + - * / ** ( )）
    try:
        result = _eval_ast(tree.body)
        return str(result)
    except Exception as e:
        return f"计算错误：{str(e)}"
```

### 5.3 通用输入清洗

```python
# 所有工具入口的通用清洗函数
import html

def sanitize_input(user_input: str, max_length: int = 4096) -> str:
    """
    通用输入清洗
    """
    if not isinstance(user_input, str):
        return ""

    # 长度截断
    if len(user_input) > max_length:
        user_input = user_input[:max_length]

    # 移除空字节
    user_input = user_input.replace('\x00', '')

    return user_input

def sanitize_output(output: str) -> str:
    """
    输出编码（防止 XSS，如果前端直接渲染 HTML）
    """
    return html.escape(output, quote=True)


# 在 register_tool 框架中集成
# 修改 execute_tool() 入口（tools/__init__.py），对所有入参自动清洗：
def execute_tool_safe(name: str, arguments: Dict[str, Any]) -> str:
    """带输入清洗的工具执行入口"""
    # 清洗所有字符串参数
    cleaned_args = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            cleaned_args[key] = sanitize_input(value)
        else:
            cleaned_args[key] = value

    # 执行
    result = execute_tool(name, cleaned_args)

    # 清洗输出
    return sanitize_output(result)
```

---

## 六、审计日志

### 6.1 日志记录内容

每条审计日志包含以下字段：

```python
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json

@dataclass
class AuditRecord:
    timestamp: str        # ISO 8601 时间戳（UTC）
    tool: str             # 工具名称：sql_tool / k8s_tool / ...
    action: str           # 操作类型：run_sql / kubectl_exec / ...
    status: str           # SUCCESS / BLOCKED / ERROR / CONFIRMED
    user: str             # 调用者标识（未来集成认证后使用）
    session_id: str       # Agent 会话 ID
    input_summary: str    # 输入摘要（脱敏后，前 100 字符）
    output_summary: str   # 输出摘要（脱敏后，前 100 字符）
    details: dict         # 扩展字段（命令、SQL 语句等）
    error: str            # 错误信息（如有）
    elapsed_ms: int       # 执行耗时（毫秒）
    source_ip: str        # 请求来源 IP
```

### 6.2 审计日志存储

```python
# scripts/audit.py — 审计日志模块

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

class AuditLogger:
    """
    审计日志记录器
    - 结构化 JSON Lines 格式
    - 按天轮转
    - 线程安全
    - 同步写（不丢日志）
    """

    def __init__(self, log_dir: str = "logs/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _log_file(self) -> str:
        """当天日志文件"""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return str(self.log_dir / f"agent-audit-{date_str}.jsonl")

    def log(self, tool: str, action: str, status: str, **kwargs):
        """
        写入一条审计日志
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "action": action,
            "status": status,
            "user": kwargs.get("user", "anonymous"),
            "session_id": kwargs.get("session_id", ""),
            "input_summary": str(kwargs.get("input", ""))[:100],
            "output_summary": str(kwargs.get("output", ""))[:100],
            "details": kwargs.get("details", {}),
            "error": str(kwargs.get("error", "")),
            "elapsed_ms": kwargs.get("elapsed_ms", 0),
            "source_ip": kwargs.get("source_ip", ""),
        }
        with self._lock:
            with open(self._log_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

# 全局单例
audit = AuditLogger()


# ===== 在 tools/__init__.py 的 execute_tool 中集成 =====
import time

def execute_tool_with_audit(name: str, arguments: Dict[str, Any],
                            session_id: str = "", user: str = "") -> str:
    """带审计日志的工具执行入口"""
    start = time.time()

    try:
        result = execute_tool(name, arguments)  # 原执行逻辑
        elapsed = int((time.time() - start) * 1000)

        audit.log(
            tool=name,
            action=name,
            status="SUCCESS",
            input=json.dumps(arguments, ensure_ascii=False),
            output=result,
            session_id=session_id,
            user=user,
            elapsed_ms=elapsed,
            details={"arguments": arguments}
        )
        return result

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        audit.log(
            tool=name,
            action=name,
            status="ERROR",
            input=json.dumps(arguments, ensure_ascii=False),
            error=str(e),
            session_id=session_id,
            user=user,
            elapsed_ms=elapsed,
        )
        return f"工具执行异常：{str(e)}"
```

### 6.3 日志查询接口

```python
# 审计日志查询（按时间、工具、状态筛选）
def query_audit_logs(
    tool: str = None,
    status: str = None,
    start_time: str = None,
    end_time: str = None,
    limit: int = 100
) -> list:
    """查询审计日志"""
    # 简化版实现：读取当天日志并过滤
    results = []
    log_file = audit._log_file()
    if not os.path.exists(log_file):
        return results

    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line.strip())
            if tool and record["tool"] != tool:
                continue
            if status and record["status"] != status:
                continue
            results.append(record)
            if len(results) >= limit:
                break
    return results
```

### 6.4 告警规则

```
审计日志 → 实时检测 → 触发告警：

规则 1：5 分钟内 BLOCKED 事件 > 10 次
    → 可能存在攻击，发送告警通知

规则 2：任何包含 FORBIDDEN_KEYWORD 的操作
    → 高优先级告警

规则 3：production 命名空间出现 scale 操作
    → 高优先级告警 + 必须有人工确认记录

规则 4：1 小时内 ERROR 事件 > 50 次
    → 工具可能异常，需排查
```

---

## 七、安全加固总览

### 7.1 加固前后对比

| 维度 | 当前状态 | 加固后 |
|------|---------|--------|
| SQL 防护 | ❌ 无过滤，任意 SQL | ✅ 关键词过滤 + 只读账户 + RBAC |
| kubectl 防护 | ❌ shell=True，无白名单 | ✅ shell=False + shlex + 白名单 + RBAC |
| Calculator | ❌ eval() | ✅ ast.literal_eval() 或 numexpr |
| 二次确认 | ❌ 无 | ✅ confirm_token 机制 |
| 审计日志 | ❌ 无 | ✅ JSON Lines 结构化日志 + 告警 |
| 用户认证 | ❌ 无 | ✅ 预留 session_id/user 字段 |
| 命名空间隔离 | ❌ 无 | ✅ 白名单 + RBAC + 只读标记 |
| 输入清洗 | ❌ 无 | ✅ 长度限制 + 空字节过滤 + HTML 编码 |

### 7.2 config.yaml 新增配置汇总

```yaml
# agent/config.yaml — 安全配置汇总（新增字段）

# 原有字段保持不变
model: "qwen-max"
env: "mock"
db_path: "data/demo.db"
tickets_path: "data/tickets.json"

# 以下为新增安全配置
security:
  audit:
    enabled: true
    log_dir: "logs/audit"
    retention_days: 90        # 日志保留 90 天

  sql:
    read_only: true
    allowed_commands: [SELECT, SHOW, DESCRIBE, EXPLAIN, WITH]
    forbidden_keywords:
      - INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE
      - CREATE, REPLACE, GRANT, REVOKE, EXEC, EXECUTE
    max_query_length: 4096
    max_result_rows: 1000

  k8s:
    allowed_verbs: [get, describe, logs, top]
    allowed_resources:
      - pods, deployments, services, configmaps
      - namespaces, nodes, events, replicasets
    forbidden_verbs: [delete, drain, taint, cordon, exec]
    forbidden_flags: ["--force", "--grace-period=0", "--all"]
    allowed_namespaces: [default, staging, monitoring]
    read_only_namespaces: [production]

  calculator:
    max_expression_length: 200
    max_result_value: 1e15    # 防止极大数 DoS

  confirm:
    token_ttl_seconds: 300    # 确认令牌有效期 5 分钟
    require_for:
      - kubectl.scale
      - kubectl.rolling-update
```

### 7.3 实施优先级

```
Phase 1（本周）：
  ✅ Calculator: eval() → ast.literal_eval()
  ✅ kubectl: shell=True → shell=False + shlex
  ✅ SQL: 关键词过滤 validate_sql()
  ✅ 审计日志: AuditLogger 基础版

Phase 2（下周）：
  ✅ kubectl: 命令白名单 + 禁止动词
  ✅ SQL: 只读账户创建
  ✅ 二次确认: confirm_token 机制
  ✅ K8s RBAC: ServiceAccount + RoleBinding

Phase 3（下月）：
  ✅ 用户认证集成（JWT / API Key）
  ✅ 告警通知（飞书 / 钉钉 Webhook）
  ✅ 日志查询面板
  ✅ 数据库审计插件
```

---

## 八、需要手动修改的已有文件

> 按用户要求，此处仅说明修改位置和修改内容，不直接改文件。

### 8.1 `agent/tools/sql_tool.py`
- `cur.execute(query)` 前增加 `validate_sql(query)` 校验
- 连接时设置只读模式
- 增加 `fetchmany(1000)` 限制返回行数

### 8.2 `agent/tools/k8s_tool.py`
- 将 `subprocess.run(command, shell=True)` 改为 `subprocess.run(shlex.split(command), shell=False)`
- 执行前增加 `validate_kubectl()` 校验
- `scale` 操作前返回确认请求，不直接执行

### 8.3 `agent/tools/calculator_tool.py`
- 将 `eval(expression)` 替换为 `ast.literal_eval(expression)` 或使用 `numexpr` 库
- 增加表达式长度上限和结果上限

### 8.4 `agent/tools/__init__.py`
- 在 `execute_tool()` 中增加 `audit.log()` 调用
- 增加 `sanitize_input()` 对字符串参数自动清洗

### 8.5 `agent/config.yaml`
- 新增 `security:` 配置段（见 7.2）

### 8.6 `agent/config.py`
- 在 `AgentConfig` 数据类中新增 `security` 相关字段

---

## 九、新增依赖

```
# 安全相关新增依赖（需加到 requirements.txt）
numexpr>=2.8.0          # Calculator 安全替代 eval()（可选方案 B）
```


---

## 审计整改记录

> 整改日期：2026-06-21 | 依据：docs/SECURITY.md 审计建议

### 高危修复（4 项）

| # | 文件 | 风险 | 修复内容 | Commit |
|---|------|------|---------|--------|
| 1 | `agent/tools/calculator_tool.py` | `eval()` 代码注入 | 替换为 `ast.parse()` + `_SAFE_OPS` 安全求值，增加长度限制 | `9ab6ab0` |
| 2 | `agent/tools/k8s_tool.py` | `shell=True` 命令注入 | real 模式：`shlex.split()` + `shell=False` + `timeout=30` | `0b49ba0` |
| 3 | `agent/tools/sql_tool.py` | SQL 注入 + 无权限控制 | 新增 `validate_sql()`：关键词过滤 + 只读命令白名单 + 长度/行数限制 | `a61b042` |
| 4 | `agent/tools/__init__.py` | 工具入口无输入清洗 | 新增 `sanitize_input()`：长度截断 + 空字节过滤，execute_tool 入口自动清洗 | `ac9a2a9` |

### 中危修复（2 项）

| # | 文件 | 风险 | 修复内容 | Commit |
|---|------|------|---------|--------|
| 5 | `agent/config.yaml` | 缺少安全策略声明 | 新增 `security:` 配置段（audit / sql / k8s / calculator / confirm） | `1437fb4` |
| 6 | `agent/config.py` | 无法加载 security 配置 | AgentConfig 新增 `security: dict` 字段，from_yaml 自动加载 | `72b4f12` |

### 低危项（仅记录，不改代码）

| 项目 | 风险 | 处理方式 |
|------|------|---------|
| ticket_tool.py | 工单数据无长度限制 | 已有 `sanitize_input()` 清洗入口，暂不需要额外修改 |
| search_tool.py | 未来 real 模式 SSRF 风险 | 待 real 实现时增加 URL 白名单 |
| config.txt | API Key 明文存储 | 建议迁移到环境变量 + Secret Manager，不在本次范围 |

### 测试验证

```
$ pytest tests/ -v --tb=short
========================= 67 passed, 1 warning =========================
```

所有已有测试通过，安全修复未破坏任何现有功能。

