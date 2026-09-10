"""
RAG 企业级知识库问答系统 - FastAPI 入口
"""
import os
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import engine, Base, SessionLocal
from app.config import CORS_ORIGINS, UPLOAD_DIR, CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME
from app.services.auth_service import seed_admin
# 导入全部模型，确保 create_all 能建出所有表（含多知识库相关的 knowledge_bases）
import app.models  # noqa: F401

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rag-app")

# 创建数据库表
Base.metadata.create_all(bind=engine)


def _migrate_add_kb_id():
    """轻量迁移：为已存在的 documents 表补充 kb_id 列（多知识库隔离所需）。

    Base.metadata.create_all 只建新表，不会修改已存在的表结构，因此此处显式检查。
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("documents")}
    if "kb_id" in columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN kb_id INT NULL"))
        try:
            conn.execute(text("CREATE INDEX ix_documents_kb_id ON documents (kb_id)"))
        except Exception:
            pass  # 索引可能已存在
    logger.info("已为 documents 表补充 kb_id 列")


def _migrate_add_feedback_columns():
    """轻量迁移：为已存在的 messages 表补充用户反馈相关列。

    与 kb_id 同理，create_all 不会修改既有表结构。
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("messages")}

    additions = {
        "feedback": "ALTER TABLE messages ADD COLUMN feedback ENUM('up','down') NULL",
        "feedback_reason": "ALTER TABLE messages ADD COLUMN feedback_reason VARCHAR(64) NULL",
        "feedback_comment": "ALTER TABLE messages ADD COLUMN feedback_comment TEXT NULL",
        "feedback_at": "ALTER TABLE messages ADD COLUMN feedback_at DATETIME NULL",
        "retrieval_log_id": "ALTER TABLE messages ADD COLUMN retrieval_log_id INT NULL",
    }
    with engine.begin() as conn:
        for col, ddl in additions.items():
            if col in columns:
                continue
            conn.execute(text(ddl))
            logger.info(f"已为 messages 表补充列: {col}")


def _seed_default_kb(db):
    """确保至少存在一个默认知识库，并把历史遗留（kb_id 为空）的文档归入其中。"""
    from app.models.knowledge_base import KnowledgeBase
    from app.models.document import Document

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.is_default == "true").first()
    if not kb:
        kb = db.query(KnowledgeBase).order_by(KnowledgeBase.id.asc()).first()
    if not kb:
        kb = KnowledgeBase(
            name="默认知识库",
            description="系统初始化时自动创建，用于承载未指定归属的文档",
            collection_name=CHROMA_COLLECTION_NAME,
            is_default="true",
        )
        db.add(kb)
        db.commit()
        db.refresh(kb)
        logger.info(f"已创建默认知识库: {kb.name} (collection={kb.collection_name})")

    # 历史文档（无 kb 归属）归入默认知识库
    orphan = db.query(Document).filter(Document.kb_id.is_(None)).all()
    if orphan:
        for d in orphan:
            d.kb_id = kb.id
        db.commit()
        logger.info(f"已将 {len(orphan)} 个历史文档归入默认知识库")


_migrate_add_kb_id()
_migrate_add_feedback_columns()

# 确保目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)

# 预置管理员账号 + 默认知识库
db = SessionLocal()
try:
    seed_admin(db)
    logger.info("管理员账号已就绪: admin / 123456")
    _seed_default_kb(db)
finally:
    db.close()

# 创建 FastAPI 应用
app = FastAPI(
    title="RAG 知识库问答系统",
    description="基于 LangChain 的企业级 RAG 知识库问答系统，面向电商商品知识库场景",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    logger.info(f"{request.method} {request.url.path} - {response.status_code} ({elapsed:.2f}s)")
    return response


# 健康检查
@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "RAG 知识库问答系统"}


# 注册路由
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(knowledge_router)


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误", "message": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)