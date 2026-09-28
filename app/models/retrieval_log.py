"""
检索监控日志表:记录每次 RAG 查询的 13 个性能指标
"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.database import Base


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    question = Column(Text, nullable=False)                    # 用户原始问题
    rewritten_queries = Column(Text, nullable=True)            # 改写后的问句(JSON)
    can_answer = Column(Boolean, default=False)                # 是否成功回答

    # 各阶段耗时(毫秒)
    rewrite_time_ms = Column(Float, default=0)                 # 查询改写耗时
    vec_search_time_ms = Column(Float, default=0)              # 向量检索耗时
    bm25_search_time_ms = Column(Float, default=0)             # BM25 检索耗时
    dedup_time_ms = Column(Float, default=0)                   # 去重耗时
    rerank_time_ms = Column(Float, default=0)                  # 精排耗时
    generation_time_ms = Column(Float, default=0)              # 大模型生成耗时
    vision_time_ms = Column(Float,default=0)                   # 识图耗时
    has_image = Column(Boolean,default=False)                  # 用户是否上传了图片
    total_time_ms = Column(Float, default=0)                   # 总耗时

    # 数量指标
    rewritten_query_count = Column(Integer, default=0)         # 改写问句数
    vec_result_count = Column(Integer, default=0)              # 向量检索命中数
    bm25_result_count = Column(Integer, default=0)             # BM25 检索命中数
    candidate_count = Column(Integer, default=0)               # 去重后候选数
    rerank_count = Column(Integer, default=0)                  # 精排后保留数
    valid_doc_count = Column(Integer, default=0)               # 阈值过滤后最终数

    # 其他
    answer_length = Column(Integer, default=0)                 # 回答字数
    error_message = Column(Text, nullable=True)                # 异常信息(如果有)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


    # token 用量与成本
    prompt_tokens = Column(Integer, default=0)                 # RAG 大模型输入 token
    completion_tokens = Column(Integer, default=0)             # RAG 大模型输出 token
    vision_prompt_tokens = Column(Integer, default=0)          # 识图模型输入 token
    vision_completion_tokens = Column(Integer, default=0)      # 识图模型输出 token

    def __repr__(self):
        return f"<RetrievalLog(id={self.id}, can_answer={self.can_answer}, total={self.total_time_ms}ms)>"
