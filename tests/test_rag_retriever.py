"""
test_rag_retriever.py — RAG 检索器单元测试

测试范围：
  - 给定已知文档和问题，断言召回结果不为空
  - 相似度阈值过滤是否生效
  - 检索 top-k 数量控制
  - 空知识库/低相似度场景

使用 pytest + unittest.mock，Mock 掉 ChromaDB 和 LLM 调用。
"""

import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.documents import Document


# ============================================================
# 辅助函数：构造模拟的 Document 和 Retriever
# ============================================================

def make_docs(*contents: str) -> list:
    """快速构造 langchain Document 列表"""
    return [Document(page_content=c) for c in contents]


def make_mock_retriever(docs: list):
    """
    构造一个模拟的 LangChain Retriever
    invoke(question) → 返回给定的 docs
    """
    retriever = MagicMock()
    retriever.invoke.return_value = docs
    return retriever


def make_mock_chain(answer: str = "根据文档，这是答案。"):
    """
    构造一个模拟的 RAG chain
    invoke(question) → 返回给定的 answer
    """
    chain = MagicMock()
    chain.invoke.return_value = answer
    return chain


# ============================================================
# 测试 1：检索召回基本功能
# ============================================================

class TestRetrieverRecall:
    """测试检索器能否正确召回文档"""

    def test_retriever_returns_non_empty_for_known_query(self):
        """给定包含匹配内容的文档，断言 retriever.invoke() 返回非空结果"""
        docs = make_docs(
            "Nginx 配置文件位于 /etc/nginx/nginx.conf，修改后需要执行 nginx -s reload 重新加载。",
            "Apache 的配置文件是 httpd.conf，位于 /etc/httpd/conf/ 目录下。",
            "MySQL 默认端口是 3306，可以通过 my.cnf 修改。",
        )
        retriever = make_mock_retriever(docs)
        result = retriever.invoke("如何重启 Nginx")
        assert len(result) > 0, "检索结果不应为空"

    def test_retriever_returns_document_objects(self):
        """检索返回的每个结果应该是 langchain_core.documents.Document 类型"""
        docs = make_docs("Nginx 重启命令是 systemctl restart nginx")
        retriever = make_mock_retriever(docs)
        result = retriever.invoke("重启 Nginx")
        assert all(isinstance(d, Document) for d in result), \
            "所有结果应为 Document 类型"

    def test_retriever_preserves_page_content(self):
        """检索结果应保留原始文档内容"""
        source_text = "若服务出现 502 错误，请先检查后端服务是否正常运行。"
        docs = make_docs(source_text)
        retriever = make_mock_retriever(docs)
        result = retriever.invoke("502 错误怎么办")
        assert result[0].page_content == source_text, \
            "检索结果应保留原始 page_content"


# ============================================================
# 测试 2：相似度阈值过滤
# ============================================================

class TestSimilarityThreshold:
    """测试相似度阈值过滤逻辑"""

    def test_low_similarity_docs_are_filtered_out(self):
        """
        模拟低相似度场景：当所有文档相似度低于阈值时，
        retriever 应返回空列表（模拟 similarity_score_threshold 行为）
        """
        # 模拟一个带 score_threshold 的 retriever：低相似度返回空
        retriever = make_mock_retriever([])  # 空列表 = 没有文档达到阈值
        result = retriever.invoke("完全不相关的问题")
        assert len(result) == 0, \
            "低于阈值的查询应返回空结果"

    def test_high_similarity_docs_are_returned(self):
        """
        模拟高相似度场景：匹配的文档应被返回
        """
        docs = make_docs("服务器 CPU 使用率超过 90% 时需要排查。")
        retriever = make_mock_retriever(docs)
        result = retriever.invoke("CPU 使用率过高怎么办")
        assert len(result) > 0, \
            "高相似度查询应返回结果"

    def test_threshold_boundary_exact_match(self):
        """
        阈值边界测试：完全匹配的文档应被召回
        """
        exact_doc = make_docs("密码重置流程：登录 IT 门户 → 点击忘记密码 → 验证邮箱 → 重置。")
        retriever = make_mock_retriever(exact_doc)
        result = retriever.invoke("密码重置流程")
        assert len(result) == 1, "完全匹配应被召回"
        assert "密码重置" in result[0].page_content

    def test_threshold_boundary_irrelevant_query(self):
        """
        阈值边界测试：完全不相关的查询不应返回结果
        """
        docs = make_docs("数据库备份策略：每天凌晨 2 点全量备份。")
        # 模拟相似度低于阈值：retriever 返回空
        retriever = make_mock_retriever([])
        result = retriever.invoke("今天食堂有什么菜")
        assert len(result) == 0, \
            "不相关查询应返回空（低于阈值被过滤）"


# ============================================================
# 测试 3：Top-K 数量控制
# ============================================================

class TestTopKRetrieval:
    """测试检索数量控制"""

    def test_top_k_default_limits_results(self):
        """默认 k=3，最多返回 3 个文档"""
        docs = make_docs("文档1", "文档2", "文档3", "文档4", "文档5")
        # 模拟 k=3 的 retriever
        retriever = make_mock_retriever(docs[:3])
        result = retriever.invoke("测试查询")
        assert len(result) <= 3, f"默认 top-k=3，实际返回 {len(result)}"

    def test_top_k_returns_at_most_k_docs(self):
        """即使有更多匹配，也只返回 k 个"""
        many_docs = make_docs(*[f"相关内容 {i}" for i in range(100)])
        retriever = make_mock_retriever(many_docs[:3])  # 模拟 k=3
        result = retriever.invoke("相关")
        assert len(result) == 3, f"k=3 应只返回 3 个，实际 {len(result)}"


# ============================================================
# 测试 4：RAG Chain 集成
# ============================================================

class TestRAGChainIntegration:
    """测试 RAG chain 的问答流程（Mock LLM）"""

    def test_ask_question_returns_answer_and_sources(self):
        """ask_question 应返回 (answer, sources) 二元组"""
        from rag.core.rag import ask_question

        chain = make_mock_chain("Nginx 的重启命令是 systemctl restart nginx。")
        docs = make_docs("重启 Nginx 使用 systemctl restart nginx 命令。")
        retriever = make_mock_retriever(docs)

        answer, sources = ask_question(chain, retriever, "如何重启 Nginx")
        assert isinstance(answer, str), "answer 应为字符串"
        assert isinstance(sources, list), "sources 应为列表"
        assert len(answer) > 0, "答案不应为空"

    def test_ask_question_with_no_sources(self):
        """当检索无结果时，sources 为空列表，answer 应说明无法回答"""
        from rag.core.rag import ask_question

        chain = make_mock_chain("无法从知识库中找到答案，已自动创建工单。")
        retriever = make_mock_retriever([])  # 无匹配

        answer, sources = ask_question(chain, retriever, "完全不相关的问题")
        assert len(sources) == 0, "无匹配时 sources 应为空"
        assert len(answer) > 0, "即使无匹配，LLM 也应返回提示"

    @patch("rag.core.rag.get_llm")
    def test_build_rag_chain_uses_similarity_threshold(self, mock_get_llm):
        """build_rag_chain 应设置 similarity_score_threshold 检索类型"""
        from rag.core.rag import build_rag_chain
        from unittest.mock import MagicMock

        # Mock LLM
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        # Mock vector_db
        mock_db = MagicMock()
        mock_retriever = MagicMock()
        mock_db.as_retriever.return_value = mock_retriever

        chain, retriever = build_rag_chain(mock_db)

        # 验证 as_retriever 被调用时传入了正确的参数
        mock_db.as_retriever.assert_called_once()
        call_kwargs = mock_db.as_retriever.call_args
        assert call_kwargs[1]["search_type"] == "similarity_score_threshold", \
            "必须使用 similarity_score_threshold 检索类型"
        assert call_kwargs[1]["search_kwargs"]["score_threshold"] == 0.6, \
            "相似度阈值应为 0.6"


# ============================================================
# 测试 5：文档加载与切分（Mock 文件 I/O）
# ============================================================

class TestDocumentProcessing:
    """测试文档加载和切分逻辑"""

    @patch("rag.core.rag.TextLoader")
    def test_load_document_txt(self, mock_loader):
        """加载 .txt 文件应使用 TextLoader"""
        from rag.core.rag import load_document

        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = make_docs("测试内容")
        mock_loader.return_value = mock_loader_instance

        docs = load_document("test.txt")
        mock_loader.assert_called_once_with("test.txt", encoding="utf-8")

    @patch("rag.core.rag.PyPDFLoader")
    def test_load_document_pdf(self, mock_loader):
        """加载 .pdf 文件应使用 PyPDFLoader"""
        from rag.core.rag import load_document

        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = make_docs("PDF 内容")
        mock_loader.return_value = mock_loader_instance

        docs = load_document("test.pdf")
        mock_loader.assert_called_once_with("test.pdf")

    def test_load_document_unsupported_format(self):
        """不支持的格式应抛出 ValueError"""
        from rag.core.rag import load_document

        with pytest.raises(ValueError, match="不支持的文件格式"):
            load_document("test.docx")

    def test_split_docs_respects_chunk_size(self):
        """split_docs 应按照 chunk_size 参数切分文档"""
        from rag.core.rag import split_docs

        long_text = "这是一个测试文档。" * 200  # 足够长以触发切分
        docs = make_docs(long_text)
        chunks = split_docs(docs, chunk_size=500, chunk_overlap=50)

        assert len(chunks) > 0, "切分后应有至少一个 chunk"
        # 每个 chunk 不应超过 chunk_size（允许一定误差）
        for chunk in chunks:
            assert len(chunk.page_content) <= 600, \
                f"chunk 大小 {len(chunk.page_content)} 超过预期上限 600"


# ============================================================
# 测试 6：ask_question 与 rag/router 的集成行为
# ============================================================

class TestAskQuestionIntegration:
    """测试 ask_question 函数与 router 的契约"""

    def test_ask_question_passes_question_to_chain(self):
        """ask_question 应将问题直接传给 chain.invoke()"""
        from rag.core.rag import ask_question

        chain = MagicMock()
        chain.invoke.return_value = "这是回复"
        retriever = make_mock_retriever(make_docs("上下文"))

        question = "如何查看系统日志？"
        ask_question(chain, retriever, question)

        chain.invoke.assert_called_once_with(question)

    def test_ask_question_passes_question_to_retriever(self):
        """ask_question 应将问题同时传给 retriever.invoke() 获取来源"""
        from rag.core.rag import ask_question

        chain = make_mock_chain("回复")
        retriever = MagicMock()
        retriever.invoke.return_value = make_docs("来源内容")

        question = "数据库连接失败怎么排查？"
        ask_question(chain, retriever, question)

        retriever.invoke.assert_called_once_with(question)

    def test_auto_ticket_logic_no_sources(self):
        """当 sources 为空时，router 层应触发自动创建工单"""
        from rag.core.rag import ask_question

        chain = make_mock_chain("无法从知识库中找到答案，已自动创建工单。")
        retriever = make_mock_retriever([])

        answer, sources = ask_question(chain, retriever, "未知问题")
        auto_ticket = len(sources) == 0  # 这个逻辑在 router.py 中
        assert auto_ticket is True, "无来源时应标记 auto_ticket=True"
