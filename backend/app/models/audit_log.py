from app.database import Base
from sqlalchemy import Column, DateTime, Index, Integer, String, Text, func


class AuditLog(Base):
    """操作审计日志。

    回答的是"谁、在什么时候、对哪个对象、做了什么"——
    用户点踩的 retrieval_logs 记录的是"检索过程明细"，两者不是一回事。

    为什么要把 username 冗余存一份：
    用户被删除后，外键指向的记录就没了归属，审计线索会断。
    审计日志的价值恰恰在于事后追查，所以这里刻意反范式。
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)        # 不设外键：用户删了日志要留
    username = Column(String(64), nullable=True)    # 冗余，防用户删除后线索断裂
    action = Column(String(64), nullable=False)     # document.upload / document.delete ...
    target_type = Column(String(32), nullable=True)  # document / knowledge_base / user
    target_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)            # JSON 字符串，记录文件名、大小等
    ip = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=True)  # 关联到当次请求的完整日志
    status = Column(String(16), nullable=False, default="success")  # success / failure
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        # 审计查询几乎总是"按人查"或"按时间倒序查"
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_created", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )
