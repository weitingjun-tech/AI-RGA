"""问答 API — 核心对话接口"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.knowledge_base import KnowledgeBase
from app.schemas import (
    ChatRequest,
    ConversationResponse,
    ConversationList,
)
from app.services.rag_service import (
    search_knowledge,
    generate_answer_stream,
    generate_chat_stream,
    save_message,
    get_or_create_conversation,
    get_conversation_history,
    update_conversation_title,
)

router = APIRouter(prefix="/api/chat", tags=["问答"])


@router.get("/conversations", response_model=ConversationList)
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的会话列表"""
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return ConversationList(conversations=conversations, total=len(conversations))


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建会话"""
    conv = Conversation(user_id=current_user.id, title="新会话")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}")
def delete_conversation(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除会话"""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    db.delete(conv)
    db.commit()
    return {"message": "会话已删除"}


@router.put("/conversations/{conv_id}")
def rename_conversation(
    conv_id: int,
    title: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重命名会话"""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    conv.title = title[:200]
    db.commit()
    return {"message": "会话已重命名"}


@router.get("/conversations/{conv_id}/messages")
def get_messages(
    conv_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取会话消息（分页）"""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conv_id, Conversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")

    total = db.query(Message).filter(Message.conversation_id == conv_id).count()
    offset = (page - 1) * page_size
    # 按 id 倒序取「最新的一页」，再翻转为时间正序展示
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv_id)
        .order_by(Message.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    messages.reverse()  # 转为正序展示
    return {"messages": messages, "total": total}


@router.post("/send")
async def send_message(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送消息并获取流式回答"""
    # 1. 获取或创建会话
    conv = get_or_create_conversation(db, current_user.id, data.conversation_id)

    # 2. 保存用户消息
    save_message(db, conv.id, "user", data.query)

    # 3. 检索知识库（可限定到指定知识库，实现多知识库隔离）
    collection_names = None
    if data.kb_ids:
        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(data.kb_ids)).all()
        collection_names = [kb.collection_name for kb in kbs] or None
    context, sources = search_knowledge(data.query, collection_names=collection_names)

    # 4. 获取历史（最近 10 轮对话）
    history = get_conversation_history(db, conv.id, limit=10)

    # 5. 流式返回
    async def stream():
        full_answer = ""
        try:
            async for chunk in generate_chat_stream(data.query, context, history):
                full_answer += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            # 保存助手消息
            save_message(db, conv.id, "assistant", full_answer, sources)

            # 自动生成标题
            update_conversation_title(db, conv.id, data.query)

            # 返回引用来源
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv.id, 'sources': sources}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )