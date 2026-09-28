import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.knowledge import rag
from app.core.logger import logger
from app.database import get_db, engine, Base
from app.models import User
from app.models.chat_history import ChatHistory
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RAGService
from app.services.vision_service import describe_product

Base.metadata.create_all(bind=engine)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    对话接口：接收用户问题，流式（SSE）返回回答。

    支持图片识图：request.image 有值时，先用视觉模型把图片转成文字，再拼进问题做 RAG。
    """
    logger.info(f"收到对话请求: {request.question[:50]}...")

    # 提前取出 user_id：生成器运行时会话可能已关闭，不能在生成器里访问 current_user
    uid = current_user.id
    session_id = request.session_id or "default"

    rows = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.user_id == uid,
            ChatHistory.session_id == session_id
        )
        .order_by(ChatHistory.id.desc())
        .limit(8)
        .all()
    )
    history = [{"role": r.role, "content": r.content} for r in reversed(rows)]

    db.add(ChatHistory(user_id=uid, session_id=session_id, role="user", content=request.question))
    db.commit()

    # 识图：先把图片识别成文字（带耗时监控）
    user_question = request.question
    has_image = False
    vision_time_ms = 0
    v_in = v_out = 0
    if request.image:
        has_image = True
        t_vision = time.time()
        try:
            product_desc, v_in, v_out = describe_product(request.image)
            user_question = f"{user_question}\n[图片识别结果]{product_desc}"
        except Exception as e:
            logger.warning(f"图片识别失败，按纯文本处理: {e}")
            user_question = request.question
        finally:
            vision_time_ms = round((time.time() - t_vision) * 1000, 2)

    async def event_stream():
        import json
        full_answer = ""
        meta_sent = False
        try:
            for chunk in rag.query(
                user_question,
                messages=history,
                user_id=uid,
                has_image=has_image,
                vision_time_ms=vision_time_ms,
                vision_prompt_tokens=v_in,
                vision_completion_tokens=v_out
            ):
                if not meta_sent:
                    meta_sent = True
                    yield f"data: {chunk}\n\n"
                else:
                    full_answer += chunk
                    # JSON 编码答案段，防止回答里的换行符破坏 SSE 帧
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            db.add(ChatHistory(user_id=uid, session_id=session_id, role="assistant", content=full_answer))
            db.commit()
        except Exception as e:
            logger.error(f"流式对话异常: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chat/history")
def get_chat_history(
        session_id: str = "default",
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """返回当前用户指定会话的历史记录（从早到晚）"""
    rows = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.user_id == current_user.id,
            ChatHistory.session_id == session_id
        )
        .order_by(ChatHistory.id.desc())
        .limit(30)
        .all()
    )
    history = [
        {"role": r.role, "content": r.content}
        for r in reversed(rows)
    ]
    return {"history": history}


@router.post("/chat/clear")
def clear_chat_history(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """删除当前用户的所有历史记录"""
    db.query(ChatHistory).filter(ChatHistory.user_id == current_user.id).delete()
    db.commit()
    return {"message": "历史已清空"}


@router.get("/chat/sessions")
def get_sessions(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """返回所有会话：标题取首条用户消息，最近时间取最新消息"""
    rows = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .order_by(ChatHistory.id.desc())
        .all()
    )
    first_user_msg = {}
    updated_at = {}
    for r in rows:
        if r.session_id not in updated_at:
            updated_at[r.session_id] = r.created_at
        if r.role == "user" and r.session_id not in first_user_msg:
            first_user_msg[r.session_id] = r.content[:20]
    sessions = []
    for sid in updated_at:
        sessions.append({
            "session_id": sid,
            "title": first_user_msg.get(sid) or "新对话",
            "updated_at": str(updated_at[sid]) if updated_at[sid] else "",
        })
    result = sorted(sessions, key=lambda s: s["updated_at"], reverse=True)
    return {"sessions": result}


@router.delete("/chat/session/{session_id}")
def delete_session(
        session_id: str,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """删除当前用户的指定会话"""
    db.query(ChatHistory).filter(
        ChatHistory.user_id == current_user.id,
        ChatHistory.session_id == session_id
    ).delete()
    db.commit()
    return {"message": "会话已删除"}