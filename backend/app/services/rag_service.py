"""RAG 问答服务：检索增强生成全流程"""
import asyncio
import json
from typing import AsyncGenerator, Optional

from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from sqlalchemy.orm import Session

from app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    RETRIEVAL_TOP_K,
    RELEVANCE_THRESHOLD,
    RAG_SYSTEM_PROMPT,
)
from app.services.kb_service import (
    get_embedding_model,
    get_chroma_collection,
    get_collection,
    get_chroma_client,
)
from app.models.conversation import Conversation
from app.models.message import Message
from app.utils.cache import query_cache


# ==================== RAG System Prompt ====================
# 模板定义在 app/config.py，可通过环境变量 RAG_SYSTEM_PROMPT 覆盖，以适配不同业务场景
RAG_SYSTEM_TEMPLATE = RAG_SYSTEM_PROMPT


def build_rag_messages(query: str, context: str, history: list[dict] | None = None) -> list:
    """构建 RAG 对话消息列表（system + 可选历史 + 当前问题）。

    注意：这里直接构造 Message 对象，**不经过 ChatPromptTemplate**。
    原因：知识库原文中可能含有 {xxx} 形式的花括号（例如 API 文档里的 JSON 示例
    {"task_id": "..."}）。若把拼好的文本再交给 ChatPromptTemplate 解析，
    花括号会被误判为模板变量并抛出 INVALID_PROMPT_INPUT，导致检索到此类文档时
    整个问答直接失败。直接构造消息对象可以从根本上避免二次模板解析。
    """
    messages: list = [SystemMessage(content=RAG_SYSTEM_TEMPLATE.format(context=context))]
    for msg in (history or []):
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=query))
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


def list_collection_names() -> list[str]:
    """列出 ChromaDB 中所有向量集合的名称（即全部知识库）"""
    try:
        return [c.name for c in get_chroma_client().list_collections()]
    except Exception:
        return []


def retrieve(
    query: str,
    top_k: int = RETRIEVAL_TOP_K,
    collection_names: Optional[list[str]] = None,
) -> dict:
    """向量检索。

    Args:
        collection_names: 要检索的知识库集合名列表。
            - 传入具体集合名 → 只在该知识库内检索（实现知识库隔离）
            - 传 None 或空列表 → 检索全部知识库，跨库结果按相似度合并排序
    """
    embedding_model = get_embedding_model()
    query_embedding = embedding_model.embed_query(query)

    names = collection_names or list_collection_names()

    merged_docs: list = []
    merged_metas: list = []
    merged_dists: list = []

    for name in names:
        try:
            col = get_collection(name)
            if col.count() == 0:
                continue
            res = col.query(query_embeddings=[query_embedding], n_results=top_k)
        except Exception:
            # 某个集合不可用不应影响整体检索
            continue
        merged_docs.extend(res.get("documents", [[]])[0])
        merged_metas.extend(res.get("metadatas", [[]])[0])
        merged_dists.extend(res.get("distances", [[]])[0])

    # 跨库结果按距离升序合并（距离越小越相似），截断到 top_k
    order = sorted(range(len(merged_dists)), key=lambda i: merged_dists[i])[:top_k]

    return {
        "documents": [[merged_docs[i] for i in order]],
        "metadatas": [[merged_metas[i] for i in order]],
        "distances": [[merged_dists[i] for i in order]],
    }


@query_cache
def retrieve_cached(
    query: str,
    top_k: int = RETRIEVAL_TOP_K,
    collections: Optional[tuple] = None,
) -> dict:
    """带缓存的向量检索（collections 用元组以保证可哈希）"""
    return retrieve(query, top_k, list(collections) if collections else None)


def search_knowledge(
    query: str,
    top_k: int = RETRIEVAL_TOP_K,
    collection_names: Optional[list[str]] = None,
) -> tuple[str, list[dict]]:
    """检索知识库并构建上下文（可指定知识库范围）"""
    results = retrieve_cached(query, top_k, tuple(collection_names) if collection_names else None)
    return build_context_from_results(results)


async def generate_answer_stream(
    query: str,
    context: str,
) -> AsyncGenerator[str, None]:
    """流式生成回答（单轮，无历史）"""
    llm = get_llm()
    messages = build_rag_messages(query, context)
    chain = llm | StrOutputParser()

    async for chunk in chain.astream(messages):
        yield chunk


async def generate_chat_stream(
    query: str,
    context: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    """带历史的多轮对话流式生成"""
    llm = get_llm()
    messages = build_rag_messages(query, context, history)
    chain = llm | StrOutputParser()

    async for chunk in chain.astream(messages):
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