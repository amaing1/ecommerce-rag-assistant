"""
分块模型
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    chunk_index = Column(Integer, nullable=False)           # 在文档中的序号（第0块、第1块...）
    content = Column(Text, nullable=False)                 # 分块的原文内容
    content_length = Column(Integer, nullable=False)       # 分块的长度（字符数）
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ✍️ 这一行你必须亲手敲
    document = relationship("Document", back_populates="chunks")

    def __repr__(self):
        return f"<Chunk(id={self.id}, document_id={self.document_id}, chunk_index={self.chunk_index}, length={self.content_length})>"