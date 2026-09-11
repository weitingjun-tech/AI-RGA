"""检索质量优化 — 精排明细与改写后的问题

对应两处检索链路的增强，各加一列可观测信息：
  1. retrieval_logs.rerank           —— Cross-Encoder 精排的明细
  2. retrieval_logs.rewritten_query  —— 多轮追问经指代消解后、真正用于检索的问题

**为什么加的是"可观测字段"而不是"业务字段"**
这两列不参与业务逻辑，只影响事后归因能力。但正是它们让新功能**可被验证**：
  - `rerank.reordered = 0` 说明精排压根没改变排序 → 要么模型没区分度，要么接错了
  - `rewritten_query IS NOT NULL` 能直接统计改写的触发率
没有这两列，出了问题只能靠猜「精排到底生效了没」。

两列都允许为 NULL：历史数据不需要回填，新功能关闭时也不写入。

Revision ID: 0003_rerank_query_rewrite
Revises: 0002_enterprise_hardening
Create Date: 2026-09-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_rerank_query_rewrite"
down_revision: Union[str, None] = "0002_enterprise_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = "fk_documents_kb_id"


def _existing_fk_columns(bind, table: str) -> set[str]:
    """列出某个表上**已被外键约束覆盖**的列。"""
    return {
        col
        for fk in sa.inspect(bind).get_foreign_keys(table)
        for col in (fk.get("constrained_columns") or [])
    }


def upgrade() -> None:
    # 加列是**可空、无默认值**的操作，MySQL 下是 INSTANT DDL，
    # 不需要重建表、不锁表，几百万行也是秒级完成。
    # （对比：给已有列加 NOT NULL DEFAULT 在新版 MySQL 是 INSTANT，
    #   但改列类型/加索引就要重建，那才是需要停机窗口的操作。）
    op.add_column(
        "retrieval_logs",
        sa.Column("rewritten_query", sa.Text(), nullable=True),
    )
    op.add_column(
        "retrieval_logs",
        sa.Column("rerank", sa.JSON(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 顺带补一个**一直缺失的外键**
    #
    # documents.kb_id 在模型里写了 ForeignKey("knowledge_bases.id")，
    # 但数据库里从来没有这条约束——当初加"多知识库"字段时漏了配套迁移，
    # 属于典型的"模型和数据库悄悄跑偏"。
    #
    # 是 `alembic check` 把它揪出来的（本次改动的副产品）：
    # 这类漂移靠人眼读代码永远发现不了，只有拿模型和真实库对账才会暴露。
    #
    # 影响：删知识库时文档不会级联清理，会留下 kb_id 指向已删库的孤儿记录。
    #
    # **必须先判断再创建，不能无条件执行。**
    #
    # 各环境的起点并不一致：本地开发库是早期用 `create_all()` 建的，这条外键
    # 确实缺失；而容器库是由迁移建起来的，`documents_ibfk_1` 本来就在。
    # 无条件创建会在容器库上多出一条一模一样的约束——功能上无害，
    # 但两个相同约束意味着双份索引维护开销，而且 `alembic check`
    # **查不出来**（它只比对"这一列有没有外键"，不管有没有多）。
    # 这类问题只能靠人看 information_schema 才会发现。
    #
    # 执行前已确认 documents 表零孤立记录（kb_id 都指向存在的知识库），
    # 因此可以安全添加；若在别的库上有孤儿行，这一步会失败——
    # 那时的正确做法是先清理孤儿行，而不是跳过约束。
    # ------------------------------------------------------------------
    if "kb_id" not in _existing_fk_columns(op.get_bind(), "documents"):
        op.create_foreign_key(
            _FK_NAME, "documents", "knowledge_bases", ["kb_id"], ["id"]
        )


def downgrade() -> None:
    # 两列都是纯附加信息，删除不影响任何业务逻辑的正常运行，
    # 因此这里不需要像 0002 那样加数据安全检查。
    #
    # 外键的删除同样要判断：它是条件创建的，在不缺外键的环境里
    # （例如容器库）根本没建过，直接 drop 会因为"约束不存在"而报错，
    # 让整条回滚路径失效。**迁移的 downgrade 必须能无条件跑通**，
    # 否则真出事时才发现回不去。
    if _FK_NAME in {
        fk["name"] for fk in sa.inspect(op.get_bind()).get_foreign_keys("documents")
    }:
        op.drop_constraint(_FK_NAME, "documents", type_="foreignkey")

    op.drop_column("retrieval_logs", "rerank")
    op.drop_column("retrieval_logs", "rewritten_query")
