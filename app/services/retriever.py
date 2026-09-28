# ============================================================
# 第0块：SQLite版本替换（解决Chroma依赖问题）
# ============================================================
# 错误记录1：Chroma要求sqlite3 >= 3.35.0，否则报错
# 解决方案：用pysqlite3替换系统sqlite3
import sys
try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # 未安装 pysqlite3（Python 3.11+ 系统自带 sqlite3 已满足 Chroma 要求）


# ============================================================
# 第1块：环境准备 + 导入工具包
# ============================================================

import os
# 设置 HuggingFace 国内镜像，解决模型下载超时的问题
# 错误记录2：URL写成了 https:hf-mirror.com（少一个斜杠）
# 正确写法：https://hf-mirror.com
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 类型提示，告诉调用方这个函数返回什么类型（仅用于阅读，不强制）
from typing import List

# BM25 关键词检索算法：根据词有没有出现来打分
from rank_bm25 import BM25Okapi

# Chroma 向量数据库：存文本的向量（Embedding），支持相似度检索
from langchain_chroma import Chroma

# HuggingFaceEmbeddings：把文本转成向量（数字数组）
from langchain_community.embeddings import HuggingFaceEmbeddings



from app.services.vector_store import VectorStore
# ============================================================
# 第2块：定义混合检索器类
# ============================================================

class HybridRetriever:
    """
    混合检索器：
    - 支持关键词检索（BM25）
    - 支持语义检索（向量）
    - 支持重排序（CrossEncoder）
    - 对外提供统一的查询入口 hybrid_query()
    """

    # ---------- 2.1 初始化 ----------
    def __init__(self):
        """
        初始化方法：在创建检索器对象时自动执行
        加载三个模型 + 连接向量库，所有准备工作一次性完成
        """

        # 1. 向量模型：把文本转成向量
        #    使用的是 BAAI 开源的 bge-small-zh 中文模型
        self.embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )

        # 2. 向量库：存储所有文本块对应的向量，支持相似度检索
        #    persist_directory：向量数据持久化到硬盘的文件夹
        #    embedding_function：指定用哪个模型做向量化
        self.vector_db = VectorStore(persist_dir="./vector_store")




        # 4. 占位变量：存储文档分块和 BM25 索引
        #    - all_chunks：所有文本块（Document 对象列表）
        #    - bm25：BM25 索引对象，用于关键词检索
        #    这两个变量在 build_index() 被调用之前是空的
        self.all_chunks = []      # 初始为空列表
        self.bm25 = None          # 初始为空（还没建索引）

        # 启动时输出一条日志，方便确认初始化成功
        print("✅ HybridRetriever 初始化完成")

    # ---------- 2.2 构建索引 ----------
    def build_index(self, chunk_list):
        """
        功能：把文档分块存入向量库 + 构建 BM25 关键词索引
        调用时机：加载新知识库时调用一次，后续查询不需要再调用
        参数：chunk_list = LangChain Document 对象列表（由分块函数生成）
        """

        # 把分块存入实例变量，供 BM25 和检索使用
        self.all_chunks = chunk_list

        # 把分块批量加入向量库（自动生成向量并存储到硬盘）
        self.vector_db.add_documents(chunk_list)

        # 构建 BM25 索引
        # 1. 把所有文档的内容按空格分词（中文粗粒度分词，简单可用）
        # 错误记录3：写成了 doc.page.content，但 Document 对象的属性是 page_content
        # 正确写法：doc.page_content.split()
        corpus = [doc.page_content.split() for doc in chunk_list]
        # 2. 初始化 BM25 索引
        self.bm25 = BM25Okapi(corpus)

        # 打印构建结果
        print(f"✅ 索引构建完成，共加载 {len(chunk_list)} 个文本切片")

    # ---------- 2.3 BM25 关键词检索 ----------
    def bm25_search(self, q,top_k=20,min_score=0.0):
        """
        功能：基于关键词匹配的检索
        场景：用户问“价格”“保修”“型号”这类确定性词汇
        参数：q = 查询字符串
        返回：按 BM25 得分降序排列的文档列表（全部）
        """

        # 安全检查：如果 BM25 为空,先尝试从向量库恢复(重启后内存索引丢失)
        if self.bm25 is None:
            self.restore_index()
        if self.bm25 is None:
            raise Exception("错误：还没有执行 build_index 加载文档，BM25 索引未初始化！")

        # 按空格分词（与构建索引时保持一致）
        tokenized_query = q.split()

        # 计算每个文档与查询的 BM25 得分
        # 错误记录4：写成了 get_score（单数），但方法名是 get_scores（复数）
        # 正确写法：self.bm25.get_scores(tokenized_query)
        scores = self.bm25.get_scores(tokenized_query)

        ####计算分数和过滤
        doc_scores = [(i,s)for i, s in enumerate(scores) if s >= min_score]
        doc_scores.sort(key=lambda x:x[1],reverse=True)
        #######截断和返回
        return [self.all_chunks[i] for i,_ in doc_scores[:top_k]]
        ##_表示忽略分数，只取文档对象

    # ---------- 2.4 向量语义检索 ----------
    def vec_search(self, q,k=4):
        """
        功能：基于向量相似度的检索
        场景：用户问“性价比高”“有什么特色”这类主观、抽象的问题
        参数：q = 查询字符串
        返回：最相似的 4 条文档（k=4 固定值，可根据需要调整）
        """
        # Chroma 会自动将 q 转成向量，然后和库里的向量做相似度计算
        return self.vector_db.search(q,k=k)

    # ---------- 2.5 合并 + 去重 ----------
    def merge_doc(self, list1, list2):
        """
        功能：合并 BM25 和向量检索的结果，去掉重复内容
        为什么需要去重：同一个文档可能被两路检索同时命中，导致重复
        参数：list1, list2 = 两个文档列表
        返回：去重后的文档列表（按原顺序）
        """
        res = []          # 存最终结果（列表）
        seen = set()      # 存已经出现过的文本内容（集合，用于快速查重）

        # 遍历两路结果（list1 + list2）
        for d in list1 + list2:
            # 如果这段文本还没有被加入过，就加进去
            if d.page_content not in seen:
                seen.add(d.page_content)   # 往集合里加内容（用于查重）
                res.append(d)              # 往列表里加整个文档对象（用于返回）

        return res


    # ---------- 2.8 从向量库恢复索引(解决重启后 BM25 丢失) ----------
    def restore_index(self):
        """
        uvicorn 重启后,内存里的 all_chunks 和 bm25 会丢失,
        但向量数据存在磁盘 vector_store/ 里。
        这个方法读取磁盘上已存的文档,重建 BM25 索引。
        """
        try:
            # 从 Chroma 读回所有已存文档
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


    # ---------- 2.7 混合检索统一入口 ----------
    def hybrid_query(self, question,bm25_top_k=20,vec_top_k=4,min_score=0.0):
        """
        功能：对外统一调用接口
        流程：向量检索 → BM25 检索 → 合并去重 → 重排序 → 返回最终结果
        这是你唯一需要从外部调用的方法，其他方法都是内部辅助
        参数：question = 用户提问（字符串）
        返回：重排序后的文档列表（按相关性从高到低，全部返回）
        """

        # 第 1 步：两路召回
        vec_res = self.vec_search(question,k=vec_top_k)      # 语义检索（向量）
        bm25_res = self.bm25_search(question,top_k=bm25_top_k,min_score=min_score)    # 关键词检索（BM25）

        # 第 2 步：合并 + 去重
        mix = self.merge_doc(vec_res, bm25_res)

        # 第 3 步：返回最终结果（不再用CrossEncoder重排序，由百炼API处理）
        return mix
    ########单独使用BM25检索
    def bm25_only(self,question,top_k=10,min_score=0.0):
        return self.bm25_search(question,top_k=top_k,min_score=min_score)



# ============================================================
# 第3块：独立测试（仅在直接运行此文件时执行）
# ============================================================

if __name__ == "__main__":
    """
    这段代码只在执行 python retriever.py 时运行
    用于本地测试检索器是否能正常工作
    """

    from langchain.schema import Document

    # 1. 创建检索器实例
    retriever = HybridRetriever()

    # 2. 模拟分块数据（实际使用时由 PDF 加载 + 分块函数生成）
    #    用 Document 对象包装文本，确保有 page_content 属性
    mock_chunks = [
        Document(page_content="Python 文件读取有三种模式：r 只读、w 写入、a 追加"),
        Document(page_content="Python 文件写入模式 w 会覆盖原有内容，a 模式会在末尾追加"),
        Document(page_content="Python 的 open() 函数支持 r、w、a、x 等模式")
    ]

    # 3. 构建索引
    retriever.build_index(mock_chunks)

    test_q = "Python 读取文件有哪些模式？"

    # ========== 测试1：混合检索（原有功能）==========
    print("\n====== 测试1：混合检索 ======")
    results = retriever.hybrid_query(test_q)
    print(f"问题：{test_q}")
    print(f"命中 {len(results)} 条：")
    for idx, doc in enumerate(results, 1):
        print(f"  {idx}. {doc.page_content[:50]}...")

    # ========== 测试2：BM25单独检索（新功能）==========
    print("\n====== 测试2：BM25单独检索 ======")
    results = retriever.bm25_only(test_q, top_k=3)
    print(f"top_k=3，命中 {len(results)} 条：")
    for idx, doc in enumerate(results, 1):
        print(f"  {idx}. {doc.page_content[:50]}...")

    # ========== 测试3：BM25带阈值过滤（新功能）==========
    print("\n====== 测试3：BM25阈值过滤 ======")
    # 先看看实际分数
    tokenized_query = test_q.split()
    all_scores = retriever.bm25.get_scores(tokenized_query)
    print(f"模拟数据的BM25分数：{[round(s, 4) for s in all_scores]}")
    print(f"(真实知识库的分数会更高，因为文档更多)")
    
    # 用阈值过滤掉最后一条（分数最低的0.0794）
    results = retriever.bm25_search(test_q, min_score=0.08)
    print(f"min_score=0.08，命中 {len(results)} 条（过滤掉分数<0.08的）：")
    for idx, doc in enumerate(results, 1):
        print(f"  {idx}. {doc.page_content[:50]}...")

    # ========== 测试4：BM25只返回1条（极端top_k）==========
    print("\n====== 测试4：BM25 top_k=1 ======")
    results = retriever.bm25_only(test_q, top_k=1)
    print(f"命中 {len(results)} 条：")
    if results:
        print(f"  1. {results[0].page_content[:50]}...")































