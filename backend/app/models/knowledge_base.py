from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class KnowledgeBase(Base):
    """知识库：一个知识库对应 ChromaDB 中一个独立的向量集合，实现互相隔离。

    设计要点：
    - 每个知识库绑定一个 ChromaDB collection（collection_name 全局唯一）
    - 文档通过 Document.kb_id 归属到知识库
    - 检索时可指定一个或多个知识库，避免无关语料污染结果
    """
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)          # 知识库名称
    description = Column(String(512), nullable=True)                 # 描述
    collection_name = Column(String(128), nullable=False, unique=True)  # ChromaDB 集合名
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_default = Column(String(10), default="false", nullable=True)  # 是否为默认知识库
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    documents = relationship("Document", backref="knowledge_base")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "collection_name": self.collection_name,
            "created_by": self.created_by,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
