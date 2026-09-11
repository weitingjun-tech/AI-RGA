"""enterprise hardening — 审计日志、知识库权限、文档队列状态

对应「企业级落地」这一批改动，包含三类迁移操作，正好覆盖实际会遇到的三种情况：
  1. 建新表（audit_logs / kb_permissions）
  2. **改已有列的类型**（documents.status 增加 queued 状态）——
     这是手写迁移脚本最难做、也最容易出错的一类，正是引入 Alembic 的理由
  3. **数据迁移**（给存量用户补授权）——不只是改结构，还要搬数据

Revision ID: 0002_enterprise_hardening
Revises: 0001_baseline
Create Date: 2026-09-11
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_enterprise_hardening"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. 审计日志：谁在什么时候对什么对象做了什么
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # 刻意不加外键：用户被删除后审计记录必须保留，否则线索就断了
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"], unique=False
    )

    # ------------------------------------------------------------------
    # 2. 知识库权限（ACL）
    # ------------------------------------------------------------------
    op.create_table(
        "kb_permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 同一用户对同一知识库只能有一条授权记录
        sa.UniqueConstraint("user_id", "kb_id", name="uq_kb_permission_user_kb"),
    )
    op.create_index("ix_kb_permissions_user", "kb_permissions", ["user_id"], unique=False)

    # ------------------------------------------------------------------
    # 3. documents.status 增加 "queued" 状态
    # ------------------------------------------------------------------
    # 引入任务队列后，文档会先进入"排队中"再被 worker 领取执行。
    # 区分 queued / processing 让运维能一眼看出队列是积压了还是没 worker。
    #
    # MySQL 的 ENUM 以序号存储，直接在头部插入新值会改变已有值的序号。
    # MODIFY COLUMN 会按**值**而非序号重建整列，所以存量数据不会错乱——
    # 但这正是手写迁移容易踩的坑，必须理解清楚才敢改。
    op.alter_column(
        "documents",
        "status",
        existing_type=sa.Enum("processing", "ready", "error", name="doc_status"),
        type_=sa.Enum("queued", "processing", "ready", "error", name="doc_status"),
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # 4. 数据迁移：给存量用户补上原有的访问范围
    # ------------------------------------------------------------------
    # 引入 ACL 之前，所有登录用户都能检索全部知识库。
    # 如果直接启用 ACL 而不补授权，升级后普通用户会突然"一个知识库都看不到"，
    # 表现为功能故障。
    #
    # 因此这里把原有的访问范围原样保留下来（所有存量用户 → 所有存量知识库）。
    # 管理员不写授权记录 —— 他们本来就无限制，写进去只会让权限表产生误导性的数据。
    #
    # ⚠️ 这是"保持现状"而非"最小权限"。升级后管理员应当按实际组织架构
    # 重新梳理授权（撤销多余的、补充缺失的），再做收紧。
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "INSERT INTO kb_permissions (user_id, kb_id, permission, granted_by, created_at) "
            "SELECT u.id, k.id, 'read', NULL, NOW() "
            "FROM users u CROSS JOIN knowledge_bases k "
            "WHERE u.role <> 'admin'"
        )
    )
    if result.rowcount:
        logger.warning(
            "已为 %d 条「存量用户 ↔ 知识库」组合保留原有读权限。"
            "这是保持升级前后行为一致，请尽快按组织架构重新梳理授权。",
            result.rowcount,
        )


def downgrade() -> None:
    # 回滚顺序与创建顺序相反。
    # 注意：把 documents.status 改回三值枚举时，**处于 queued 状态的记录会丢失信息**
    # （被 MySQL 转成枚举的第一个值 processing）。这是有损回滚，无法自动还原。
    # 所以回滚前应先确认没有 queued 状态的文档，例如：
    #   UPDATE documents SET status='processing' WHERE status='queued';
    bind = op.get_bind()
    queued = bind.execute(
        sa.text("SELECT COUNT(*) FROM documents WHERE status = 'queued'")
    ).scalar()
    if queued:
        raise RuntimeError(
            f"有 {queued} 个文档处于 queued 状态，回滚会导致这些记录的状态失真。\n"
            "请先执行：UPDATE documents SET status='processing' WHERE status='queued';\n"
            "再重新执行 downgrade。"
        )

    op.alter_column(
        "documents",
        "status",
        existing_type=sa.Enum("queued", "processing", "ready", "error", name="doc_status"),
        type_=sa.Enum("processing", "ready", "error", name="doc_status"),
        existing_nullable=False,
    )

    op.drop_index("ix_kb_permissions_user", table_name="kb_permissions")
    op.drop_table("kb_permissions")

    op.drop_index("ix_audit_logs_user_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
