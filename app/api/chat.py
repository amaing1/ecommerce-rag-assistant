# ============================================================
# 第0块：导入依赖
# ============================================================

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import RAGService
from app.core.logger import logger
from app.api.knowledge import rag
from app.services.vision_service import describe_product
from fastapi import Depends
from app.api.deps import get_current_user
from app.models import User
from sqlalchemy.orm import Session
from app.database import get_db, engine, Base
from app.models.chat_history import ChatHistory
import time
# 确保 chat_history 表存在(幂等,已存在则跳过)
Base.metadata.create_all(bind=engine)
# 创建路由实例：这个文件里的所有路由都挂在这个 router 上
# 然后在 main.py 里用 app.include_router(chat.router) 注册
router = APIRouter()

# ============================================================
# 第1块：从knowledge中引入rag
# ============================================================
# RAGService 内部会加载向量模型、重排序模型、连接 Chroma
# 如果每个请求都重新创建，会导致严重的性能问题


# ⚠️ 注意：这里没有加载知识库数据！
# 知识库需要通过 /knowledge/upload 接口上传后才能使用
# 如果直接调用 /chat 而没有先上传文档，会报 "BM25 索引未初始化" 错误

# ============================================================
# 第2块：接口函数（核心逻辑）
# ============================================================

@router.post("/chat", response_model=ChatResponse)
async def chat(
        request: ChatRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    对话接口：接收用户问题，调用 RAG 服务，返回回答和来源

    请求体格式（ChatRequest）：
        - question: str       必填，用户问题
        - top_k: int          可选，返回来源条数，默认 5

    响应体格式（ChatResponse）：
        - answer: str         最终答案（Day 8 接入生成后才有）
        - sources: List[str]  来源文档片段（最多 top_k 条）
        - can_answer: bool    是否能回答
    """
    # 1. 记录日志（截取前 50 个字符，避免日志过长）
    logger.info(f"收到对话请求: {request.question[:50]}...")

    # 提前取出 user_id(普通整数)。不能在生成器里访问 current_user,
    # 因为流式生成器执行时,current_user 绑定的 session 可能已关闭
    uid = current_user.id
    session_id = request.session_id or "default"

    # 从数据库加载这个会话最近 8 条历史(长期记忆,按 session_id 区分)
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

    # 保存用户问题(带 session_id)
    db.add(ChatHistory(user_id=uid, session_id=session_id, role="user", content=request.question))
    db.commit()

    ###### ====== 识图桥接: 如果用户发了图片，先识别成文字（带耗时监控） ======
    user_question = request.question
    has_image = False
    vision_time_ms = 0
    v_in = v_out = 0
    if request.image:
        has_image = True
        t_vision = time.time()
        try:
            product_desc,v_in,v_out = describe_product(request.image)
            user_question = f"{user_question}\n[图片识别结果]{product_desc}"
        except Exception as e:
            ##识别失败，记日志，但问题保持原样，
            logger.warning(f"图片识别失败，按纯文本处理: {e}")
            user_question = request.question
        finally:
            vision_time_ms = round((time.time() - t_vision) * 1000, 2)


    # 定义 SSE 流式生成器:第一段是元信息(JSON),后面是答案文本
    async def event_stream():
        import json
        full_answer = ""
        meta_sent = False   # 独立标志:是否已转发过第一段(元信息)
        try:
            for chunk in rag.query(user_question, messages=history, user_id=uid,has_image=has_image,vision_time_ms=vision_time_ms,vision_prompt_tokens=v_in,vision_completion_tokens=v_out):
                if not meta_sent:
                    # 第一段:元信息(JSON),原样转发(不拼进答案)
                    meta_sent = True
                    yield f"data: {chunk}\n\n"
                else:
                    # 后续段:答案文本,拼进 full_answer 并转发
                    # 🔧 修复:JSON编码答案段,防止回答里的换行符破坏SSE帧导致内容丢失
                    full_answer += chunk
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            # 循环结束:把完整回答存进数据库(带 session_id)
            db.add(ChatHistory(user_id=uid, session_id=session_id, role="assistant", content=full_answer))
            db.commit()
        except Exception as e:
            logger.error(f"流式对话异常: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ============================================================
# 获取当前用户的聊天历史(长期记忆的"读取"口)
# ============================================================
@router.get("/chat/history")
def get_chat_history(
        session_id: str = "default",
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    返回当前用户指定会话的历史记录(从早到晚)
    前端打开页面时调用,用于显示聊天记录
    """
    rows = (
        db.query(ChatHistory)
        .filter(
            ChatHistory.user_id == current_user.id,
            ChatHistory.session_id == session_id
        )
        .order_by(ChatHistory.id.desc())
        .limit(30)          # 最多返回 30 条
        .all()
    )
    # 倒序取回,反转成"从早到晚"
    history = [
        {"role": r.role, "content": r.content}
        for r in reversed(rows)
    ]
    return {"history": history}

# ============================================================
# 清空当前用户的聊天历史(新对话/删除记录用)
# ============================================================
@router.post("/chat/clear")
def clear_chat_history(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """删除当前用户的所有历史记录"""
    db.query(ChatHistory).filter(ChatHistory.user_id == current_user.id).delete()
    db.commit()
    return {"message": "历史已清空"}

# ============================================================
# 列出当前用户的所有会话(用于侧边栏)
# ============================================================
@router.get("/chat/sessions")
def get_sessions(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """返回所有会话:标题取"首条用户消息",最近时间取最新消息"""
    rows = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .order_by(ChatHistory.id.desc())   # 最新在前
        .all()
    )
    first_user_msg = {}   # session_id -> 第一条用户消息(标题)
    updated_at = {}       # session_id -> 最新时间
    for r in rows:
        if r.session_id not in updated_at:
            updated_at[r.session_id] = r.created_at
        # 找最早的用户消息作标题(豆包风格:标题=对话主题,稳定不变)
        if r.role == "user" and r.session_id not in first_user_msg:
            first_user_msg[r.session_id] = r.content[:20]
    sessions = []
    for sid in updated_at:
        sessions.append({
            "session_id": sid,
            "title": first_user_msg.get(sid) or "新对话",
            "updated_at": str(updated_at[sid]) if updated_at[sid] else "",
        })
    # 按时间倒序(最近的在最上)
    result = sorted(sessions, key=lambda s: s["updated_at"], reverse=True)
    return {"sessions": result}


# ============================================================
# 删除单个会话
# ============================================================
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

# # ============================================================
# # 踩坑记录（供后续复查）
# # ============================================================
#
# """
# 📌 在编写 chat.py 过程中遇到的错误及修复方法：
#
# 1. BM25 索引未初始化
#    报错：错误：还没有执行 build_index 加载文档，BM25 索引未初始化！
#    原因：RAGService 实例创建后，没有调用 load_knowledge_base() 加载任何数据，
#         导致 self.bm25 仍为 None，调用 hybrid_query 时触发检查。
#    临时修复：在 chat.py 中手动加载模拟数据（测试用）。
#    正式方案：Day 8 实现 /knowledge/upload 接口，通过上传文件动态加载知识库。
#    注意：模拟数据在测试完成后已删除，现在必须通过上传接口加载数据。
#
# 2. Windows PowerShell 中 curl 命令失效
#    报错：Invoke-WebRequest : 无法绑定参数“Headers”
#    原因：PowerShell 中的 curl 是 Invoke-WebRequest 的别名，语法不同。
#    解决：使用浏览器访问 /docs 页面，通过 Swagger UI 测试接口，更方便。
# 3. 大模型生成答案为空
#    现象：/chat 返回的 answer 字段始终为空字符串。
#    原因：RAGService.query() 在 can_answer=True 时，reply 字段设计为空，
#         因为生成答案的步骤尚未接入（计划 Day 8 或 Day 9 实现）。
#    状态：这是设计如此，不是 bug，待后续接入大模型生成。
#
# 4. 服务启动后 /chat 报错 500
#    原因：未加载知识库，BM25 索引为空。
#    修复：确认已通过上传接口或临时加载方式建立了索引。
# """
#


