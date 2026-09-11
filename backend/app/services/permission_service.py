"""知识库访问控制（ACL）。

**核心原则：检索前过滤，而不是检索后过滤。**

举例说明为什么：假设"财务制度"知识库里有薪资表，销售角色无权访问。
用户问"高级工程师的薪资范围是多少"。

- 检索后过滤：向量库先把薪资那段召回出来 → 写进 retrieval_logs →
  拼进 Prompt 送给 LLM → 再按权限把结果筛掉。
  结果是：机密内容已经进了日志、进了模型上下文，日志有可能被运维看到，
  模型也可能在总结时带出细节。**这已经不是"没看到"，而是已经泄露了。**
- 检索前过滤：构造查询时根本不包含那个 collection，机密内容从未离开数据库。

所以本模块的职责是：在检索发生**之前**，把用户请求的知识库范围收敛到他有权限的那些。
"""
import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import KB_ACL_ENABLED
from app.models.kb_permission import KbPermission
from app.models.user import User

logger = logging.getLogger("rag-app")


def get_accessible_kb_ids(
    db: Session, user: User, need_write: bool = False
) -> Optional[set[int]]:
    """返回用户可访问的知识库 ID 集合。

    返回 None 表示"不受限"（管理员，或 ACL 未启用）——调用方需区分
    "全是空集合" 和 "不受限" 这两种情况，前者表示什么都看不到。
    """
    if not KB_ACL_ENABLED or user.role == "admin":
        return None

    query = db.query(KbPermission.kb_id).filter(KbPermission.user_id == user.id)
    if need_write:
        query = query.filter(KbPermission.permission == "write")
    return {row[0] for row in query.all()}


def can_access_kb(db: Session, user: User, kb_id: int, need_write: bool = False) -> bool:
    allowed = get_accessible_kb_ids(db, user, need_write=need_write)
    return allowed is None or kb_id in allowed


def require_kb_access(
    db: Session, user: User, kb_id: int, need_write: bool = False
) -> None:
    """校验失败时抛 403。用于单个知识库的操作。"""
    if not can_access_kb(db, user, kb_id, need_write=need_write):
        # 不区分"不存在"和"无权限"是有意为之的取舍：
        # 返回 403 会暴露"这个 ID 确实存在"，但对内部系统来说，
        # 让用户能区分"我该申请权限"和"这个库没了"更有用。
        action = "写入" if need_write else "访问"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权{action}该知识库（kb_id={kb_id}），请联系管理员授权",
        )


def resolve_query_kb_ids(
    db: Session, user: User, requested: Optional[list[int]]
) -> list[int]:
    """把请求中的 kb_ids 收敛为实际可检索的集合。

    关键点：**requested 为 None 表示"全部知识库"，必须展开成"我有权限的那些"，
    而不是真的去检索全部**——后者就是权限绕过。
    """
    allowed = get_accessible_kb_ids(db, user)

    if allowed is None:
        # 管理员 / ACL 关闭：requested 为空则交给上层检索全部
        return requested or []

    if not allowed:
        # 没有任何授权。返回空列表让上层直接返回"无可用知识库"，
        # 绝不能因为列表为空就退化成"检索全部"。
        logger.info(f"用户无任何知识库授权 user_id={user.id}")
        return []

    if not requested:
        return sorted(allowed)

    # 取交集：请求了但无权限的直接剔除，不报错
    # （报错等于告诉对方"存在一个你访问不了的库"，会泄露知识库的存在性）
    permitted = [kb_id for kb_id in requested if kb_id in allowed]
    if not permitted:
        logger.warning(
            f"用户请求的知识库全部无权限 user_id={user.id} requested={requested}"
        )
    elif len(permitted) != len(requested):
        logger.warning(
            f"用户请求中部分知识库无权限，已剔除 user_id={user.id} "
            f"requested={requested} permitted={permitted}"
        )
    return permitted
