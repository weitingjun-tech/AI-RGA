from app.database import Base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger, Enum, func

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    chunk_count = Column(Integer, default=0)
    status = Column(Enum("processing", "ready", "error", name="doc_status"), default="processing", nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True, index=True)  # 所属知识库
    created_at = Column(DateTime, server_default=func.now())