"""
用户模型：对应数据库里的 users 表，存「谁在用这个系统」。
"""

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)  # 存哈希值，不是明文密码
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # User 是顶层表，关联关系在子表（KnowledgeBase）里通过 backref 反向关联
    def __repr__(self):
        """打印对象时显示关键信息，便于调试"""
        return f"<User(id={self.id}, username={self.username})>"