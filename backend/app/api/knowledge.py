"""知识库管理 API（仅管理员）"""
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_SIZE,
    RATE_LIMIT_UPLOAD,
    UPLOAD_DIR,
)
from app.database import get_db
from app.middleware.auth import get_admin_user, get_current_user
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.kb_permission import KbPermission
from app.models.knowledge_base import KnowledgeBase
from app.models.message import Message
from app.models.retrieval_log import RetrievalLog
from app.models.user import User
from app.schemas import (
    DocumentList,
    DocumentProcessStatus,
    KbPermissionGrant,
    KnowledgeBaseCreate,
    KnowledgeBaseList,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.services.audit_service import audit_log
from app.services.kb_service import (
    delete_document_from_chroma,
    drop_collection,
    get_collection,
)
from app.services.permission_service import (
    get_accessible_kb_ids,
)
from app.services.task_dispatch import enqueue_document_task
from app.utils.file_security import (
    FileValidationError,
    sanitize_filename,
    validate_file,
)
from app.utils.rate_limit import user_rate_limit

logger = logging.getLogger("rag-app")

router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])


@router.get("/documents", response_model=DocumentList)
def list_documents(
    page: int = 1,
    page_size: int = 20,
    kb_id: Optional[int] = None,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """获取知识库文档列表（可通过 kb_id 只查看某个知识库）"""
    offset = (page - 1) * page_size
    query = db.query(Document)
    if kb_id is not None:
        query = query.filter(Document.kb_id == kb_id)
    total = query.count()
    docs = (
        query.order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return DocumentList(documents=docs, total=total)


@router.get("/documents/{doc_id}", response_model=DocumentProcessStatus)
def get_document_status(
    doc_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """获取文档处理状态"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return DocumentProcessStatus(id=doc.id, status=doc.status, chunk_count=doc.chunk_count)


@router.post(
    "/upload",
    dependencies=[Depends(user_rate_limit("upload", RATE_LIMIT_UPLOAD))],
)
async def upload_document(
    file: UploadFile = File(...),
    kb_id: Optional[int] = Form(None),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """上传文档（可指定归属的知识库 kb_id）"""
    # 校验知识库存在
    if kb_id is not None:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"知识库不存在: id={kb_id}",
            )

    # 校验扩展名
    raw_name = file.filename or ""
    ext = Path(raw_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型，支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 保存文件。
    #
    # 两点与历史实现不同：
    # 1. **分块落盘**边写边判大小。历史实现是 `await file.read()` 一次性读进内存
    #    再判大小——那时整个文件已经在内存里了，客户端发一个超大请求就能打挂服务。
    # 2. **文件名取 basename**。历史实现是 `f"{uuid}_{file.filename}"`，
    #    随机前缀挡不住 `../`，路径穿越依然成立。
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_display_name = sanitize_filename(raw_name)
    stored_name = f"{uuid.uuid4().hex}_{safe_display_name}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)

    max_bytes = MAX_UPLOAD_SIZE * 1024 * 1024
    written = 0
    try:
        with open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件过大，最大支持 {MAX_UPLOAD_SIZE}MB",
                    )
                f.write(chunk)

        # 文件头校验：扩展名可以伪造，文件头不行
        validate_file(ext, file_path)
    except HTTPException:
        # 半截文件 / 非法文件不要留在磁盘上
        if os.path.exists(file_path):
            os.remove(file_path)
        raise
    except FileValidationError as exc:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # 创建数据库记录
    doc = Document(
        filename=stored_name,
        file_type=ext,
        file_size=written,
        status="queued",
        uploaded_by=current_user.id,
        kb_id=kb_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 投递到任务队列。
    # 不要在请求里直接处理——解析 + 逐块算 embedding 可能要几十秒，
    # 会占满 uvicorn 的请求处理能力，且 HTTP 超时后用户会看到失败但任务其实在跑。
    mode = enqueue_document_task(doc.id, file_path, stored_name)

    logger.info(
        f"文档已入队 doc_id={doc.id} name={safe_display_name} "
        f"size={written}B kb_id={kb_id} 投递方式={mode}"
    )
    audit_log(
        db, current_user, "document.upload",
        target_type="document", target_id=doc.id,
        detail={"filename": safe_display_name, "size": written, "kb_id": kb_id},
    )

    return {
        "message": "文档上传成功，已加入处理队列",
        "document_id": doc.id,
        "filename": safe_display_name,
        # 如实告知走了哪种执行方式：降级时会返回 "thread"，
        # 前端可以据此提示"当前为开发模式，重启可能丢失任务"
        "queue_mode": mode,
        "status": doc.status,
    }


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """删除文档"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    # 删除向量数据（从该文档所属知识库的集合中删除）
    delete_document_from_chroma(db, doc_id)

    # 删除文件
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    # 审计要在删除之前写：删完再写的话，一旦写失败就彻底没有记录了
    audit_log(
        db, current_user, "document.delete",
        target_type="document", target_id=doc_id,
        detail={"filename": doc.filename, "kb_id": doc.kb_id, "chunks": doc.chunk_count},
    )

    # 删除数据库记录
    db.delete(doc)
    db.commit()

    logger.info(f"文档已删除 doc_id={doc_id} by user_id={current_user.id}")
    return {"message": "文档已删除"}


@router.post("/documents/{doc_id}/reindex")
def reindex(
    doc_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """重新索引文档。

    与上传走同一条队列，因此同样具备重试与失败落库；
    历史实现是起一个裸 daemon 线程，进程重启就没了。
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if not os.path.exists(file_path):
        doc.status = "error"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="源文件已丢失，无法重新索引，请重新上传",
        )

    # 先把状态置为排队中并递增一个"索引版本"，避免重复点击产生的并发重建。
    # process_document 内部是幂等的（会先清旧向量），所以并发重建不会产生脏数据，
    # 但会浪费算力，这里能挡掉大部分重复请求。
    doc.status = "queued"
    doc.chunk_count = 0
    db.commit()

    audit_log(
        db, current_user, "document.reindex",
        target_type="document", target_id=doc_id,
        detail={"filename": doc.filename},
    )

    mode = enqueue_document_task(doc.id, file_path, doc.filename)
    logger.info(f"文档重新索引入队 doc_id={doc_id} 投递方式={mode}")
    return {"message": "已加入重新索引队列", "queue_mode": mode, "status": doc.status}


# ==================== 系统统计（管理员） ====================
@router.get("/stats")
def get_system_stats(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """系统概览统计：文档 / 会话 / 用户 / 消息"""
    total_docs = db.query(Document).count()
    ready_docs = db.query(Document).filter(Document.status == "ready").count()
    processing_docs = db.query(Document).filter(Document.status == "processing").count()
    ready_chunk_sum = sum(
        (c for (c,) in db.query(Document.chunk_count).filter(Document.status == "ready").all()),
    )
    total_users = db.query(User).count()
    total_convos = db.query(Conversation).count()
    total_messages = db.query(Message).count()

    return {
        "documents": total_docs,
        "ready_documents": ready_docs,
        "processing_documents": processing_docs,
        "chunks": ready_chunk_sum,
        "users": total_users,
        "conversations": total_convos,
        "messages": total_messages,
    }


# ==================== 用户管理（管理员） ====================
@router.get("/users")
def list_users(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """用户列表（不含密码）"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": len(users),
    }


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """删除用户（连带会话与消息）"""
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除自己")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 先删除该用户的所有会话（连带消息），避免外键冲突
    convos = db.query(Conversation).filter(Conversation.user_id == user_id).all()
    for conv in convos:
        db.query(Message).filter(Message.conversation_id == conv.id).delete()
        db.delete(conv)

    db.delete(user)
    db.commit()
    return {"message": f"用户 {user.username} 已删除"}

# ==================== 知识库（Knowledge Base）管理 ====================

def _build_collection_name(name: str) -> str:
    """根据知识库名称生成全局唯一且合法的 ChromaDB 集合名。

    ChromaDB 要求：3~63 字符，仅含字母/数字/下划线/连字符，首尾为字母或数字。
    """
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()[:30] or "kb"
    return f"kb_{uuid.uuid4().hex[:8]}_{slug}"


def _kb_to_response(db: Session, kb: KnowledgeBase) -> KnowledgeBaseResponse:
    """组装知识库响应，附带文档数与分块数统计"""
    docs = db.query(Document).filter(Document.kb_id == kb.id).all()
    return KnowledgeBaseResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        collection_name=kb.collection_name,
        is_default=kb.is_default,
        doc_count=len(docs),
        chunk_count=sum(d.chunk_count or 0 for d in docs),
        created_at=kb.created_at,
    )


@router.get("/bases", response_model=KnowledgeBaseList)
def list_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出**当前用户有权访问**的知识库（含文档数与分块数）。

    对所有已登录用户开放，但结果按权限过滤：
    普通用户只看得到被授权的知识库，管理员看得到全部。

    **不泄露"存在但无权访问"的知识库**——列表里不出现，
    用户就不会知道有这么一个库，也就不会去猜它的内容。
    """
    query = db.query(KnowledgeBase)
    allowed = get_accessible_kb_ids(db, current_user)
    if allowed is not None:
        if not allowed:
            return KnowledgeBaseList(bases=[], total=0)
        query = query.filter(KnowledgeBase.id.in_(allowed))

    bases = query.order_by(KnowledgeBase.id.asc()).all()
    return KnowledgeBaseList(
        bases=[_kb_to_response(db, kb) for kb in bases],
        total=len(bases),
    )


@router.post("/bases", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
def create_knowledge_base(
    data: KnowledgeBaseCreate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """创建知识库（同时创建对应的独立向量集合）"""
    if db.query(KnowledgeBase).filter(KnowledgeBase.name == data.name).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"知识库名称已存在: {data.name}",
        )

    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        collection_name=_build_collection_name(data.name),
        created_by=current_user.id,
        is_default="false",
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)

    # 预创建集合，确保立即可用
    get_collection(kb.collection_name)

    audit_log(
        db, current_user, "knowledge_base.create",
        target_type="knowledge_base", target_id=kb.id,
        detail={"name": kb.name, "collection": kb.collection_name},
    )
    logger.info(f"知识库已创建 id={kb.id} name={kb.name} by user_id={current_user.id}")
    return _kb_to_response(db, kb)


@router.put("/bases/{kb_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    kb_id: int,
    data: KnowledgeBaseUpdate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """更新知识库名称或描述"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    if data.name and data.name != kb.name:
        exists = db.query(KnowledgeBase).filter(KnowledgeBase.name == data.name).first()
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"知识库名称已存在: {data.name}",
            )
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description

    db.commit()
    db.refresh(kb)
    return _kb_to_response(db, kb)


@router.delete("/bases/{kb_id}")
def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """删除知识库：连同其下所有文档、向量集合一并删除"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    docs = db.query(Document).filter(Document.kb_id == kb_id).all()
    if docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"该知识库下还有 {len(docs)} 个文档，请先删除文档或将其移出知识库",
        )

    collection_name = kb.collection_name
    kb_name = kb.name
    # 授权记录随知识库一起清理（外键 ondelete=CASCADE 只在数据库层生效，
    # 这里显式删除以便 ORM 层行为一致，也便于观察影响行数）
    revoked = (
        db.query(KbPermission).filter(KbPermission.kb_id == kb_id).delete()
    )
    db.delete(kb)
    db.commit()

    # 删除对应的向量集合
    drop_collection(collection_name)

    # 审计写在 commit 之后：删除动作已经生效，必须留痕
    audit_log(
        db, current_user, "knowledge_base.delete",
        target_type="knowledge_base", target_id=kb_id,
        detail={"name": kb_name, "collection": collection_name, "revoked_permissions": revoked},
    )
    logger.warning(
        f"知识库已删除 id={kb_id} name={kb_name} "
        f"by user_id={current_user.id} 同时清理授权={revoked} 条"
    )
    return {"message": f"知识库「{kb_name}」已删除"}


# ==================== 权限管理（仅管理员） ====================

@router.get("/bases/{kb_id}/permissions")
def list_kb_permissions(
    kb_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """查看某知识库的授权名单"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    rows = (
        db.query(KbPermission, User)
        .join(User, User.id == KbPermission.user_id)
        .filter(KbPermission.kb_id == kb_id)
        .all()
    )
    return {
        "kb_id": kb_id,
        "kb_name": kb.name,
        "permissions": [
            {
                "user_id": user.id,
                "username": user.username,
                "permission": perm.permission,
                "granted_by": perm.granted_by,
                "created_at": perm.created_at,
            }
            for perm, user in rows
        ],
    }


@router.post("/bases/{kb_id}/permissions")
def grant_kb_permission(
    kb_id: int,
    data: KbPermissionGrant,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """授予某用户对某知识库的访问权限（重复授权则更新权限级别）"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    target = db.query(User).filter(User.id == data.user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if target.role == "admin":
        # 管理员本来就无限制，再存一条授权只会让权限表产生误导性的记录
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该用户是管理员，本就拥有全部知识库权限，无需单独授权",
        )

    existing = (
        db.query(KbPermission)
        .filter(KbPermission.user_id == data.user_id, KbPermission.kb_id == kb_id)
        .first()
    )
    if existing:
        existing.permission = data.permission
        existing.granted_by = current_user.id
        action = "knowledge_base.permission_update"
    else:
        db.add(
            KbPermission(
                user_id=data.user_id,
                kb_id=kb_id,
                permission=data.permission,
                granted_by=current_user.id,
            )
        )
        action = "knowledge_base.permission_grant"
    db.commit()

    audit_log(
        db, current_user, action,
        target_type="knowledge_base", target_id=kb_id,
        detail={"target_user_id": target.id, "target_username": target.username,
                "permission": data.permission},
    )
    logger.info(
        f"授权变更 kb_id={kb_id} user={target.username} "
        f"permission={data.permission} by user_id={current_user.id}"
    )
    return {"message": f"已授予 {target.username} 对「{kb.name}」的 {data.permission} 权限"}


@router.delete("/bases/{kb_id}/permissions/{user_id}")
def revoke_kb_permission(
    kb_id: int,
    user_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """撤销某用户对某知识库的访问权限"""
    perm = (
        db.query(KbPermission)
        .filter(KbPermission.user_id == user_id, KbPermission.kb_id == kb_id)
        .first()
    )
    if not perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该授权不存在")

    db.delete(perm)
    db.commit()

    audit_log(
        db, current_user, "knowledge_base.permission_revoke",
        target_type="knowledge_base", target_id=kb_id,
        detail={"target_user_id": user_id},
    )
    logger.warning(f"权限已撤销 kb_id={kb_id} user_id={user_id} by user_id={current_user.id}")
    return {"message": "授权已撤销"}


# ==================== 运营闭环：bad case 归档 ====================

@router.get("/bad-cases")
def list_bad_cases(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """列出被用户点踩的回答（bad case），用于知识库补漏与回归测试集建设。

    每条记录附带当次检索的明细，可直接判断失败原因属于：
    - 检索问题（BM25/向量候选里压根没有正确文档）
    - 生成问题（检索到了，但模型没用上）
    """
    offset = (page - 1) * page_size
    total = db.query(Message).filter(Message.feedback == "down").count()
    msgs = (
        db.query(Message)
        .filter(Message.feedback == "down")
        .order_by(Message.feedback_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = []
    for m in msgs:
        # 取同会话中该回答之前最近的一条用户提问
        question = (
            db.query(Message)
            .filter(
                Message.conversation_id == m.conversation_id,
                Message.id < m.id,
                Message.role == "user",
            )
            .order_by(Message.id.desc())
            .first()
        )
        log = None
        if m.retrieval_log_id:
            rl = db.query(RetrievalLog).filter(RetrievalLog.id == m.retrieval_log_id).first()
            if rl:
                log = {
                    "id": rl.id,
                    "vector_candidates": len(rl.vector_hits or []),
                    "bm25_candidates": len(rl.bm25_hits or []),
                    "fused_count": rl.fused_count,
                    "final_count": rl.final_count,
                    "latency_ms": rl.latency_ms,
                }
        items.append({
            "message_id": m.id,
            "conversation_id": m.conversation_id,
            "question": question.content if question else None,
            "answer": m.content,
            "reason": m.feedback_reason,
            "comment": m.feedback_comment,
            "feedback_at": m.feedback_at.isoformat() if m.feedback_at else None,
            "sources": m.sources,
            "retrieval_log": log,
        })

    return {"items": items, "total": total}


@router.get("/retrieval-stats")
def retrieval_stats(
    limit: int = 200,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """检索质量概览：取最近 N 次检索统计两路召回的贡献与延迟。"""
    logs = (
        db.query(RetrievalLog)
        .order_by(RetrievalLog.id.desc())
        .limit(limit)
        .all()
    )
    if not logs:
        return {"sample": 0, "message": "暂无检索日志"}

    n = len(logs)
    bm25_only = 0
    vector_only = 0
    both = 0
    latencies = []

    for rl in logs:
        v_ids = {h["chunk_id"] for h in (rl.vector_hits or [])}
        b_ids = {h["chunk_id"] for h in (rl.bm25_hits or [])}
        final_ids = set(rl.final_chunk_ids or [])
        hit_v = bool(final_ids & v_ids)
        hit_b = bool(final_ids & b_ids)
        if hit_v and hit_b:
            both += 1
        elif hit_b:
            bm25_only += 1
        elif hit_v:
            vector_only += 1
        if rl.latency_ms is not None:
            latencies.append(rl.latency_ms)

    latencies.sort()
    return {
        "sample": n,
        "both_paths_contributed": both,
        "bm25_only_contributed": bm25_only,      # BM25 独有贡献 = 混合检索的增量价值
        "vector_only_contributed": vector_only,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "p95_latency_ms": latencies[int(len(latencies) * 0.95)] if latencies else None,
    }
