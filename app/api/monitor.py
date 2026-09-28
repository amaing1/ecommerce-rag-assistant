"""
检索监控接口:查看统计信息和日志列表
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text, insert, inspect
from app.core.config import settings
import math
from app.database import get_db, engine, Base
from app.models.retrieval_log import RetrievalLog
from app.api.deps import get_current_user
from app.models import User

# 确保 retrieval_logs 表存在
Base.metadata.create_all(bind=engine)

router = APIRouter()
def _ensure_token_columns():
    """给已存在的表补上token列(SQLite建表不会自动加列，老库要手动补)"""
    existing = {c["name"] for c in inspect(engine).get_columns("retrieval_logs")}
    with engine.begin() as conn:
        for col in ("prompt_tokens", "completion_tokens", "vision_prompt_tokens", "vision_completion_tokens"):
            if col not in existing:
                conn.execute(text(f"ALTER TABLE retrieval_logs ADD COLUMN {col} INTEGER DEFAULT 0"))
_ensure_token_columns()

def _percentile(values, p):
    """计算分位数：数据从小到大排，取第 p% 位置的值（p=50 就是中位数）"""
    if not values:
        return 0
    values = sorted(values)
    idx = math.ceil(p / 100 * len(values)) - 1
    return round(values[idx], 1)

@router.get("/monitor/stats")
def get_stats(

    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    返回检索监控的汇总统计
    """
    total = db.query(func.count(RetrievalLog.id)).scalar()
    answered = db.query(func.count(RetrievalLog.id)).filter(
        RetrievalLog.can_answer == True
    ).scalar()
    avg_total = db.query(func.avg(RetrievalLog.total_time_ms)).scalar() or 0
    avg_rewrite = db.query(func.avg(RetrievalLog.rewrite_time_ms)).scalar() or 0
    avg_vec = db.query(func.avg(RetrievalLog.vec_search_time_ms)).scalar() or 0
    avg_bm25 = db.query(func.avg(RetrievalLog.bm25_search_time_ms)).scalar() or 0
    avg_rerank = db.query(func.avg(RetrievalLog.rerank_time_ms)).scalar() or 0
    avg_vision = db.query(func.avg(RetrievalLog.vision_time_ms)).scalar() or 0
    avg_generation = db.query(func.avg(RetrievalLog.generation_time_ms)).scalar() or 0
    avg_candidates = db.query(func.avg(RetrievalLog.candidate_count)).scalar() or 0
    avg_valid = db.query(func.avg(RetrievalLog.valid_doc_count)).scalar() or 0

    # ===== 分位数：取最近 100 条算 P50/P95/P99 =====
    recent = db.query(RetrievalLog).order_by(RetrievalLog.id.desc()).limit(100).all()
    total_times = [r.total_time_ms or 0 for r in recent]
    vision_times = [r.vision_time_ms or 0 for r in recent]
    gen_times = [r.generation_time_ms or 0 for r in recent]

    # ===== 成本：token × 单价（RAG 和识图分开算再相加）=====
    sum_prompt = db.query(func.sum(RetrievalLog.prompt_tokens)).scalar() or 0
    sum_completion = db.query(func.sum(RetrievalLog.completion_tokens)).scalar() or 0
    sum_v_prompt = db.query(func.sum(RetrievalLog.vision_prompt_tokens)).scalar() or 0
    sum_v_completion = db.query(func.sum(RetrievalLog.vision_completion_tokens)).scalar() or 0
    rag_cost = sum_prompt / 1000 * settings.INPUT_PRICE_PER_1K + sum_completion / 1000 * settings.OUTPUT_PRICE_PER_1K
    vision_cost = sum_v_prompt / 1000 * settings.VISION_INPUT_PRICE_PER_1K + sum_v_completion / 1000 * settings.VISION_OUTPUT_PRICE_PER_1K
    total_cost = rag_cost + vision_cost

    return {
        "total_queries": total,
        "answered_count": answered,
        "answer_rate": round(answered / total * 100, 1) if total > 0 else 0,
        "avg_total_ms": round(avg_total, 1),
        "avg_rewrite_ms": round(avg_rewrite, 1),
        "avg_vec_search_ms": round(avg_vec, 1),
        "avg_bm25_search_ms": round(avg_bm25, 1),
        "avg_rerank_ms": round(avg_rerank, 1),
        "avg_generation_ms": round(avg_generation, 1),
        "avg_candidates": round(avg_candidates, 1),
        "avg_vision_ms": round(avg_vision, 1),
        "avg_valid_docs": round(avg_valid, 1),
        # 分位数
        "p50_total_ms": _percentile(total_times, 50),
        "p95_total_ms": _percentile(total_times, 95),
        "p99_total_ms": _percentile(total_times, 99),
        "p50_vision_ms": _percentile(vision_times, 50),
        "p95_vision_ms": _percentile(vision_times, 95),
        "p99_vision_ms": _percentile(vision_times, 99),
        "p50_generation_ms": _percentile(gen_times, 50),
        # 成本
        "total_tokens": sum_prompt + sum_completion + sum_v_prompt + sum_v_completion,
        "rag_cost": round(rag_cost, 4),
        "vision_cost": round(vision_cost, 4),
        "total_cost": round(total_cost, 4),
        "avg_cost": round(total_cost / total, 6) if total > 0 else 0,
    }


@router.get("/monitor/logs")
def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    返回检索日志列表(分页,最新在前)
    """
    total = db.query(func.count(RetrievalLog.id)).scalar()
    logs = (
        db.query(RetrievalLog)
        .order_by(RetrievalLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": [
            {
                "id": log.id,
                "question": log.question[:100],
                "can_answer": log.can_answer,
                "total_time_ms": round(log.total_time_ms, 1),
                "rewrite_time_ms": round(log.rewrite_time_ms, 1),
                "vec_search_time_ms": round(log.vec_search_time_ms, 1),
                "bm25_search_time_ms": round(log.bm25_search_time_ms, 1),
                "rerank_time_ms": round(log.rerank_time_ms, 1),
                "generation_time_ms": round(log.generation_time_ms, 1),
                "candidate_count": log.candidate_count,
                "valid_doc_count": log.valid_doc_count,
                "answer_length": log.answer_length,
                "error_message": log.error_message,
                "created_at": str(log.created_at) if log.created_at else "",
            }
            for log in logs
        ],
    }


@router.get("/monitor/trend")
def get_trend(
    limit: int = Query(30, ge=5, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """返回最近 N 条日志的耗时，供前端画趋势图（时间从早到晚）"""
    logs = db.query(RetrievalLog).order_by(RetrievalLog.id.desc()).limit(limit).all()
    logs = list(reversed(logs))   # 倒过来：时间从早到晚，画图更自然
    return {
        "points": [
            {
                "id": log.id,
                "total_time_ms": round(log.total_time_ms or 0, 1),
                "vision_time_ms": round(log.vision_time_ms or 0, 1),
                "generation_time_ms": round(log.generation_time_ms or 0, 1),
                "created_at": str(log.created_at) if log.created_at else "",
            }
            for log in logs
        ]
    }