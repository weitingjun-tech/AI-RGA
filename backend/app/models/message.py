from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum("user", "assistant", name="message_role"), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)  # [{doc_id, doc_name, chunk_id, text_snippet, score}]
    created_at = Column(DateTime, server_default=func.now())

    # ========== 用户反馈闭环 ==========
    # 没有反馈数据，所有质量优化都是拍脑袋。
    # 点赞/点踩 + 原因标签是「生产问题 → 测试用例 → 防回归」正循环的起点。
    feedback = Column(Enum("up", "down", name="feedback_type"), nullable=True)
    feedback_reason = Column(String(64), nullable=True)   # 不准确 / 不完整 / 过时 / 无关 / 其他
    feedback_comment = Column(Text, nullable=True)        # 用户补充说明
    feedback_at = Column(DateTime, nullable=True)
    # 关联当次检索明细，使反馈可一路追溯到「当时检索到了什么」
    retrieval_log_id = Column(Integer, nullable=True)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("idx_conv_time", "conversation_id", "created_at"),
    )