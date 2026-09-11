"""
RAG 企业级知识库问答系统 - FastAPI 入口
"""
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 导入全部模型，确保 create_all 能建出所有表（含多知识库相关的 knowledge_bases）
import app.models  # noqa: F401
from app.config import (
    APP_ENV,
    BACKEND_DIR,
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    CORS_ORIGINS,
    DOC_TASK_TIMEOUT_SECONDS,
    IS_PRODUCTION,
    RECONCILE_ON_STARTUP,
    RUN_MIGRATIONS_ON_STARTUP,
    UPLOAD_DIR,
)
from app.database import SessionLocal, engine
from app.services.auth_service import seed_admin
from app.utils.logging_config import setup_logging
from app.utils.request_context import get_request_id, set_request_id

# 配置日志（必须在其它模块打日志之前完成）
setup_logging()
logger = logging.getLogger("rag-app")

# 首个迁移版本的 revision id（见 migrations/versions/ 下的基线文件）。
# 已有数据库"收编"进 Alembic 管理时，需要先把版本号标记到这个基线。
BASELINE_REVISION = "0001_baseline"


def _run_migrations() -> None:
    """执行数据库迁移（alembic upgrade head）。

    为什么用 Alembic 取代原先手写的 `_migrate_add_kb_id` 这类函数：
    手写迁移只能"加列"，改不了类型、加不了索引、**更不能回滚**，
    而且没有版本记录——没人知道线上到底跑过哪些变更。
    真实项目里改错一次表结构就需要人工修数据，代价极高。

    两种部署方式的取舍：
    - 本函数在启动时自动迁移，适合本地开发和单副本部署，"拉下来就能跑"
    - 多副本生产环境应设置 RUN_MIGRATIONS_ON_STARTUP=false，
      由发布流水线单独执行 `alembic upgrade head`，
      否则多个副本同时启动会并发执行同一批 DDL
    """
    if not RUN_MIGRATIONS_ON_STARTUP:
        logger.info("已跳过启动时迁移（RUN_MIGRATIONS_ON_STARTUP=false）")
        return

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    with engine.connect() as conn:
        current_revision = MigrationContext.configure(conn).get_current_revision()

    if current_revision is None:
        # 库里已有表但没有 alembic_version —— 说明这套表是"历史遗留"，
        # 由早期版本的 create_all 建的。此时不能直接 upgrade（会重复建表报错），
        # 而要先把它标记成"已经处于基线版本"，再往后升级。
        if "documents" in set(inspect(engine).get_table_names()):
            command.stamp(cfg, BASELINE_REVISION)
            logger.info(f"检测到既有数据库，已标记为基线版本 {BASELINE_REVISION}")
        # 全新数据库：从头执行所有迁移即可

    command.upgrade(cfg, "head")
    logger.info("数据库迁移已完成（alembic upgrade head）")


def _seed_default_kb(db):
    """确保至少存在一个默认知识库，并把历史遗留（kb_id 为空）的文档归入其中。"""
    from app.models.document import Document
    from app.models.knowledge_base import KnowledgeBase

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


def _reconcile_stuck_documents() -> None:
    """启动对账：把卡在 queued / processing 的文档重新入队。

    为什么需要：Celery 的 broker 是持久的，任务本身不会因为 API 进程重启而丢。
    但仍有两种情况会留下"永远卡住"的文档：
      1. worker 被强杀且超出 acks_late 的重投窗口
      2. 早期版本用裸线程处理时留下的存量脏数据（进程一重启就丢）
    这些文档的状态是 queued/processing，但队列里已经没有对应任务了，
    前端会一直显示"处理中"直到天荒地老。

    阈值取 DOC_TASK_TIMEOUT_SECONDS：只有超过这个时长还在处理中的，
    才判定为"卡住"。低于阈值的不动——它们可能只是排在队列里还没轮到，
    重复入队会导致同一个文档被处理两次（虽然有幂等保护，但纯属浪费算力）。
    """
    from datetime import datetime, timedelta

    from app.models.document import Document
    from app.services.task_dispatch import enqueue_document_task

    if not RECONCILE_ON_STARTUP:
        return

    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(seconds=DOC_TASK_TIMEOUT_SECONDS)
        stuck = (
            db.query(Document)
            .filter(
                Document.status.in_(["queued", "processing"]),
                Document.created_at < cutoff,
            )
            .all()
        )
        if not stuck:
            return

        logger.warning(f"发现 {len(stuck)} 个卡住的文档，正在重新入队")
        for doc in stuck:
            file_path = os.path.join(UPLOAD_DIR, doc.filename)
            if not os.path.exists(file_path):
                doc.status = "error"
                db.commit()
                logger.error(f"卡住文档的源文件已丢失，标记失败 doc_id={doc.id}")
                continue
            doc.status = "queued"
            db.commit()
            enqueue_document_task(doc.id, file_path, doc.filename)
        logger.info(f"对账完成，已重新入队 {len(stuck)} 个文档")
    except Exception as exc:
        # 对账失败不能阻止应用启动——它只是补救措施，不是启动前提
        logger.error(f"启动对账失败（不影响服务启动）: {exc}", exc_info=True)
    finally:
        db.close()


_run_migrations()

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

_reconcile_stuck_documents()

# 创建 FastAPI 应用
app = FastAPI(
    title="RAG 知识库问答系统",
    description="基于 LangChain 的企业级 RAG 知识库问答系统，面向电商商品知识库场景",
    version="1.0.0",
    # /docs 与 /redoc 会完整暴露内部接口结构，生产环境默认关闭。
    # 需要在生产临时开启时设置 EXPOSE_DOCS=true 并确保外层有鉴权。
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求上下文 + 访问日志中间件
#
# 这两件事必须放在同一个中间件里做：request_id 要在任何日志产生之前设置好，
# 拆成两个中间件时 Starlette 的洋葱模型容易让顺序反过来，
# 导致部分日志拿不到 request_id。
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    # 复用上游（网关 / 前端）传来的 id，便于跨服务串联整条链路
    request_id = set_request_id(request.headers.get("X-Request-ID"))
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        logger.exception(
            f"{request.method} {request.url.path} 处理失败 ({elapsed:.0f}ms)"
        )
        raise
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code} ({elapsed:.0f}ms)"
    )
    # 回传给客户端：用户报障时把这个 id 给到运维就能直接定位
    response.headers["X-Request-ID"] = request_id
    return response


# 健康检查（存活探针）—— 只回答"进程还活着吗"，不查依赖。
# 依赖挂掉时不应该重启应用容器，那是就绪探针的职责。
@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "RAG 知识库问答系统", "env": APP_ENV}


# 就绪探针 —— 逐项探测依赖，任一不可用则返回 503，流量不应打到本实例。
# 与存活探针分开的意义：数据库临时抖动时，让负载均衡摘掉本节点即可，
# 而重启进程不但没用，还会丢掉正在执行的请求。
@app.get("/api/health/ready")
def readiness_check():
    checks: dict[str, str] = {}
    healthy = True

    # MySQL
    try:
        from sqlalchemy import text as _text

        with engine.connect() as conn:
            conn.execute(_text("SELECT 1"))
        checks["mysql"] = "ok"
    except Exception as exc:
        checks["mysql"] = f"error: {type(exc).__name__}"
        healthy = False

    # ChromaDB（嵌入式）—— 只检查客户端句柄可用
    try:
        from app.services.kb_service import get_chroma_client

        get_chroma_client().heartbeat()
        checks["chroma"] = "ok"
    except Exception as exc:
        checks["chroma"] = f"error: {type(exc).__name__}"
        healthy = False

    # 上传目录可写
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        probe = os.path.join(UPLOAD_DIR, ".write_probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        checks["upload_dir"] = "ok"
    except Exception as exc:
        checks["upload_dir"] = f"error: {type(exc).__name__}"
        healthy = False

    payload = {"status": "ok" if healthy else "degraded", "checks": checks}
    return JSONResponse(status_code=200 if healthy else 503, content=payload)


# 注册路由
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(admin_router)


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """兜底异常处理。

    关键原则：**异常细节只进日志，不出接口**。
    历史实现会把 str(exc) 原样返回给前端，而 SQLAlchemy / pymysql 的报错里
    通常包含完整的 SQL 语句、表名、字段名，连接失败时甚至包含主机、端口和用户名——
    等于把数据库结构免费送给任何一个能触发 500 的攻击者。
    现在只回一个 request_id，运维凭它在日志里查到完整堆栈。
    """
    request_id = get_request_id()
    logger.error(f"未处理异常 [{request_id}]: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误，请稍后重试或联系管理员",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败。返回字段级错误便于前端定位，但不回显原始输入值（可能含密码）。"""
    errors = [
        {"field": ".".join(str(x) for x in e.get("loc", [])), "message": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "请求参数不合法", "errors": errors})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)