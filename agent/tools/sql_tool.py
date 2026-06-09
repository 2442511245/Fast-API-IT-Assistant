import sqlite3
import json
from . import register_tool
from ..config import config

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
        try:
            conn = sqlite3.connect(config.db_path)
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            conn.close()
            return json.dumps(rows, ensure_ascii=False, default=str) if rows else "查询结果为空"
        except Exception as e:
            return f"SQL 执行错误：{str(e)}"