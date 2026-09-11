"""管理端 API：审计日志查询。

审计数据如果只能写不能看，等于没做——出事时没人能拿到线索。
所以这里提供按人、按动作、按时间检索的接口。
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_admin_user
from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger("rag-app")

router = APIRouter(prefix="/api/admin", tags=["管理端"])


@router.get("/audit-logs")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    action: Optional[str] = None,
    username: Optional[str] = None,
    days: int = Query(7, ge=1, le=365, description="只查最近 N 天"),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """查询审计日志（默认最近 7 天）。

    默认限定时间范围是有意的：审计表只增不减，全表扫描会随运行时间越来越慢。
    需要查更早的记录时显式传 days。
    """
    query = db.query(AuditLog).filter(
        AuditLog.created_at >= datetime.now() - timedelta(days=days)
    )
    if action:
        # 前缀匹配：传 "document" 能同时匹配 document.upload / document.delete
        query = query.filter(AuditLog.action.like(f"{action}%"))
    if username:
        query = query.filter(AuditLog.username == username)

    total = query.count()
    rows = (
        query.order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "logs": [
            {
                "id": r.id,
                "username": r.username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "ip": r.ip,
                "request_id": r.request_id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/audit-logs/actions")
def list_audit_actions(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """列出出现过的动作类型，供前端做筛选下拉框。

    比硬编码枚举好：新增了动作类型，筛选框自动就有，不用改前端。
    """
    rows = db.query(AuditLog.action).distinct().all()
    return {"actions": sorted(r[0] for r in rows)}
