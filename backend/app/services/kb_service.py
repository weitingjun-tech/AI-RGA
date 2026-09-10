"""知识库管理服务：文档解析、分块、向量化、入库"""
import os
# 把 HuggingFace 缓存目录设到 D 盘，否则 C 盘会满
os.environ.setdefault("HF_HOME", "D:/mydo/huggingface_cache")
# 强制离线模式 —— 模型已在本地缓存，不需要联网下载
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    CSVLoader,
    Docx2txtLoader,
)
from langchain_core.documents import Document as LCDocument
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
import chromadb
from chromadb.config import Settings as ChromaSettings
from sqlalchemy.orm import Session

from app.config import (
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_MODEL,
    EMBEDDING_DEVICE,
    UPLOAD_DIR,
)
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase


# ==================== Embedding 模型（单例懒加载） ====================
_embedding_model: Optional[HuggingFaceBgeEmbeddings] = None


def get_embedding_model() -> HuggingFaceBgeEmbeddings:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = HuggingFaceBgeEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={
                "device": EMBEDDING_DEVICE,
            },
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedding_model


# ==================== ChromaDB 客户端（单例懒加载） ====================
_chroma_client: Optional[chromadb.PersistentClient] = None
# 集合缓存：一个知识库对应一个集合，按名称缓存避免重复获取
_collections: dict[str, chromadb.Collection] = {}


def get_chroma_client() -> chromadb.PersistentClient:
    """获取全局唯一的 ChromaDB 持久化客户端"""
    global _chroma_client
    if _chroma_client is None:
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_collection(collection_name: str) -> chromadb.Collection:
    """按名称获取（或创建）向量集合。

    多知识库隔离的核心：每个知识库拥有独立的 collection，
    检索时只查询目标知识库，从根本上避免跨库语料污染。
    """
    if collection_name not in _collections:
        _collections[collection_name] = get_chroma_client().get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[collection_name]


def get_chroma_collection() -> chromadb.Collection:
    """兼容旧调用：返回默认知识库对应的集合"""
    return get_collection(CHROMA_COLLECTION_NAME)


def drop_collection(collection_name: str) -> None:
    """删除整个集合（删除知识库时调用）"""
    try:
        get_chroma_client().delete_collection(collection_name)
    except Exception:
        pass
    _collections.pop(collection_name, None)


# ==================== EPUB/MOBI 文本提取 ====================
def _epub_to_documents(epub_path: str) -> List[LCDocument]:
    """用 ebooklib 读取 epub，将每个 HTML 章节转为纯文本，每章一个 Document。"""
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    documents: List[LCDocument] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", errors="ignore")
        text = BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
        # 合并多余空行
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if text:
            documents.append(LCDocument(page_content=text, metadata={"source": item.get_name()}))
    return documents


class EpubLoader:
    """LangChain 风格的 EPUB 加载器：直接基于 ebooklib，无需 unstructured 依赖。"""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def load(self) -> List[LCDocument]:
        return _epub_to_documents(self.file_path)


class MobiLoader:
    """MOBI 加载器：先用 mobi 包转成 epub/html，再提取文本。"""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def load(self) -> List[LCDocument]:
        from mobi import extract as mobi_extract
        tempdir, extracted = mobi_extract(self.file_path)
        try:
            ext = Path(extracted).suffix.lower()
            if ext == ".epub":
                return _epub_to_documents(extracted)
            # mobi 退化为 html 的情况
            with open(extracted, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
            text = BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            return [LCDocument(page_content=text, metadata={"source": extracted})] if text else []
        finally:
            shutil.rmtree(tempdir, ignore_errors=True)


# ==================== 文档加载器映射 ====================
LOADER_MAP = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
    ".csv": CSVLoader,
    ".docx": Docx2txtLoader,
    ".epub": EpubLoader,
    ".mobi": MobiLoader,
}


def get_file_hash(file_path: str) -> str:
    """计算文件 MD5，用于去重"""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    """获取中文优化的文本分块器"""
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        length_function=len,
    )


def resolve_collection_name(db: Session, kb_id: Optional[int]) -> str:
    """根据知识库 ID 解析对应的 ChromaDB 集合名；未指定时回退到默认集合"""
    if kb_id is None:
        return CHROMA_COLLECTION_NAME
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    return kb.collection_name if kb else CHROMA_COLLECTION_NAME


def process_document(db: Session, doc_id: int, file_path: str, filename: str) -> None:
    """处理上传的文档：解析 → 分块 → 向量化 → 存入 ChromaDB"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return

    try:
        # 1. 选择加载器
        ext = Path(filename).suffix.lower()
        loader_cls = LOADER_MAP.get(ext)
        if not loader_cls:
            doc.status = "error"
            db.commit()
            return

        # 2. 加载文档（文本类文件统一使用 UTF-8 编码，避免 Windows GBK 问题）
        if ext in (".csv", ".txt", ".md"):
            loader = loader_cls(file_path, encoding="utf-8")
        else:
            loader = loader_cls(file_path)
        docs = loader.load()

        if not docs:
            doc.status = "error"
            db.commit()
            return

        # 3. 分块
        splitter = get_text_splitter()
        chunks = splitter.split_documents(docs)

        # 4. 向量化 + 入库（写入该文档所属知识库对应的独立集合）
        embedding_model = get_embedding_model()
        collection = get_collection(resolve_collection_name(db, doc.kb_id))

        texts = [chunk.page_content for chunk in chunks]
        ids = [f"doc_{doc_id}_chunk_{i}" for i in range(len(texts))]
        metadatas = [
            {
                "doc_id": doc_id,
                "doc_name": filename,
                "chunk_index": i,
                "source": chunks[i].metadata.get("source", filename),
            }
            for i in range(len(texts))
        ]

        # 批量嵌入并存入
        embeddings = embedding_model.embed_documents(texts)
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        # 5. 更新数据库状态
        doc.status = "ready"
        doc.chunk_count = len(chunks)
        db.commit()

    except Exception as e:
        doc.status = "error"
        db.commit()
        raise e


def delete_document_from_chroma(db: Session, doc_id: int) -> None:
    """从文档所属知识库的集合中删除该文档的所有分块"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    collection = get_collection(resolve_collection_name(db, doc.kb_id if doc else None))
    try:
        # 按 metadata 过滤删除
        results = collection.get(where={"doc_id": doc_id})
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        # ChromaDB 0.5 删除方式可能有差异，尝试 ID 前缀删除
        try:
            # 获取所有以 doc_{id}_ 开头的 chunk
            all_data = collection.get()
            ids_to_delete = [i for i in all_data["ids"] if i.startswith(f"doc_{doc_id}_")]
            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
        except Exception:
            pass


def reindex_document(db: Session, doc_id: int) -> None:
    """重新索引文档"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return

    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if not os.path.exists(file_path):
        doc.status = "error"
        db.commit()
        return

    # 先删旧向量
    delete_document_from_chroma(db, doc_id)
    doc.chunk_count = 0
    doc.status = "processing"
    db.commit()

    # 重新处理
    process_document(db, doc_id, file_path, doc.filename)