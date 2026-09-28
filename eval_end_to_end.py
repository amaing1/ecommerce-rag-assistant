"""
端到端评估（End-to-End Evaluation）—— LLM-as-Judge 判定
==========================================================
评估目标：从"用户问题"到"最终回答"的完整链路是否正常工作。

三个维度：
1. 路由准确率（Routing Accuracy）：意图路由是否选对工具（product/order/after_sales/rag）
2. 工具命中率（Tool Hit Rate）：工具/检索环节是否拿到数据
   - product 类 → 是否在 Redis/文件里查到价格
   - order/after_sales 类 → 是否查到订单/售后信息
   - rag 类 → 是否检索到文档
3. 回答正确率（Answer Accuracy）：最终回答与标准答案是否一致（LLM 裁判）

用法：python eval_end_to_end.py
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
from langchain_openai import ChatOpenAI
from app.core.config import settings
from app.services.rag_service import RAGService

# ===================== 配置区 =====================
DATASET_PATH = "eval_dataset.json"   # 测试集
# =================================================


def judge_answer(llm, question: str, reference_answer: str, model_answer: str) -> bool:
    """
    用大模型判断：模型的回答是否答对了用户的问题。
    返回 True（对）或 False（错）。
    """
    prompt = f"""你是客服回答质量评估员。判断"模型回答"是否正确回答了"用户问题"。

判断标准：
- 模型回答与"标准答案"关键信息一致（数字、状态、结论）→ 输出 correct
- 模型回答关键信息错误、或答非所问、或说查不到（但标准答案说应该查得到）→ 输出 incorrect
- 如果标准答案是"应引导用户提供单号"，模型回答也引导了 → 算 correct

用户问题：{question}

标准答案（权威）：{reference_answer}

模型回答：{model_answer}

请只输出一个词：correct 或 incorrect。"""
    try:
        resp = llm.invoke(prompt)
        verdict = resp.content.strip().lower()
        return verdict.startswith("correct")
    except Exception as e:
        print(f"    ⚠️ judge 调用失败: {e}")
        return False


def main():
    # 1. 加载测试集
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)
    items = dataset["items"]
    total = len(items)

    # 2. 初始化裁判大模型 + RAGService（内部含检索器、意图路由、LLM）
    print("⏳ 初始化裁判大模型...")
    llm = ChatOpenAI(
        model=settings.DASHSCOPE_MODEL,
        base_url=settings.DASHSCOPE_BASE_URL,
        api_key=settings.DASHSCOPE_API_KEY,
        temperature=0.0,
    )
    print("⏳ 初始化 RAGService...")
    svc = RAGService()

    # 3. 逐题评估
    print(f"\n端到端评估：{total} 题\n")
    print("=" * 78)

    route_hits = 0
    tool_hits = 0
    answer_hits = 0
    # 按类型分组统计
    stats = {}

    for it in items:
        q = it["question"]
        ref = it["reference_answer"]
        expect = it["expect_tool"]
        cat = it.get("category", "?")

        # ① 意图路由
        intent = svc._route_intent(q)
        route_ok = (intent == expect)

        # ② 调用完整链路，收集回答 + 是否查到数据
        tool_ok = False
        answer_text = ""
        streamed_meta = None

        try:
            gen = svc.query(user_question=q, messages=[], user_id=None)
            for chunk in gen:
                # 元数据是"JSON字符串+换行"（如 {"tool":"price_query"}\n），尝试解析成 dict
                if isinstance(chunk, str) and chunk.strip().startswith("{"):
                    try:
                        obj = json.loads(chunk.strip())
                        if isinstance(obj, dict) and "tool" in obj:
                            streamed_meta = obj
                            continue  # 元数据不算回答文本
                    except Exception:
                        pass
                if isinstance(chunk, dict) and "tool" in chunk:
                    streamed_meta = chunk
                elif isinstance(chunk, str):
                    answer_text += chunk
        except Exception as e:
            answer_text = f"[链路异常] {e}"

        # 工具命中判定：按类型看
        if expect == "product":
            tool_ok = streamed_meta is not None and streamed_meta.get("tool") == "price_query"
        elif expect in ("order", "after_sales"):
            tool_ok = streamed_meta is not None and streamed_meta.get("tool") == expect + "_query"
        else:  # rag
            tool_ok = True  # RAG 类只要链路没崩就算"检索环节工作"

        # ③ 回答正确性（LLM 裁判）
        answer_ok = judge_answer(llm, q, ref, answer_text)

        # 汇总
        if route_ok:
            route_hits += 1
        if tool_ok:
            tool_hits += 1
        if answer_ok:
            answer_hits += 1

        key = f"{expect} / {cat}"
        if key not in stats:
            stats[key] = {"n": 0, "route": 0, "tool": 0, "answer": 0}
        stats[key]["n"] += 1
        stats[key]["route"] += 1 if route_ok else 0
        stats[key]["tool"] += 1 if tool_ok else 0
        stats[key]["answer"] += 1 if answer_ok else 0

        print(f"{'✅' if route_ok else '❌'} {it['id']} [{cat}] 期望={expect} 路由={intent}")
        print(f"    工具命中={'✅' if tool_ok else '❌'}  回答正确={'✅' if answer_ok else '❌'}")
        if not answer_ok:
            print(f"    标准: {ref[:60]}")
            print(f"    模型: {answer_text[:80]}")

    # 4. 汇总
    print("\n" + "=" * 78)
    print("端到端评估结果汇总")
    print("=" * 78)
    print(f"总题数        : {total}")
    print(f"路由准确率    : {route_hits}/{total} = {route_hits/total*100:.1f}%")
    print(f"工具命中率    : {tool_hits}/{total} = {tool_hits/total*100:.1f}%")
    print(f"回答正确率    : {answer_hits}/{total} = {answer_hits/total*100:.1f}%")

    print("\n按类型细分：")
    for key, s in sorted(stats.items()):
        print(f"  [{key}] n={s['n']}  路由={s['route']}/{s['n']}  工具={s['tool']}/{s['n']}  回答={s['answer']}/{s['n']}")

    print("\n解读：")
    print("  - 路由准确率：意图路由选对工具的比例（选错会走错分支）")
    print("  - 工具命中率：工具/检索环节拿到数据的比例")
    print("  - 回答正确率：最终回答与标准答案一致的比例（LLM 裁判）")


if __name__ == "__main__":
    main()
