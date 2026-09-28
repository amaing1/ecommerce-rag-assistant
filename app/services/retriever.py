# Chroma 要求 sqlite3 >= 3.35.0，低版本时用 pysqlite3 替代系统 sqlite3
import sys
try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # 未安装 pysqlite3（Python 3.11+ 系统自带 sqlite3 已满足要求）

import os
# 国内镜像，解决 HuggingFace 模型下载超时
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from typing import List
from rank_bm25 import BM25Okapi
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.services.vector_store import VectorStore


class HybridRetriever:
    """
    混合检索器：
    - 支持关键词检索（BM25）
    - 支持语义检索（向量）
    - 对外提供统一的查询入口 hybrid_query()
    """
    def __init__(self):
        """
        初始化：加载向量模型 + 连接向量库
        """
        self.embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )
        self.vector_db = VectorStore(persist_dir="./vector_store")

        self.all_chunks = []
        self.bm25 = None

        print("✅ HybridRetriever 初始化完成")

    def build_index(self, chunk_list):
        """
        把文档分块存入向量库 + 构建 BM25 关键词索引
        参数：chunk_list = LangChain Document 对象列表
        """
        self.all_chunks = chunk_list
        self.vector_db.add_documents(chunk_list)

        # 空格分词（中文是粗粒度分词，BM25 效果有限）
        corpus = [doc.page_content.split() for doc in chunk_list]
        self.bm25 = BM25Okapi(corpus)

        print(f"✅ 索引构建完成，共加载 {len(chunk_list)} 个文本切片")

    def bm25_search(self, q,top_k=20,min_score=0.0):
        """
        基于关键词匹配的检索，返回按 BM25 得分降序的文档列表
        """
        # BM25 为空时先尝试从向量库恢复（重启后内存索引丢失）
        if self.bm25 is None:
            self.restore_index()
        if self.bm25 is None:
            raise Exception("错误：还没有执行 build_index 加载文档，BM25 索引未初始化！")

        # 与构建索引一致：按空格分词
        tokenized_query = q.split()
        scores = self.bm25.get_scores(tokenized_query)

        doc_scores = [(i,s)for i, s in enumerate(scores) if s >= min_score]
        doc_scores.sort(key=lambda x:x[1],reverse=True)
        return [self.all_chunks[i] for i,_ in doc_scores[:top_k]]

    def vec_search(self, q,k=4):
        """
        基于向量相似度的检索，返回最相似的 k 条文档
        """
        return self.vector_db.search(q,k=k)

    def merge_doc(self, list1, list2):
        """
        合并 BM25 和向量检索的结果，按文本内容去重（同一文档可能被两路同时命中）
        """
        res = []
        seen = set()
        for d in list1 + list2:
            if d.page_content not in seen:
                seen.add(d.page_content)
                res.append(d)
        return res

    def restore_index(self):
        """
        uvicorn 重启后，内存里的 all_chunks 和 bm25 丢失，
        但向量数据在磁盘 vector_store/ 里，这里从磁盘重建 BM25 索引。
        """
        try:
            data = self.vector_db.get(include=["documents", "metadatas"])
            texts = data.get("documents") or []
            metas = data.get("metadatas") or []
            if not texts:
                print("警告: 向量库为空,无需恢复")
                return
            from langchain_core.documents import Document
            self.all_chunks = [
                Document(page_content=t, metadata=(m or {}))
                for t, m in zip(texts, metas)
            ]
            corpus = [t.split() for t in texts]
            self.bm25 = BM25Okapi(corpus)
            print(f"OK 从向量库恢复索引成功,共 {len(self.all_chunks)} 个分块")
        except Exception as e:
            print(f"警告: 恢复索引失败: {e}")

    def hybrid_query(self, question,bm25_top_k=20,vec_top_k=4,min_score=0.0):
        """
        对外统一查询入口：向量检索 → BM25 检索 → 合并去重
        参数：question = 用户提问
        """
        vec_res = self.vec_search(question,k=vec_top_k)
        bm25_res = self.bm25_search(question,top_k=bm25_top_k,min_score=min_score)
        mix = self.merge_doc(vec_res, bm25_res)
        # 这里不做 CrossEncoder 重排，改由百炼 rerank API 处理
        return mix

    def bm25_only(self,question,top_k=10,min_score=0.0):
        return self.bm25_search(question,top_k=top_k,min_score=min_score)


if __name__ == "__main__":
    """
    这段代码只在执行 python retriever.py 时运行，用于本地测试检索器
    """

    from langchain.schema import Document

    retriever = HybridRetriever()

    mock_chunks = [
        Document(page_content="Python 文件读取有三种模式：r 只读、w 写入、a 追加"),
        Document(page_content="Python 文件写入模式 w 会覆盖原有内容，a 模式会在末尾追加"),
        Document(page_content="Python 的 open() 函数支持 r、w、a、x 等模式")
    ]

    retriever.build_index(mock_chunks)

    test_q = "Python 读取文件有哪些模式？"

    print("\n====== 测试1：混合检索 ======")
    results = retriever.hybrid_query(test_q)
    print(f"问题：{test_q}")
    print(f"命中 {len(results)} 条：")
    for idx, doc in enumerate(results, 1):
        print(f"  {idx}. {doc.page_content[:50]}...")

    print("\n====== 测试2：BM25单独检索 ======")
    results = retriever.bm25_only(test_q, top_k=3)
    print(f"top_k=3，命中 {len(results)} 条：")
    for idx, doc in enumerate(results, 1):
        print(f"  {idx}. {doc.page_content[:50]}...")

    print("\n====== 测试3：BM25阈值过滤 ======")
    tokenized_query = test_q.split()
    all_scores = retriever.bm25.get_scores(tokenized_query)
    print(f"模拟数据的BM25分数：{[round(s, 4) for s in all_scores]}")
    print(f"(真实知识库的分数会更高，因为文档更多)")

    results = retriever.bm25_search(test_q, min_score=0.08)
    print(f"min_score=0.08，命中 {len(results)} 条（过滤掉分数<0.08的）：")
    for idx, doc in enumerate(results, 1):
        print(f"  {idx}. {doc.page_content[:50]}...")

    print("\n====== 测试4：BM25 top_k=1 ======")
    results = retriever.bm25_only(test_q, top_k=1)
    print(f"命中 {len(results)} 条：")
    if results:
        print(f"  1. {results[0].page_content[:50]}...")