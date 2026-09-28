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

# Chroma 向量数据库：存文本的向量（Embedding），支持相似度检索
from langchain_chroma import Chroma

# HuggingFaceEmbeddings：把文本转成向量（数字数组）
from langchain_community.embeddings import HuggingFaceEmbeddings


class VectorStore:
    def __init__(self,persist_dir="./vector_store",vector_type="chroma"):
        # 1. 向量模型：把文本转成向量
        #    使用的是 BAAI 开源的 bge-small-zh 中文模型
        self.embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )
        self.vector_type = vector_type

        # 2. 向量库：存储所有文本块对应的向量，支持相似度检索
        #    embedding_function：指定用哪个模型做向量化
        #如果用FAISS，先不创建（因为FAISS需要文档才能初始化）
        if vector_type == "faiss":
            self.vector_db = None
        else:
            self.vector_db = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embedding
            )

    def add_documents(self,chunk_list):
        # 把分块存入实例变量，供 BM25 和检索使用
        self.all_chunks = chunk_list
        if self.vector_type == "faiss":
            from langchain_community.vectorstores import FAISS
            self.vector_db = FAISS.from_documents(chunk_list,self.embedding)
        else:
            self.vector_db.add_documents(chunk_list)
    def search(self,query,k=4):
        return self.vector_db.similarity_search(query,k=k)
    def get(self,**kwargs):
        return self.vector_db.get(**kwargs)


if __name__ == "__main__":
    from langchain.schema import Document

    # 测试数据
    test_q = "Python 读取文件有哪些模式？"
    docs = [
        Document(page_content="Python 文件读取有三种模式：r 只读、w 写入、a 追加"),
        Document(page_content="Python 文件写入模式 w 会覆盖原有内容，a 模式会在末尾追加"),
        Document(page_content="Python 的 open() 函数支持 r、w、a、x 等模式")
    ]

    # Chroma检索
    print("====== Chroma检索 ======")
    chroma_store = VectorStore(vector_type="chroma")
    chroma_store.add_documents(docs)
    results = chroma_store.search(test_q, k=2)
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc.page_content[:50]}...")

    # FAISS检索
    print("\n====== FAISS检索 ======")
    faiss_store = VectorStore(vector_type="faiss")
    faiss_store.add_documents(docs)
    results = faiss_store.search(test_q, k=2)
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc.page_content[:50]}...")






















