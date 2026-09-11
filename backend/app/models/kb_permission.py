from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)

from app.database import Base


class KbPermission(Base):
    """用户对知识库的访问授权。

    **为什么必须要这张表**
    没有它时，任何登录用户都能检索任意知识库——企业客户的第一句话就是
    "我们文档分部门，销售的不能看到财务的"，没有这条就谈不下去。

    **为什么是"检索前过滤"而不是"检索后过滤"**
    检索后再筛掉无权限的结果，有两个问题：
      1. 无权限的内容已经被读进内存、写进 retrieval_logs、甚至送进了 LLM 上下文，
         从数据安全角度已经算泄露了
      2. Top-K 名额被无权限内容占掉，用户看到的结果比实际可用的少
    所以必须在构造检索请求时就限定 collection 范围。

    权限粒度只分读/写两档，没有再细分：
    再细（按文档、按字段、按时间）在中小规模场景收益很低，
    但会让权限模型复杂到难以维护和审计。
    """

    __tablename__ = "kb_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(
        Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    # read  = 可以检索该知识库
    # write = 额外可以上传/删除该知识库的文档（隐含 read）
    permission = Column(String(16), nullable=False, default="read")
    granted_by = Column(Integer, nullable=True)  # 授权人，用于追责
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        # 同一用户对同一知识库只允许一条记录，避免重复授权导致权限判断歧义
        UniqueConstraint("user_id", "kb_id", name="uq_kb_permission_user_kb"),
        # 鉴权是每次检索都要走的路径，必须有索引
        Index("ix_kb_permissions_user", "user_id"),
    )
