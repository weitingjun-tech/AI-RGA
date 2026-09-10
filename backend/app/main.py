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
from app.config import CORS_ORIGINS, UPLOAD_DIR, CHROMA_PERSIST_DIR
from app.services.auth_service import seed_admin

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rag-app")

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 确保目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)

# 预置管理员账号
db = SessionLocal()
try:
    seed_admin(db)
    logger.info("管理员账号已就绪: admin / 123456")
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