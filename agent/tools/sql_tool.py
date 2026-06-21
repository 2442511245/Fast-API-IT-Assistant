import json
import re
import sqlite3

from . import register_tool
from ..config import config

# ---------- SQL 安全校验 ----------
# 仅允许只读查询命令
_ALLOWED_COMMANDS = ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN", "WITH"]

# 禁止的 SQL 关键词（写操作、权限操作、文件操作）
_FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "REPLACE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE", "INTO OUTFILE", "INTO DUMPFILE",
    "LOAD_FILE", "LOAD DATA",
]

_MAX_QUERY_LEN = 4096
_MAX_RESULT_ROWS = 1000


def validate_sql(query: str) -> tuple:
    """
    校验 SQL 语句安全性
    返回 (是否通过, 失败原因)
    """
    # 1. 长度限制
    if len(query) > _MAX_QUERY_LEN:
        return False, f"SQL 查询超过最大长度限制 ({_MAX_QUERY_LEN})"

    # 2. 检查禁止关键词（单词边界匹配）
    upper_query = query.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, upper_query):
            return False, f"禁止的 SQL 操作: {keyword}"

    # 3. 必须以允许的命令开头
    stripped = upper_query.strip().lstrip("--").strip()
    if not any(stripped.startswith(cmd) for cmd in _ALLOWED_COMMANDS):
        return False, f"仅允许以 {_ALLOWED_COMMANDS} 开头的查询"

    # 4. 禁止多语句
    if ";" in query.rstrip(";"):
        return False, "禁止多语句查询"

    return True, "ok"


@register_tool(
    name="run_sql",
    description="执行 SQL 查询，从企业数据库中获取数据。表：sales(region, product, revenue, quarter)。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQL 查询语句"}
        },
        "required": ["query"]
    }
)
def run_sql(query: str) -> str:
    if config.env == "real":
        raise NotImplementedError("真实数据库连接未实现")
    else:
        # 安全校验
        passed, reason = validate_sql(query)
        if not passed:
            return f"SQL 执行被拒绝：{reason}"

        try:
            conn = sqlite3.connect(config.db_path)
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchmany(_MAX_RESULT_ROWS)
            conn.close()
            return json.dumps(rows, ensure_ascii=False, default=str) if rows else "查询结果为空"
        except Exception as e:
            return f"SQL 执行错误：{str(e)}"
