"""
对话历史表:存每个用户的聊天记录(长期记忆)
对应数据库中的 chat_history 表
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.database import Base


class ChatHistory(Base):
    """
    对话历史表
    每行 = 一条消息(用户说的 或 助手回的)
    按 user_id 区分是哪个用户的
    """
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)   # 哪个用户的消息
    session_id = Column(String(64), index=True, nullable=False, default="default")  # 属于哪个会话
    role = Column(String(20), nullable=False)               # "user" 或 "assistant"
    content = Column(Text, nullable=False)                  # 消息内容(可能很长,用 Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ChatHistory(id={self.id}, user_id={self.user_id}, role={self.role})>"
