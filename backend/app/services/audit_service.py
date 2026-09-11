"""审计日志写入。

**设计原则：审计失败绝不能影响主业务。**
写审计日志失败（表不存在、磁盘满、字段超长）时只记一条告警，
不能让"上传文档"这种核心操作因为日志写不进去而失败。
听起来反直觉，但审计是"附加证据"，不是业务前置条件。
"""
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import AUDIT_LOG_ENABLED
from app.models.audit_log import AuditLog
from app.utils.request_context import get_request_id

logger = logging.getLogger("rag-app")

_MAX_DETAIL_LENGTH = 4000


def audit_log(
    db: Session,
    user: Any,
    action: str,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict | None = None,
    status: str = "success",
    ip: str | None = None,
) -> None:
    """记录一条审计日志。

    user 传 User 对象或 None；None 时记为匿名（例如登录失败，此时还没有用户）。
    """
    if not AUDIT_LOG_ENABLED:
        return

    try:
        payload = json.dumps(detail, ensure_ascii=False) if detail else None
        if payload and len(payload) > _MAX_DETAIL_LENGTH:
            # 截断而不是丢弃：宁可留下部分证据，也不要有日志空洞
            payload = payload[:_MAX_DETAIL_LENGTH] + "...(truncated)"

        db.add(
            AuditLog(
                user_id=getattr(user, "id", None),
                username=getattr(user, "username", None),
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=payload,
                ip=ip,
                request_id=get_request_id(),
                status=status,
            )
        )
        db.commit()
    except Exception as exc:
        # 回滚掉失败的插入，否则会把调用方的 session 一起弄脏
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"审计日志写入失败 action={action}: {exc}")
