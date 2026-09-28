"""
检索层评估（Retrieval Evaluation）v2 —— LLM-as-Judge 判定
=========================================================
评估目标：判断"标准答案所依赖的信息，检索环节能不能把它捞回来"。
只测检索这一环，不测最终回答（那是端到端评估，第 3 步做）。

为什么用大模型当裁判（而不是相似度阈值）？
- v1 用"标准答案 vs 召回文档"的向量相似度阈值判命中，结果是全❌但排名几乎都第1。
- 原因：标准答案是【改写过的】，与知识库原文表述不同，向量相似度被压低，
  但检索其实把相关内容排在了最前面。阈值尺子用错了。
- 正确做法：把"召回文档 + 问题 + 标准答案"交给大模型，让它判断
  "这些文档是否包含回答问题所需的关键信息"——语义级判断，不被表述差异欺骗。

指标：
- Hit Rate@K：大模型判定"检索结果能支持答对"的比例（越接近100%越好）
- MRR：答案相关文档的排名倒数平均（越接近1.0越好，说明答案靠前）

用法：python eval_retrieval.py
"""

# Chroma 需要高版本 sqlite3，用 pysqlite3 替换（与项目其他文件一致）
import sys
try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # Python 3.11+ 系统自带 sqlite3 已满足 Chroma 要求

import os
# HuggingFace 国内镜像，加速 embedding 模型加载
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import json
import numpy as np
from langchain_openai import ChatOpenAI
from app.core.config import settings
from app.services.retriever import HybridRetriever

# ===================== 配置区 =====================
DATASET_PATH = "eval_dataset.json"   # 第 1 步生成的测试集
TOP_K = 5                            # 检索返回条数
# =================================================


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度（用于计算 MRR 排名参考，不用于命中判定）"""
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def embed_text(embed, text: str) -> np.ndarray:
    """把文本转成向量（兼容不同 embedding 接口）"""
    try:
        return np.array(embed.embed_query(text))
    except Exception:
        return np.array(embed.embed_documents([text])[0])


def judge_retrieval(llm, question: str, reference_answer: str, docs) -> bool:
    """
    用大模型判断：检索返回的文档，是否包含回答该问题所需的关键信息。
    返回 True（能答对/hit）或 False（答不了/miss）。
    """
    docs_text = "\n\n".join(
        f"[文档{i + 1}] {d.page_content}" for i, d in enumerate(docs)
    )
    prompt = f"""你是检索质量评估员。请判断：下面这些"检索返回的文档"，是否包含了回答用户问题所需的【关键信息】。

判断标准：只根据这些文档（不要自己补充知识），能否给出与"标准答案"一致的答案。
- 如果文档中能找到回答问题的关键信息 → 输出 hit
- 如果文档中缺少关键信息、无法据此答对 → 输出 miss

用户问题：{question}

标准答案（仅供参考）：{reference_answer}

检索返回的文档：
{docs_text}

请只输出一个词：hit 或 miss。"""
    try:
        resp = llm.invoke(prompt)
        verdict = resp.content.strip().lower()
        return verdict.startswith("hit")
    except Exception as e:
        print(f"    ⚠️ judge 调用失败: {e}")
        return False


def main():
    # 1. 加载测试集
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)
    items = dataset["items"]

    # 只看 RAG 类题目（订单/售后工具题走的是工具查询，不参与检索评估）
    rag_items = [it for it in items if it["expect_tool"] == "rag"]

    # 2. 初始化裁判大模型 + 检索器
    print("⏳ 初始化裁判大模型...")
    llm = ChatOpenAI(
        model=settings.DASHSCOPE_MODEL,
        base_url=settings.DASHSCOPE_BASE_URL,
        api_key=settings.DASHSCOPE_API_KEY,
        temperature=0.0,          # 裁判要稳定，温度设为0
    )
    print("⏳ 初始化检索器...")
    retriever = HybridRetriever()
    retriever.restore_index()
    if not retriever.all_chunks:
        print("❌ 向量库为空，请先通过前端上传知识库")
        return
    print(f"✅ 索引就绪，共 {len(retriever.all_chunks)} 个分块")
    embed = retriever.embedding

    # 3. 逐题评估
    print(f"\n检索评估：{len(rag_items)} 道 RAG 题，top_k={TOP_K}\n")
    print("=" * 70)

    hits = 0
    rr_sum = 0.0

    for it in rag_items:
        q = it["question"]
        ref = it["reference_answer"]

        # 检索 top_k 条
        docs = retriever.hybrid_query(q, bm25_top_k=TOP_K, vec_top_k=4)[:TOP_K]
        if not docs:
            print(f"❌ {it['id']} [{it['category']}] {q}\n    （检索返回空）")
            continue

        # ① 命中判定：大模型判断文档能否答对（核心指标）
        hit = judge_retrieval(llm, q, ref, docs)

        # ② MRR：用向量相似度找"最相关文档"的排名（排序质量参考）
        ref_vec = embed_text(embed, ref)
        sims = [cosine(ref_vec, embed_text(embed, d.page_content)) for d in docs]
        best_rank = sims.index(max(sims)) + 1

        if hit:
            hits += 1
            rr_sum += 1.0 / best_rank

        print(f"{'✅' if hit else '❌'} {it['id']} [{it['category']}] {q}")
        print(f"    judge判定={'hit' if hit else 'miss'}  最相关文档排名第 {best_rank} 位")

    # 4. 汇总
    total = len(rag_items)
    hit_rate = hits / total * 100
    mrr = rr_sum / total

    print("\n" + "=" * 70)
    print("检索层评估结果汇总（LLM-as-Judge）")
    print("=" * 70)
    print(f"题目数           : {total}")
    print(f"Hit Rate@{TOP_K}  : {hits}/{total} = {hit_rate:.1f}%")
    print(f"MRR（平均倒数排名）: {mrr:.3f}")
    print("\n解读：")
    print("  - Hit Rate：检索结果里找得到答案的比例，越接近100%越好")
    print("  - MRR：答案相关文档排得越靠前，值越接近1.0")


if __name__ == "__main__":
    main()