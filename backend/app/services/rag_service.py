"""RAG 问答服务：检索增强生成全流程"""
import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator, Optional

from rank_bm25 import BM25Okapi

logger = logging.getLogger("rag-app")

# BM25 索引缓存（按集合名）。BM25 需要全量语料算 IDF，故缓存复用；
# 语料发生变更时必须通过 clear_bm25_cache() 失效，否则会检索到已删除内容。
_bm25_cache: dict[str, Optional[dict]] = {}

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
    HYBRID_SEARCH_ENABLED,
    HYBRID_CANDIDATE_K,
    RRF_K,
    DEDUP_ENABLED,
    DEDUP_JACCARD_THRESHOLD,
)
from app.utils.cache import register_invalidation_hook
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


_TOKEN_RE = re.compile(r"[a-z0-9_.\-]+|[一-鿿]+")
_CJK_RE = re.compile(r"[一-鿿]")


def _is_cjk(s: str) -> bool:
    return bool(_CJK_RE.match(s[0]))


def tokenize(text: str) -> list[str]:
    """面向中英混排的轻量分词，供 BM25 使用。

    - 英文、数字、型号、错误码整体保留（如 conn_timeout / 2.4.0 / task_7f3c91a2）
      这是混合检索补足向量短板的关键：向量对错误码、型号几乎无感，而它们会被完整保留。

    - 中文采用**二元组（bigram）**而非单字：
      单字切分会让「的 / 了 / 是」这类高频字到处命中，BM25 分数被噪声淹没，
      实测反而拉低了整体召回（Hit@5 下降 3.3 个百分点）。
      二元组保留词序信息、区分度显著更高，是无外部分词库时的最佳折中。
    """
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer((text or "").lower()):
        s = m.group()
        if not _is_cjk(s):
            tokens.append(s)
            continue
        if len(s) == 1:
            tokens.append(s)
        else:
            tokens.extend(s[i:i + 2] for i in range(len(s) - 1))
    return tokens


def clear_bm25_cache() -> None:
    """清空 BM25 索引缓存（语料变更时必须调用）"""
    _bm25_cache.clear()


# 语料变更时，检索结果缓存与 BM25 索引必须同时失效
register_invalidation_hook(clear_bm25_cache)


def _get_bm25_index(collection_name: str) -> Optional[dict]:
    """获取（并缓存）某个集合的 BM25 索引。

    BM25 需要全量语料才能计算 IDF，因此按集合缓存，随语料变更失效。
    """
    if collection_name in _bm25_cache:
        return _bm25_cache[collection_name]

    try:
        col = get_collection(collection_name)
        data = col.get(include=["documents", "metadatas"])
    except Exception:
        return None

    ids = data.get("ids") or []
    if not ids:
        _bm25_cache[collection_name] = None
        return None

    corpus = [tokenize(d) for d in (data.get("documents") or [])]
    index = {
        "bm25": BM25Okapi(corpus),
        "ids": ids,
        "documents": data.get("documents") or [],
        "metadatas": data.get("metadatas") or [],
    }
    _bm25_cache[collection_name] = index
    return index


def _rrf_fuse(rank_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """倒数排序融合（Reciprocal Rank Fusion）。

    只依赖「排名」而非「分数」，因此可以直接融合量纲完全不同的
    向量相似度与 BM25 分值，无需调权重，是业界最常用的融合方式。
    """
    scores: dict[str, float] = {}
    for ranks in rank_lists:
        for rank, cid in enumerate(ranks):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _dedup_candidates(cands: list[dict], threshold: float) -> tuple[list[dict], int]:
    """移除与已选片段高度重复的候选（Jaccard 词集合相似度）。

    重复内容（如多版本文档、相邻重叠分块）会挤占 Top-K 名额，
    让真正有信息量的片段进不了上下文。
    """
    kept: list[dict] = []
    kept_token_sets: list[set] = []
    removed = 0

    for c in cands:
        tokens = set(c["tokens"])
        if not tokens:
            kept.append(c)
            continue
        dup = False
        for ks in kept_token_sets:
            if not ks:
                continue
            inter = len(tokens & ks)
            union = len(tokens | ks)
            if union and inter / union >= threshold:
                dup = True
                break
        if dup:
            removed += 1
            continue
        kept.append(c)
        kept_token_sets.append(tokens)

    return kept, removed


def _search_one_collection(col, name: str, query: str, query_embedding, candidate_k: int) -> dict:
    """在单个集合内执行「向量 + BM25」双路召回并融合，返回候选列表。"""
    result = {"vector_hits": [], "bm25_hits": [], "fused": [], "dedup_removed": 0}

    # ---------- 路径 A：向量检索（语义泛化能力强） ----------
    vec_by_id: dict[str, dict] = {}
    try:
        if col.count() > 0:
            res = col.query(query_embeddings=[query_embedding], n_results=candidate_k)
            v_ids = res.get("ids", [[]])[0]
            v_docs = res.get("documents", [[]])[0]
            v_metas = res.get("metadatas", [[]])[0]
            v_dists = res.get("distances", [[]])[0]
            for i, cid in enumerate(v_ids):
                sim = 1.0 - (v_dists[i] if v_dists[i] is not None else 1.0)
                vec_by_id[cid] = {
                    "chunk_id": cid,
                    "text": v_docs[i],
                    "meta": v_metas[i],
                    "similarity": sim,
                    "collection": name,
                }
            result["vector_hits"] = [
                {"chunk_id": cid, "rank": r, "similarity": round(vec_by_id[cid]["similarity"], 4)}
                for r, cid in enumerate(v_ids)
            ]
    except Exception as e:
        logger.warning(f"集合 {name} 向量检索失败: {e}")

    # ---------- 路径 B：BM25 检索（精确匹配能力强，专治型号/错误码） ----------
    bm25_ranked: list[str] = []
    if HYBRID_SEARCH_ENABLED:
        idx = _get_bm25_index(name)
        if idx and idx.get("bm25"):
            try:
                scores = idx["bm25"].get_scores(tokenize(query))
                ranked = sorted(range(len(scores)), key=lambda i: -scores[i])
                hits = []
                for pos in ranked[:candidate_k]:
                    if scores[pos] <= 0:
                        continue
                    hits.append({
                        "chunk_id": idx["ids"][pos],
                        "rank": len(hits),
                        "score": round(float(scores[pos]), 4),
                    })
                bm25_ranked = [h["chunk_id"] for h in hits]
                result["bm25_hits"] = hits
            except Exception as e:
                logger.warning(f"集合 {name} BM25 检索失败: {e}")

    # ---------- 融合 ----------
    rank_lists = [[h["chunk_id"] for h in result["vector_hits"]]]
    if bm25_ranked:
        rank_lists.append(bm25_ranked)
    fused_scores = _rrf_fuse(rank_lists)

    if not fused_scores:
        return result

    # 为 BM25 独有（向量未召回）的候选补齐文本与相似度
    missing = [cid for cid in fused_scores if cid not in vec_by_id]
    if missing:
        try:
            got = col.get(ids=missing, include=["documents", "metadatas", "embeddings"])
            emb = got.get("embeddings")
            docs = got.get("documents") or []
            metas = got.get("metadatas") or []
            for i, cid in enumerate(got.get("ids") or []):
                sim = 0.0
                if emb is not None and len(emb) > i:
                    # 向量已做归一化，点积即余弦相似度
                    sim = float(sum(a * b for a, b in zip(query_embedding, emb[i])))
                vec_by_id[cid] = {
                    "chunk_id": cid,
                    "text": docs[i] if i < len(docs) else "",
                    "meta": metas[i] if i < len(metas) else {},
                    "similarity": sim,
                    "collection": name,
                }
        except Exception as e:
            logger.warning(f"集合 {name} 补齐 BM25 候选失败: {e}")

    cands = []
    for cid, rrf in fused_scores.items():
        base = vec_by_id.get(cid)
        if not base:
            continue
        cands.append({
            **base,
            "rrf": rrf,
            "tokens": tokenize(base["text"]),
        })
    cands.sort(key=lambda x: -x["rrf"])

    if DEDUP_ENABLED:
        cands, removed = _dedup_candidates(cands, DEDUP_JACCARD_THRESHOLD)
        result["dedup_removed"] = removed

    result["fused"] = cands
    return result


def retrieve(
    query: str,
    top_k: int = RETRIEVAL_TOP_K,
    collection_names: Optional[list[str]] = None,
) -> dict:
    """混合检索：向量（语义）+ BM25（精确）双路召回，RRF 融合后去冗、截断。

    Args:
        collection_names: 要检索的知识库集合名列表。
            - 传入具体集合名 → 只在该知识库内检索（知识库隔离）
            - 传 None 或空列表 → 检索全部知识库

    返回结果中的 "trace" 键记录了本次检索的完整明细
    （两路召回候选、融合数量、去冗数量、耗时），供落库与问题归因。
    """
    t0 = time.time()
    embedding_model = get_embedding_model()
    query_embedding = embedding_model.embed_query(query)

    names = collection_names or list_collection_names()

    all_cands: list[dict] = []
    vector_hits_all: list[dict] = []
    bm25_hits_all: list[dict] = []
    dedup_removed_total = 0

    for name in names:
        try:
            col = get_collection(name)
        except Exception:
            continue
        try:
            r = _search_one_collection(col, name, query, query_embedding, HYBRID_CANDIDATE_K)
        except Exception as e:
            # 某个集合不可用不应影响整体检索
            logger.warning(f"集合 {name} 检索异常，已跳过: {e}")
            continue
        all_cands.extend(r["fused"])
        vector_hits_all.extend(r["vector_hits"])
        bm25_hits_all.extend(r["bm25_hits"])
        dedup_removed_total += r["dedup_removed"]

    # 跨库按 RRF 分数合并
    all_cands.sort(key=lambda x: -x["rrf"])

    # 跨库去冗余（同一文档可能被多个库召回）
    if DEDUP_ENABLED and len(names) > 1:
        all_cands, removed = _dedup_candidates(all_cands, DEDUP_JACCARD_THRESHOLD)
        dedup_removed_total += removed

    selected = all_cands[:top_k]

    trace = {
        "query": query,
        "collection_names": names,
        "vector_hits": vector_hits_all[:20],
        "bm25_hits": bm25_hits_all[:20],
        "fused_count": len(all_cands),
        "dedup_removed": dedup_removed_total,
        "final_count": len(selected),
        "final_chunk_ids": [c["chunk_id"] for c in selected],
        "latency_ms": int((time.time() - t0) * 1000),
    }

    # 保持既有调用方约定：distances = 1 - 余弦相似度
    return {
        "documents": [[c["text"] for c in selected]],
        "metadatas": [[c["meta"] for c in selected]],
        "distances": [[1.0 - c["similarity"] for c in selected]],
        "chunk_ids": [[c["chunk_id"] for c in selected]],
        "trace": trace,
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
) -> tuple[str, list[dict], dict]:
    """检索知识库并构建上下文（可指定知识库范围）。

    Returns:
        (拼接好的上下文文本, 引用来源列表, 检索过程明细 trace)
    """
    results = retrieve_cached(query, top_k, tuple(collection_names) if collection_names else None)
    context, sources = build_context_from_results(results)
    return context, sources, results.get("trace", {})


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
    retrieval_log_id: Optional[int] = None,
) -> Message:
    """保存消息到数据库（助手消息会关联当次检索日志，便于反馈归因）"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        sources=sources,
        retrieval_log_id=retrieval_log_id,
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