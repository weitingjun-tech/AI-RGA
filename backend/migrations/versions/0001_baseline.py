"""baseline schema — 项目纳入 Alembic 管理时的既有表结构

这是"历史基线"，代表引入 Alembic 之前由 Base.metadata.create_all 建出来的那套表。
已经用旧版本跑起来的数据库，会被 stamp 到这个版本（不重复建表）；
全新的数据库则从这里开始，再依次执行后续迁移。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("admin", "user", name="user_role"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_updated", "conversations", ["user_id", "updated_at"], unique=False)

    # 多知识库隔离：每个知识库绑定一个独立的向量集合
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("collection_name", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_name"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        # 注意：此时还没有 "queued" 状态 —— 它是随任务队列一起引入的，
        # 由 0002 迁移添加。迁移历史按时间顺序演进，不要回头改这个定义。
        sa.Column(
            "status",
            sa.Enum("processing", "ready", "error", name="doc_status"),
            nullable=False,
        ),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("kb_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_kb_id"), "documents", ["kb_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("user", "assistant", name="message_role"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        # 用户反馈闭环
        sa.Column("feedback", sa.Enum("up", "down", name="feedback_type"), nullable=True),
        sa.Column("feedback_reason", sa.String(length=64), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(), nullable=True),
        sa.Column("retrieval_log_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_conv_time", "messages", ["conversation_id", "created_at"], unique=False)

    # 检索可观测性：记录每次检索的双路候选、融合、耗时
    op.create_table(
        "retrieval_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("kb_ids", sa.JSON(), nullable=True),
        sa.Column("collection_names", sa.JSON(), nullable=True),
        sa.Column("vector_hits", sa.JSON(), nullable=True),
        sa.Column("bm25_hits", sa.JSON(), nullable=True),
        sa.Column("fused_count", sa.Integer(), nullable=True),
        sa.Column("dedup_removed", sa.Integer(), nullable=True),
        sa.Column("final_count", sa.Integer(), nullable=True),
        sa.Column("final_chunk_ids", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_retrieval_created", "retrieval_logs", ["created_at"], unique=False)
    # TEXT 列不能直接建索引，必须指定前缀长度（MySQL 限制 767 字节）
    op.create_index(
        "idx_retrieval_query", "retrieval_logs", ["query"], unique=False,
        mysql_length={"query": 191},
    )


def downgrade() -> None:
    op.drop_index("idx_retrieval_query", table_name="retrieval_logs", mysql_length={"query": 191})
    op.drop_index("idx_retrieval_created", table_name="retrieval_logs")
    op.drop_table("retrieval_logs")

    op.drop_index("idx_conv_time", table_name="messages")
    op.drop_table("messages")

    op.drop_index(op.f("ix_documents_kb_id"), table_name="documents")
    op.drop_table("documents")

    op.drop_table("knowledge_bases")

    op.drop_index("idx_user_updated", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
