"""问答 API — 核心对话接口"""
import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import (
    KB_ACL_ENABLED,
    QUERY_REWRITE_ENABLED,
    RATE_LIMIT_CHAT,
    RETRIEVAL_LOG_ENABLED,
    RETRIEVAL_TOP_K,
)
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.conversation import Conversation
from app.models.knowledge_base import KnowledgeBase
from app.models.message import Message
from app.models.retrieval_log import RetrievalLog
from app.models.user import User
from app.services.permission_service import resolve_query_kb_ids
from app.utils.rate_limit import user_rate_limit

logger = logging.getLogger("rag-app")
from app.schemas import (
    ChatRequest,
    ConversationList,
    ConversationResponse,
    FeedbackRequest,
)
from app.services.query_rewrite import rewrite_query
from app.services.rag_service import (
    generate_chat_stream,
    get_conversation_history,
    get_or_create_conversation,
    save_message,
    search_knowledge,
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


@router.post(
    "/send",
    # 问答是最贵的接口（嵌入 + 检索 + LLM 推理），必须限流
    dependencies=[Depends(user_rate_limit("chat", RATE_LIMIT_CHAT))],
)
async def send_message(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送消息并获取流式回答"""
    # 1. 获取或创建会话
    conv = get_or_create_conversation(db, current_user.id, data.conversation_id)

    # **立刻取出普通整数**，后面一律用 conv_id，不再碰 conv 这个 ORM 对象。
    #
    # 原因：下面的回答是流式返回的，`stream()` 真正执行时，请求处理函数
    # 早已返回，依赖注入的收尾逻辑已经把数据库会话关掉了。
    # 会话关闭时 SQLAlchemy 会把所有 ORM 实例"过期 + 脱离"，此时再读
    # `conv.id` 会触发一次重新加载，而对象已经没有会话可用了，直接抛
    # `Instance <Conversation> is not bound to a Session`。
    #
    # 这个坑的隐蔽之处在于：**它取决于中途有没有 commit**。
    # 每次 commit 都会让会话里所有对象过期；只要在流式返回之前
    # 恰好读过一次 `conv.id`，对象就会被顺带刷新，问题不出现。
    # 所以一旦调整了中间代码的顺序（哪怕只是挪动一行取历史），
    # 就可能把原本"碰巧没事"变成必现的报错。
    conv_id = conv.id

    # 2. 取历史（最近 10 轮）—— 必须在保存本条消息**之前**取。
    #    顺序反了的话，当前问题会同时出现在 history 末尾和 generate_chat_stream
    #    的 query 参数里，在 Prompt 中重复出现一次。
    #    而且多轮改写也依赖它：没有历史，「它支持哪些数据库」根本无从消解。
    history = get_conversation_history(db, conv_id, limit=10)

    # 3. 保存用户消息
    save_message(db, conv_id, "user", data.query)

    # 4. 权限收敛 —— **必须在检索之前**
    #    把请求里的 kb_ids 换成"用户真的有权限的那些"。
    #    注意 data.kb_ids 为 None 时表示"全部知识库"，这里会被展开成
    #    "用户可访问的那些"，而不是真的检索全部——否则就是权限绕过。
    permitted_kb_ids = resolve_query_kb_ids(db, current_user, data.kb_ids)

    collection_names = None
    if KB_ACL_ENABLED and not permitted_kb_ids and current_user.role != "admin":
        # 有 ACL 但一个可访问的知识库都没有：直接返回空检索结果，
        # 绝不能因为列表为空就退化成"检索全部"
        collection_names = []  # 空列表 = 检索不到任何东西（与 None 含义不同）
    elif permitted_kb_ids:
        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(permitted_kb_ids)).all()
        collection_names = [kb.collection_name for kb in kbs] or []

    # 5. 检索改写（指代消解）。
    #    只在问题确实依赖上文时才触发，否则白白多等一次 LLM 推理。
    #    改写**只用于检索**：最终回答的仍然是用户原本那句话（连同历史一起交给模型）。
    search_query = data.query
    if QUERY_REWRITE_ENABLED:
        search_query = await asyncio.to_thread(rewrite_query, data.query, history)

    # 向量检索中的 embedding 计算是同步阻塞的 CPU/GPU 操作。
    # 直接在 async 函数里调用会阻塞事件循环，导致并发请求被迫排队，
    # 因此通过 asyncio.to_thread 放到线程池执行。
    context, sources, trace = await asyncio.to_thread(
        search_knowledge, search_query, RETRIEVAL_TOP_K, collection_names
    )
    if trace is not None:
        # 记录下来便于事后核对"这次到底查了哪些库"
        trace["permitted_kb_ids"] = permitted_kb_ids
        trace["original_query"] = data.query

    # 4. 落库检索日志：记录本次检索的双路候选、融合与耗时。
    #    用户点踩时，可据此判断「是没检索到，还是检索到了但模型没用」。
    retrieval_log_id = None
    if RETRIEVAL_LOG_ENABLED and trace:
        try:
            log = RetrievalLog(
                query=data.query,
                # 没改写就不重复存一份，便于用 `rewritten_query IS NOT NULL` 统计改写触发率
                rewritten_query=search_query if search_query != data.query else None,
                user_id=current_user.id,
                conversation_id=conv_id,
                kb_ids=data.kb_ids,
                collection_names=trace.get("collection_names"),
                vector_hits=trace.get("vector_hits"),
                bm25_hits=trace.get("bm25_hits"),
                fused_count=trace.get("fused_count"),
                dedup_removed=trace.get("dedup_removed"),
                rerank=trace.get("rerank"),
                final_count=trace.get("final_count"),
                final_chunk_ids=trace.get("final_chunk_ids"),
                latency_ms=trace.get("latency_ms"),
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            retrieval_log_id = log.id
            logger.info(
                f"检索完成 log_id={log.id} 向量候选={len(trace.get('vector_hits') or [])} "
                f"BM25候选={len(trace.get('bm25_hits') or [])} 融合={trace.get('fused_count')} "
                f"去冗={trace.get('dedup_removed')} 最终={trace.get('final_count')} "
                f"耗时={trace.get('latency_ms')}ms"
            )
        except Exception as e:
            logger.warning(f"写入检索日志失败（不影响问答）: {e}")

    # 6. 流式返回
    async def stream():
        full_answer = ""
        try:
            async for chunk in generate_chat_stream(data.query, context, history):
                full_answer += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            # 保存助手消息（关联本次检索日志，使后续反馈可追溯）
            msg = save_message(
                db, conv_id, "assistant", full_answer, sources, retrieval_log_id
            )

            # 自动生成标题
            update_conversation_title(db, conv_id, data.query)

            # 返回引用来源 + 消息 ID（前端据此提交点赞/点踩反馈）
            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'message_id': msg.id, 'sources': sources}, ensure_ascii=False)}\n\n"

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

# ==================== 用户反馈闭环 ====================

@router.post("/messages/{message_id}/feedback")
def submit_feedback(
    message_id: int,
    data: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交对某条回答的反馈（点赞 / 点踩）。

    没有反馈数据，所有质量优化都是拍脑袋。该接口是「生产问题 → 测试用例 → 防回归」
    正循环的起点：点踩记录会关联当次检索日志，可直接回看「当时检索到了什么」。
    """
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")
    if msg.role != "assistant":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能对助手回答进行反馈")

    # 归属校验：只能对自己会话内的消息反馈
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == msg.conversation_id, Conversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权对该消息反馈")

    msg.feedback = data.feedback
    msg.feedback_reason = data.reason
    msg.feedback_comment = data.comment
    msg.feedback_at = datetime.now()
    db.commit()

    if data.feedback == "down":
        logger.info(
            f"[负反馈] message_id={message_id} reason={data.reason} "
            f"retrieval_log_id={msg.retrieval_log_id} comment={data.comment}"
        )
    return {"message": "反馈已记录", "message_id": message_id, "feedback": data.feedback}
