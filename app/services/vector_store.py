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

from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings


class VectorStore:
    def __init__(self,persist_dir="./vector_store",vector_type="chroma"):
        self.embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )
        self.vector_type = vector_type

        # FAISS 需要文档才能初始化，所以先置空，等 add_documents 时再建
        if vector_type == "faiss":
            self.vector_db = None
        else:
            self.vector_db = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embedding
            )

    def add_documents(self,chunk_list):
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

    test_q = "Python 读取文件有哪些模式？"
    docs = [
        Document(page_content="Python 文件读取有三种模式：r 只读、w 写入、a 追加"),
        Document(page_content="Python 文件写入模式 w 会覆盖原有内容，a 模式会在末尾追加"),
        Document(page_content="Python 的 open() 函数支持 r、w、a、x 等模式")
    ]

    print("====== Chroma检索 ======")
    chroma_store = VectorStore(vector_type="chroma")
    chroma_store.add_documents(docs)
    results = chroma_store.search(test_q, k=2)
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc.page_content[:50]}...")

    print("\n====== FAISS检索 ======")
    faiss_store = VectorStore(vector_type="faiss")
    faiss_store.add_documents(docs)
    results = faiss_store.search(test_q, k=2)
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc.page_content[:50]}...")