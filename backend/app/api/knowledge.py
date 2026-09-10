"""知识库管理 API（仅管理员）"""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.middleware.auth import get_admin_user, get_current_user
from app.models.user import User
from app.models.document import Document
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas import DocumentResponse, DocumentList, DocumentProcessStatus
from app.services.kb_service import process_document, delete_document_from_chroma, reindex_document
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS

import logging
logger = logging.getLogger("rag-app")

router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])


@router.get("/documents", response_model=DocumentList)
def list_documents(
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """获取知识库文档列表"""
    offset = (page - 1) * page_size
    total = db.query(Document).count()
    docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
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


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """上传文档"""
    # 校验扩展名
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型，支持: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # 校验大小
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件过大，最大支持 {MAX_UPLOAD_SIZE}MB",
        )

    # 保存文件
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # 防止文件名冲突
    safe_filename = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    with open(file_path, "wb") as f:
        f.write(contents)

    # 创建数据库记录
    doc = Document(
        filename=safe_filename,
        file_type=ext,
        file_size=len(contents),
        status="processing",
        uploaded_by=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 异步处理文档（后台线程）
    # 注意：不要在子线程里复用请求级 db session —— session 关闭后子线程操作会报
    # "Packet sequence number wrong"，且 SQLAlchemy session 不是线程安全的。
    import threading

    def _process_in_thread(doc_id: int, file_path: str, file_name: str):
        thread_db = SessionLocal()
        try:
            process_document(thread_db, doc_id, file_path, file_name)
        except Exception as exc:
            logger.error(f"文档处理失败 doc_id={doc_id}: {exc}", exc_info=True)
        finally:
            thread_db.close()

    thread = threading.Thread(
        target=_process_in_thread,
        args=(doc.id, file_path, file.filename),
        daemon=True,
    )
    thread.start()

    return {"message": "文档上传成功，正在处理中", "document_id": doc.id, "filename": file.filename}


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

    # 删除向量数据
    delete_document_from_chroma(doc_id)

    # 删除文件
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    # 删除数据库记录
    db.delete(doc)
    db.commit()

    return {"message": "文档已删除"}


@router.post("/documents/{doc_id}/reindex")
def reindex(
    doc_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """重新索引文档"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")

    import threading

    def _reindex_in_thread(doc_id: int):
        thread_db = SessionLocal()
        try:
            reindex_document(thread_db, doc_id)
        except Exception as exc:
            logger.error(f"重新索引失败 doc_id={doc_id}: {exc}", exc_info=True)
        finally:
            thread_db.close()

    thread = threading.Thread(target=_reindex_in_thread, args=(doc_id,), daemon=True)
    thread.start()

    return {"message": "正在重新索引"}


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