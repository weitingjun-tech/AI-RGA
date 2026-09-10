"""RAG 问答服务：检索增强生成全流程"""
import asyncio
import json
from typing import AsyncGenerator, Optional

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from sqlalchemy.orm import Session

from app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    RETRIEVAL_TOP_K,
    RELEVANCE_THRESHOLD,
)
from app.services.kb_service import get_embedding_model, get_chroma_collection
from app.models.conversation import Conversation
from app.models.message import Message
from app.utils.cache import query_cache


# ==================== RAG System Prompt 模板 ====================
RAG_SYSTEM_TEMPLATE = """你是一个专业的电商客服助手。你需要根据提供的商品知识库内容来回答用户问题。

请遵守以下规则：
1. 优先使用知识库中的信息回答问题，确保回答准确、详细、有帮助
2. 在回答中引用知识库内容时，用 **[来源: 文档名]** 标注引用来源
3. 如果知识库中没有相关信息，诚实告知用户，不要编造信息
4. 回答要结构清晰，适当使用列表或分段
5. 语气亲切专业，像真正的电商客服一样

知识库参考内容：
{context}"""


def build_rag_messages(query: str, context: str, history: list[dict] | None = None) -> list[tuple[str, str]]:
    """构建 RAG 对话消息列表（system + 可选历史 + 当前问题）"""
    messages = [("system", RAG_SYSTEM_TEMPLATE.format(context=context))]
    for msg in (history or []):
        role = "human" if msg["role"] == "user" else "ai"
        messages.append((role, msg["content"]))
    messages.append(("human", query))
    return messages


def build_context_from_results(results: dict) -> tuple[str, list[dict]]:
    """从检索结果构建上下文文本和来源列表"""
    sources = []
    context_parts = []

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances)):
        score = 1.0 - dist if dist else 1.0
        if score < RELEVANCE_THRESHOLD:
            continue

        doc_name = meta.get("doc_name", "未知文档")
        context_parts.append(f"[{i+1}] (来源: {doc_name})\n{doc}\n")
        sources.append({
            "doc_id": meta.get("doc_id"),
            "doc_name": doc_name,
            "chunk_id": meta.get("chunk_index", i),
            "text_snippet": doc[:300] + ("..." if len(doc) > 300 else ""),
            "score": round(score, 4),
        })

    context = "\n---\n".join(context_parts) if context_parts else "暂无相关知识库内容。"
    return context, sources


def get_llm() -> ChatOllama:
    """获取 Ollama LLM 实例"""
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.3,
        num_predict=1024,
    )


def retrieve(query: str, top_k: int = RETRIEVAL_TOP_K) -> dict:
    """向量检索"""
    embedding_model = get_embedding_model()
    collection = get_chroma_collection()

    query_embedding = embedding_model.embed_query(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    return results


@query_cache
def retrieve_cached(query: str, top_k: int = RETRIEVAL_TOP_K) -> dict:
    """带缓存的向量检索"""
    return retrieve(query, top_k)


def search_knowledge(query: str, top_k: int = RETRIEVAL_TOP_K) -> tuple[str, list[dict]]:
    """检索知识库并构建上下文"""
    results = retrieve_cached(query, top_k)
    return build_context_from_results(results)


async def generate_answer_stream(
    query: str,
    context: str,
) -> AsyncGenerator[str, None]:
    """流式生成回答（单轮，无历史）"""
    llm = get_llm()
    chain = ChatPromptTemplate.from_messages(build_rag_messages(query, context)) | llm | StrOutputParser()

    async for chunk in chain.astream({}):
        yield chunk


async def generate_chat_stream(
    query: str,
    context: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    """带历史的多轮对话流式生成"""
    llm = get_llm()
    chain = ChatPromptTemplate.from_messages(build_rag_messages(query, context, history)) | llm | StrOutputParser()

    async for chunk in chain.astream({}):
        yield chunk


def save_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    sources: Optional[list[dict]] = None,
) -> Message:
    """保存消息到数据库"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        sources=sources,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_or_create_conversation(db: Session, user_id: int, conversation_id: Optional[int] = None) -> Conversation:
    """获取或创建会话"""
    if conversation_id:
        conv = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        ).first()
        if conv:
            return conv

    conv = Conversation(user_id=user_id, title="新会话")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversation_history(db: Session, conversation_id: int, limit: int = 10) -> list[dict]:
    """获取会话历史消息（最近 N 轮），返回简化格式"""
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit * 2)
        .all()
    )
    messages.reverse()
    return [{"role": m.role, "content": m.content} for m in messages]


def update_conversation_title(db: Session, conversation_id: int, first_query: str):
    """用第一条问题自动生成会话标题"""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv and conv.title == "新会话":
        title = first_query[:30] + ("..." if len(first_query) > 30 else "")
        conv.title = title
        db.commit()