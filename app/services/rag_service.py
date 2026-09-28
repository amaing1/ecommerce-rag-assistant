
# ============================================================
# 第0块：SQLite版本替换（解决Chroma依赖问题）
# ============================================================
import sys
try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # 未安装 pysqlite3（Python 3.11+ 系统自带 sqlite3 已满足 Chroma 要求）


# ============================================================
# 第1块：导入依赖
# ============================================================

import os
import time
import json
from typing import List, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from app.core.config import settings
from app.services.retriever import HybridRetriever
from app.services.order_service import query_order
from app.services.after_sales_service import query_after_sales,format_after_sales_snapshot
from app.services.product_service import query_price

# ============================================================
# 第2块：常量定义
# ============================================================


# 来源展示阈值：百炼 rerank 的 relevance_score 越高越相关(约 0~1)
# 低于这个分数的来源不展示(可调:调大更严格,调小更宽松)
MIN_SCORE = settings.MIN_SCORE

# 查询改写提示词模板：要求大模型生成 3 个同义问句
PROMPT_TEMPLATE = """
根据用户问题生成3个同义检索问句。
仅输出问句，一行一条，不要额外文字。
原始问题：{user_question}
"""


# ============================================================
# 第3块：RAG 服务类
# ============================================================

class RAGService:
    """
    RAG 服务类：
    - 负责查询改写、混合检索、阈值过滤、上下文拼接
    - 对外只暴露 query() 方法
    """

    # ---------- 3.1 初始化 ----------
    def __init__(self):
        """
        初始化：加载大模型、提示词模板、混合检索器
        """
        # 1. 大模型（使用通义千问，兼容 OpenAI 接口）
        # 轻任务模型：意图路由、查询改写（便宜、快）
        self.router_llm = ChatOpenAI(
            model=settings.DASHSCOPE_MODEL_ROUTER,
            base_url=settings.DASHSCOPE_BASE_URL,
            api_key=settings.DASHSCOPE_API_KEY,
            temperature=0.1,
        )
        # 重任务模型：最终答案生成（质量优先）
        self.generate_llm = ChatOpenAI(
            model=settings.DASHSCOPE_MODEL_GENERATE,
            base_url=settings.DASHSCOPE_BASE_URL,
            api_key=settings.DASHSCOPE_API_KEY,
            temperature=0.1,
        )

        # 2. 提示词模板
        self.prompt = PromptTemplate.from_template(PROMPT_TEMPLATE)
        # 3. 混合检索器（你昨天写的）
        self.retriever = HybridRetriever()
        print("✅ RAGService 初始化完成")

    # ---------- 3.2 加载知识库 ----------
    def load_knowledge_base(self, chunk_list):
        """
        功能：把文档分块喂给检索器，构建索引
        参数：chunk_list = Document 对象列表
        """
        self.retriever.build_index(chunk_list)
        print(f"✅ RAGService 知识库加载完成，共 {len(chunk_list)} 个分块")

    # ---------- 3.3 查询改写 ----------
    def generate_multi_query(self, origin_question: str) -> List[str]:
        """
        功能：调用大模型生成 3 个同义检索问句
        参数：origin_question = 用户原始问题
        返回：包含原始问题和最多 3 个改写问句的列表
        """
        # 1. 填充提示词模板
        new_prompt = self.prompt.invoke({"user_question": origin_question})
        # 2. 调用大模型生成
        response = self.router_llm.invoke(new_prompt)
        # 3. 解析返回结果：按换行分割，去除首尾空格，过滤空行
        query_list = [q.strip() for q in response.content.split("\n") if q.strip()]
        # 4. 安全截断：最多保留 3 条（防止大模型输出过多）
        if len(query_list) > 3:
            query_list = query_list[:3]
        # 5. 原始问题放在第一位（兜底）
        if origin_question not in query_list:
            query_list.insert(0, origin_question)
        return query_list

    # ---------- 调用百炼 rerank API 精排 ----------
    def _rerank_api(self, query: str, docs: List, top_n: int = 5) -> List:
        """
        调用阿里云百炼 text-rerank API 精排候选文档
        """
        import requests
        url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        headers = {
            "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "qwen3-rerank",
            "input": {
                "query": query,
                "documents": [d.page_content for d in docs],
            },
            "parameters": {"top_n": top_n},
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()#检查是否成功
        data = resp.json()
        # 解析返回结果，返回(文档, 分数)配对
        ranked = []
        for item in data.get("output", {}).get("results", []):
            idx = item.get("index")
            if idx is not None and idx < len(docs):
                score = item.get("relevance_score", 0.0)
                ranked.append((docs[idx], score))
        return ranked

    def _route_intent(self, question: str) -> str:
        """用大模型判断用户意图：返回 order / after_sales / product / rag"""
        prompt = f"""
    你是小米商城客服的意图路由器。判断用户的问题属于哪一类，只输出一个词。

    判断规则（按顺序）：
    1. 问题里有订单号(XM开头)/物流单号，或明确问"订单/物流/发货/签收/快递到哪" → order
    2. 问题里有售后单号(SH开头)，或明确问"退货/退款/换货/维修的进度/状态" → after_sales
    3. 问题的核心是【价格】：含"多少钱/价格/售价/价钱/降价/优惠价"，且是问【某个具体商品】卖多少钱 → product
    4. 其他一切 → rag，包括：
       - 问商品参数/规格：电池容量、屏幕尺寸、快充瓦数、摄像头像素、处理器、内存、存储等（不管问题里有没有商品名）
       - 问商品功能/特点：支不支持NFC、防水吗、有指纹吗
       - 推荐/对比/哪款好/选哪个/性价比/哪款最便宜/哪款最贵/最值得买
       - 售后政策：无理由退货期限、换货政策、包邮规则、保修
       - 使用方法、常见问题

    反例（这些都不是 product，即使有商品名或价格词）：
    - "REDMI K80 的电池容量是多少？" → rag（问参数不是价格）
    - "Xiaomi 14 的屏幕尺寸？" → rag（问参数）
    - "你们支持7天无理由退货吗？" → rag（问政策，不是查我的售后单）
    - "REDMI K80 和 K80 Pro 哪个好？" → rag（推荐对比）
    - "小米手机里面最便宜的是哪款？" → rag（问"哪款最便宜"，是选购对比，不是查某个商品价格）
    - "预算3000以内买什么手机好？" → rag（选购推荐）
    - "K80 和 K80 Pro 哪个性价比高？" → rag（对比选购）

    用户问题：{question}
    """
        resp = self.router_llm.invoke(prompt)
        return resp.content.strip().lower()


    # ---------- 3.4 完整 RAG 流程 ----------
    def query(self, user_question: str, messages: Optional[List[dict]] = None, user_id: int = None,has_image: bool = False,vision_time_ms: float = 0,vision_prompt_tokens: int = 0,vision_completion_tokens: int = 0):
        """
        功能：RAG 完整流水线
        参数：user_question = 用户原始问题, user_id = 当前用户 ID(用于监控日志)
        返回：字典，包含 can_answer, reply, context, documents
        """
        # ===== 监控指标:初始化计时器和计数器 =====
        t_start = time.time()
        metrics = {
            "rewrite_time_ms": 0, "vec_search_time_ms": 0, "bm25_search_time_ms": 0,
            "dedup_time_ms": 0, "rerank_time_ms": 0, "generation_time_ms": 0,
            "total_time_ms": 0, "rewritten_query_count": 0, "vec_result_count": 0,
            "bm25_result_count": 0, "candidate_count": 0, "rerank_count": 0,
            "valid_doc_count": 0, "answer_length": 0, "can_answer": False,
            "error_message": None, "rewritten_queries": [],
            "has_image": has_image,"vision_time_ms": vision_time_ms,
            "prompt_tokens": 0, "completion_tokens": 0,
            "vision_prompt_tokens": vision_prompt_tokens, "vision_completion_tokens": vision_completion_tokens
        }

        try:
            # ===== Agent 工具调用：订单/物流查询（大模型意图识别） =====
            intent = self._route_intent(user_question) if not has_image else "rag"
            if intent == "order":
                order = query_order(user_question)
                if order:
                    print(f"[AGENT] 命中订单工具: {order['order_no']}")
                    order_info = (
                        f"订单号: {order['order_no']}\n"
                        f"商品: {order['product']}\n"
                        f"状态: {order['status']}\n"
                        f"快递: {order['courier']}\n"
                        f"物流单号: {order['tracking_no'] or '暂无'}\n"
                        f"预计送达: {order['eta']}"
                    )
                    tool_prompt = (
                        "你是小米商城客服。用户查询了订单/物流信息，请根据以下订单信息，"
                        "用简洁、亲切的口吻回答，说明订单状态和最新物流节点。\n\n"
                        f"【订单信息】\n{order_info}\n\n"
                        f"【用户问题】\n{user_question}\n\n请直接给出回答："
                    )
                    yield json.dumps({"can_answer": True, "sources": [], "tool": "order_query"}, ensure_ascii=False) + "\n"
                    full_answer = ""
                    t_gen = time.time()
                    for chunk in self.generate_llm.stream(tool_prompt):
                        full_answer += chunk.content
                        yield chunk.content
                    metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
                    metrics["answer_length"] = len(full_answer)
                    return
                else:
                    # 意图是查订单，但没查到订单号/订单不存在 → 请用户提供订单号
                    print("[AGENT] 订单意图但未找到订单，请用户提供订单号")
                    ask_prompt = (
                        "你是小米商城客服。用户想查询订单/物流，但你没有找到对应的订单信息。"
                        "请礼貌地请用户提供订单号（格式如 XM20260815001）。"
                    )
                    yield json.dumps({"can_answer": True, "sources": [], "tool": "order_query"},
                                     ensure_ascii=False) + "\n"
                    full_answer = ""
                    t_gen = time.time()
                    for chunk in self.generate_llm.stream(ask_prompt):
                        full_answer += chunk.content
                        yield chunk.content
                    metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
                    metrics["answer_length"] = len(full_answer)
                    return
            if intent == "after_sales":
                after_sales = query_after_sales(user_question)
                if after_sales:
                    print(f"[AGENT] 命中售后工具: {after_sales['after_sales_no']}")
                    as_info = format_after_sales_snapshot(after_sales)
                    tool_prompt = (
                        "你是小米商城客服。用户查询了售后/退货处理状态，请根据以下售后单信息，"
                        "用简洁、亲切的口吻回答，说明售后类型、当前状态和最新处理进度。\n\n"
                        f"【售后单信息】\n{as_info}\n\n"
                        f"【用户问题】\n{user_question}\n\n请直接给出回答："
                    )
                    yield json.dumps({"can_answer": True, "sources": [], "tool": "after_sales_query"}, ensure_ascii=False) + "\n"
                    full_answer = ""
                    t_gen = time.time()
                    for chunk in self.generate_llm.stream(tool_prompt):
                        full_answer += chunk.content
                        yield chunk.content
                    metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
                    metrics["answer_length"] = len(full_answer)
                    return
                else:
                    # 售后意图但没查到售后单号 → 请用户提供
                    print("[AGENT] 售后意图但未找到售后单，请用户提供售后单号")
                    ask_prompt = (
                        "你是小米商城客服。用户想查询售后/退货处理状态，但你没有找到对应的售后单信息。"
                        "请礼貌地请用户提供售后单号（格式如 SH20260815001）。"
                    )
                    yield json.dumps({"can_answer": True, "sources": [], "tool": "after_sales_query"}, ensure_ascii=False) + "\n"
                    full_answer = ""
                    t_gen = time.time()
                    for chunk in self.generate_llm.stream(ask_prompt):
                        full_answer += chunk.content
                        yield chunk.content
                    metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
                    metrics["answer_length"] = len(full_answer)
                    return
            if intent == "product":
                product = query_price(user_question)
                if product:
                    print(f"[AGENT] 命中价格工具: {product['product']} (source={product.get('source','?')})")
                    # 价格来源提示：Redis=实时；文件降级=可能非最新，要诚实告知用户
                    stale_notice = ""
                    if product.get("source") == "file":
                        stale_notice = (
                            "\n注意：当前价格来自本地缓存（可能不是最新），"
                            "回答时请在结尾礼貌地提醒用户'价格可能不是最新，建议以小米官网为准'。\n"
                        )
                    tool_prompt = (
                        "你是小米商城客服。用户查询了商品价格，请根据以下商品价格信息，"
                        "用简洁、亲切的口吻回答。\n\n"
                        f"【价格信息】\n商品: {product['product']}\n"
                        f"当前价: ¥{product['当前价']}\n"
                        f"市场价: ¥{product['市场价']}\n"
                        f"{stale_notice}\n"
                        f"【用户问题】\n{user_question}\n\n请直接给出回答："
                    )
                    yield json.dumps({"can_answer": True, "sources": [], "tool": "price_query"}, ensure_ascii=False) + "\n"
                    full_answer = ""
                    t_gen = time.time()
                    for chunk in self.generate_llm.stream(tool_prompt):
                        full_answer += chunk.content
                        yield chunk.content
                    metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
                    metrics["answer_length"] = len(full_answer)
                    return
                else:
                    # 价格意图但 Redis/工具里没找到商品 → 诚实告知，不走 RAG
                    # （防止知识库里的旧价格快照把下架商品"复活"）
                    print("[AGENT] 价格意图但未找到商品，拒绝走知识库")
                    ask_prompt = (
                        "你是小米商城客服。用户查询了商品价格，但你这里没有这个商品的价格信息，"
                        "请礼貌地说明暂时查不到该商品的价格，并建议用户直接访问小米商城官网查看。"
                    )
                    yield json.dumps({"can_answer": True, "sources": [], "tool": "price_query"}, ensure_ascii=False) + "\n"
                    full_answer = ""
                    t_gen = time.time()
                    for chunk in self.generate_llm.stream(ask_prompt):
                        full_answer += chunk.content
                        yield chunk.content
                    metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
                    metrics["answer_length"] = len(full_answer)
                    return


            # ----- 第 1 步：日志 + 查询改写 -----
            print(f"[RAG] 开始处理问题: {user_question}")
            # 历史对话转成文本(没有历史就是空字符串)
            history_text = ""
            for m in (messages or []):
                history_text += f"{m['role']}: {m['content']}\n"

            t0 = time.time()
            query_list = self.generate_multi_query(user_question)
            metrics["rewrite_time_ms"] = round((time.time() - t0) * 1000, 2)
            metrics["rewritten_query_count"] = len(query_list)
            metrics["rewritten_queries"] = query_list
            print(f"【RAG】生成 {len(query_list)} 条检索问句")

            # ----- 第 2 步：准备容器 -----
            # ----- 第 3 步：遍历改写问句，混合检索 + 去重收集 -----
            all_docs = []          # 合并所有问句召回的候选文档
            seen_text = set()      # 按内容去重
            for q in query_list:
                # 两路召回(临时跳过 rerank:本地 CPU 跑 2GB 重排序模型要 >5 分钟)
                t_vec = time.time()
                vec_docs = self.retriever.vec_search(q)
                metrics["vec_search_time_ms"] += round((time.time() - t_vec) * 1000, 2)
                metrics["vec_result_count"] += len(vec_docs)

                t_bm25 = time.time()
                bm25_docs = self.retriever.bm25_search(q)[:10]
                metrics["bm25_search_time_ms"] += round((time.time() - t_bm25) * 1000, 2)
                metrics["bm25_result_count"] += len(bm25_docs)

                docs = vec_docs + bm25_docs
                for doc in docs:
                    content = doc.page_content.strip()
                    if content not in seen_text:
                        seen_text.add(content)
                        all_docs.append(doc)

            metrics["candidate_count"] = len(all_docs)
            print(f"[RAG] 检索完成，共搜集 {len(all_docs)} 条候选文档")

            # ===== 精排:调用百炼 rerank API(秒级,上线同款方案) =====
            # 先取前 20 条候选,API 排前 10 条,再按分数阈值过滤出最终来源
            valid_docs = []
            ranked_count = 0
            if all_docs:
                t_rerank = time.time()
                ranked = self._rerank_api(user_question, all_docs[:20], top_n=10)
                metrics["rerank_time_ms"] = round((time.time() - t_rerank) * 1000, 2)
                ranked_count = len(ranked)
                for doc, score in ranked:
                    print(f"  [精排] 分数={score:.3f}: {doc.page_content[:25]}...")
                    # 只保留分数达标的来源(低于阈值的都是"擦边"内容)
                    if score >= MIN_SCORE:
                        valid_docs.append(doc)
            else:
                valid_docs = []

            metrics["rerank_count"] = ranked_count
            metrics["valid_doc_count"] = len(valid_docs)
            print(f"【RAG】精排后,达标 {len(valid_docs)} 条 / 共 {ranked_count} 条")

            # ----- 第 5 步：判断是否能回答 -----
            if not valid_docs:
                # 拒答:也吐元信息(can_answer=False),前端据此显示拒答提示
                yield json.dumps({"can_answer": False, "sources": []}, ensure_ascii=False) + "\n"
                yield "知识库没有相关内容，无法回答你的问题"
                metrics["can_answer"] = False
                metrics["total_time_ms"] = round((time.time() - t_start) * 1000, 2)
                self._save_log(user_question, user_id, metrics)
                return

            # ----- 第 6 步：拼接上下文 + 调用大模型生成回答 -----
            context_text = "\n\n".join([doc.page_content for doc in valid_docs])

            # 基于检索到的资料，让大模型组织回答
            generate_prompt = (
                "你是一个电商客服助手。请严格根据以下参考资料回答用户问题。\n"
                "如果参考资料中没有相关信息,请直接回答:抱歉,知识库中没有相关内容。\n\n"
                f"【历史对话】\n{history_text}\n"
                f"【参考资料】\n{context_text}\n\n"
                f"【用户问题】\n{user_question}\n\n"
                "请给出简洁、专业的回答:"
            )
            # 先吐一段"元信息"(JSON):前端靠它知道能否回答 + 来源
            # 约定:流的第一段是 JSON,后面每段是答案文本
            sources_preview = [
                doc.page_content[:200] for doc in valid_docs[:3]
            ]
            yield json.dumps({"can_answer": True, "sources": sources_preview}, ensure_ascii=False) + "\n"

            # 流式生成答案:一段段吐
            full_answer = ""
            t_gen = time.time()
            for chunk in self.generate_llm.stream(generate_prompt):
                full_answer += chunk.content
                yield chunk.content
                if getattr(chunk,"usage_metadata",None):
                    metrics["prompt_tokens"] = chunk.usage_metadata.get("input_tokens",0)
                    metrics["completion_tokens"] = chunk.usage_metadata.get("output_tokens",0)
            metrics["generation_time_ms"] = round((time.time() - t_gen) * 1000, 2)
            metrics["answer_length"] = len(full_answer)
            metrics["can_answer"] = True

        except Exception as e:
            metrics["error_message"] = str(e)[:500]
            print(f"[RAG] 异常: {e}")

        finally:
            # ===== 监控指标:记录总耗时并写入数据库 =====
            metrics["total_time_ms"] = round((time.time() - t_start) * 1000, 2)
            self._save_log(user_question, user_id, metrics)

    def _save_log(self, question: str, user_id: int, metrics: dict):
        """把监控指标写入数据库(异步安全:仅写日志,不影响主流程)"""
        try:
            from app.database import SessionLocal
            from app.models.retrieval_log import RetrievalLog
            db = SessionLocal()
            try:
                log = RetrievalLog(
                    user_id=user_id,
                    question=question[:1000],
                    rewritten_queries=json.dumps(metrics.get("rewritten_queries", []), ensure_ascii=False),
                    can_answer=metrics["can_answer"],
                    rewrite_time_ms=metrics["rewrite_time_ms"],
                    vec_search_time_ms=metrics["vec_search_time_ms"],
                    bm25_search_time_ms=metrics["bm25_search_time_ms"],
                    dedup_time_ms=metrics["dedup_time_ms"],
                    rerank_time_ms=metrics["rerank_time_ms"],
                    generation_time_ms=metrics["generation_time_ms"],
                    total_time_ms=metrics["total_time_ms"],
                    rewritten_query_count=metrics["rewritten_query_count"],
                    vec_result_count=metrics["vec_result_count"],
                    bm25_result_count=metrics["bm25_result_count"],
                    candidate_count=metrics["candidate_count"],
                    rerank_count=metrics["rerank_count"],
                    valid_doc_count=metrics["valid_doc_count"],
                    answer_length=metrics["answer_length"],
                    error_message=metrics.get("error_message"),
                    has_image=metrics.get("has_image",False),
                    vision_time_ms=metrics.get("vision_time_ms",0),
                    prompt_tokens=metrics.get("prompt_tokens", 0),
                    completion_tokens=metrics.get("completion_tokens", 0),
                    vision_prompt_tokens=metrics.get("vision_prompt_tokens", 0),
                    vision_completion_tokens=metrics.get("vision_completion_tokens", 0),
                )
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[监控] 写入日志失败(不影响主流程): {e}")

































