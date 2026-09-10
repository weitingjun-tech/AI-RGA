"""知识库管理 API（仅管理员）"""
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.middleware.auth import get_admin_user, get_current_user
from app.models.user import User
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.retrieval_log import RetrievalLog
from app.schemas import (
    DocumentResponse,
    DocumentList,
    DocumentProcessStatus,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseList,
)
from app.services.kb_service import (
    process_document,
    delete_document_from_chroma,
    reindex_document,
    drop_collection,
    get_collection,
)
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS, CHROMA_COLLECTION_NAME

import logging
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


@router.post("/upload")
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
        kb_id=kb_id,
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

    # 删除向量数据（从该文档所属知识库的集合中删除）
    delete_document_from_chroma(db, doc_id)

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
    """列出全部知识库（含文档数与分块数）。

    对所有已登录用户开放：问答时需要知道有哪些知识库可选。
    创建/修改/删除仍限管理员。
    """
    bases = db.query(KnowledgeBase).order_by(KnowledgeBase.id.asc()).all()
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
    db.delete(kb)
    db.commit()

    # 删除对应的向量集合
    drop_collection(collection_name)

    return {"message": f"知识库「{kb.name}」已删除"}


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
