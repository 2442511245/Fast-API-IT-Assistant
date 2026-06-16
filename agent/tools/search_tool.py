from . import register_tool

@register_tool(
    name="web_search",
    description="搜索互联网获取最新信息，当需要外部知识时使用。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["query"]
    }
)
def web_search(query: str) -> str:
    # Mock 实现，真实环境可接入 SearXNG / Bing API
    return f'关于"{query}"的搜索结果（Mock）：这是模拟的搜索内容，实际环境将返回真实摘要。'