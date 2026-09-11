from sqlalchemy import JSON, Column, DateTime, Index, Integer, Text, func

from app.database import Base


class RetrievalLog(Base):
    """检索日志：记录每次问答的检索过程明细。

    存在的意义：当用户反馈「这个回答不对」时，能回答一个关键问题——
    **到底是没检索到，还是检索到了但模型没用？**

    没有这张表，所有检索质量问题都只能靠猜。
    """
    __tablename__ = "retrieval_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False)                     # 用户问题（原话）
    # 多轮追问经指代消解后、实际拿去检索的问题（见 services/query_rewrite.py）。
    # 单独存一列而不是覆盖 query：排查检索质量时要能区分
    # 「问题本身写得不好」和「改写改歪了」——这两类问题的修法完全不同。
    rewritten_query = Column(Text, nullable=True)
    user_id = Column(Integer, nullable=True)                 # 提问用户
    conversation_id = Column(Integer, nullable=True)         # 所属会话

    kb_ids = Column(JSON, nullable=True)                     # 检索的知识库 ID 列表
    collection_names = Column(JSON, nullable=True)           # 实际检索的向量集合

    # 两路召回各自的候选（便于对比哪一路更有效）
    vector_hits = Column(JSON, nullable=True)                # [{chunk_id, doc_name, score, rank}]
    bm25_hits = Column(JSON, nullable=True)

    fused_count = Column(Integer, nullable=True)             # RRF 融合后的候选数
    dedup_removed = Column(Integer, nullable=True)           # 被去冗余剔除的条数
    # 精排明细：{model, input_count, output_count, reordered, top_scores}
    # reordered 就是"精排是否真的改变了排序"，用来判断它有没有白跑
    rerank = Column(JSON, nullable=True)
    final_count = Column(Integer, nullable=True)             # 最终注入 Prompt 的片段数
    final_chunk_ids = Column(JSON, nullable=True)            # 最终入选的 chunk ID

    latency_ms = Column(Integer, nullable=True)              # 检索总耗时
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_retrieval_created", "created_at"),
        Index("idx_retrieval_query", "query", mysql_length={"query": 191}),
    )
