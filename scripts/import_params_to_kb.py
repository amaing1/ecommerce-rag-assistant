"""
生成"商品参数问答文档"并导入知识库
====================================
解决评估暴露的问题：参数题（电池容量/屏幕尺寸/快充等）在知识库里检索不到，
因为现有知识库分块是"商品卡片"格式（卖点摘要），没有完整参数明细。

做法：从 data/api_details.json 的"关键参数"字段生成问答式文本
（如 "REDMI K80 的电池容量是 6550mAh。"），转成 Document 追加进向量库。

用法：python scripts/import_params_to_kb.py
"""

import os
import sys
import json

# 把项目根加进 sys.path（脚本在 scripts/ 下运行时需要）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Chroma 需要高版本 sqlite3
try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # Python 3.11+ 系统自带 sqlite3 已满足 Chroma 要求
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

API_PATH = os.path.join(BASE_DIR, "data", "api_details.json")


def build_param_docs() -> list:
    """从 api_details.json 生成参数问答文档"""
    from langchain_core.documents import Document

    with open(API_PATH, encoding="utf-8") as f:
        api = json.load(f)

    docs = []
    for pid, v in api.items():
        name = (v.get("产品名") or "").strip()
        params = v.get("关键参数")
        if not name or not params:
            continue
        lines = [f"商品名称：{name}"]
        # 关键参数是 dict：{参数名: 值}
        for k, val in params.items():
            if val is None or val == "":
                continue
            lines.append(f"{k}：{val}")
        content = "\n".join(lines)
        docs.append(Document(page_content=content, metadata={"source": "api_params"}))
    return docs


def main():
    from app.services.rag_service import RAGService

    print("⏳ 生成参数问答文档...")
    docs = build_param_docs()
    print(f"✅ 生成 {len(docs)} 个商品参数文档")

    if not docs:
        print("❌ 没有生成任何文档，检查 api_details.json")
        return

    print("⏳ 初始化 RAGService 并导入向量库...")
    svc = RAGService()
    svc.load_knowledge_base(docs)
    print(f"✅ 导入完成，向量库现有 {len(svc.retriever.all_chunks)} 个分块")


if __name__ == "__main__":
    main()
