"""
监控接口的请求/响应模型
"""
from pydantic import BaseModel
from typing import Optional


class MonitorStatsResponse(BaseModel):
    """统计概览响应"""
    total_queries: int = 0                    # 总查询数
    successful_queries: int = 0               # 成功回答数
    failed_queries: int = 0                   # 拒答/异常数
    success_rate: float = 0.0                 # 成功率(%)
    avg_total_time_ms: float = 0.0            # 平均总耗时(ms)
    avg_rewrite_time_ms: float = 0.0          # 平均改写耗时
    avg_vec_search_time_ms: float = 0.0       # 平均向量检索耗时
    avg_bm25_search_time_ms: float = 0.0      # 平均 BM25 检索耗时
    avg_rerank_time_ms: float = 0.0           # 平均精排耗时
    avg_generation_time_ms: float = 0.0       # 平均生成耗时
    avg_valid_doc_count: float = 0.0          # 平均有效文档数


class MonitorLogItem(BaseModel):
    """单条日志响应"""
    id: int
    question: str
    can_answer: bool
    rewrite_time_ms: float
    vec_search_time_ms: float
    bm25_search_time_ms: float
    dedup_time_ms: float
    rerank_time_ms: float
    generation_time_ms: float
    total_time_ms: float
    rewritten_query_count: int
    vec_result_count: int
    bm25_result_count: int
    candidate_count: int
    rerank_count: int
    valid_doc_count: int
    answer_length: int
    error_message: Optional[str] = None
    created_at: Optional[str] = None


class MonitorLogsResponse(BaseModel):
    """日志列表响应"""
    total: int
    items: list[MonitorLogItem]
