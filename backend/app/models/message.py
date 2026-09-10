from app.database import Base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, Index, Enum, func
from sqlalchemy.orm import relationship

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum("user", "assistant", name="message_role"), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)  # [{doc_id, doc_name, chunk_id, text_snippet, score}]
    created_at = Column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("idx_conv_time", "conversation_id", "created_at"),
    )