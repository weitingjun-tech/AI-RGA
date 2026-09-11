from app.database import Base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger, Enum, func

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    chunk_count = Column(Integer, default=0)
    # queued    = 已入队，等待 worker 领取
    # processing= worker 正在处理
    # ready     = 处理完成，可被检索
    # error     = 处理失败（重试次数耗尽）
    # 区分 queued / processing 的意义：队列积压时运维能一眼看出是"没 worker"还是"处理太慢"
    status = Column(
        Enum("queued", "processing", "ready", "error", name="doc_status"),
        default="queued",
        nullable=False,
    )
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True, index=True)  # 所属知识库
    created_at = Column(DateTime, server_default=func.now())