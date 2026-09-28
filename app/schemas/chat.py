from pydantic import BaseModel
from typing import List, Optional


class ChatRequest(BaseModel):
    """对话请求体"""
    question: str
    top_k: Optional[int] = 5
    session_id: Optional[str] = "default"   # 属于哪个会话(前端新建对话时生成)
    messages: Optional[List[dict]] = []  ###✅ 不传也没事 → 默认空列表 []
    image: Optional[str] = None


class ChatResponse(BaseModel):
    """对话响应体"""
    answer: str
    sources: List[str]
    can_answer: bool