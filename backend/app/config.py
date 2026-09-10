# RAG 企业级知识库问答系统 - 后端配置
import os
from dotenv import load_dotenv

load_dotenv()

# 数据库
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "rag_knowledge_base")

DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
DATABASE_URL_ASYNC = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", "my-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRE_MINUTES = 120  # 2小时
JWT_REFRESH_EXPIRE_DAYS = 7

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# Embedding
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")  # GTX 1650 显存紧张时用 CPU

# ChromaDB
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "ecommerce_knowledge")

# 分块
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.3"))

# 缓存
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # 5分钟
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "128"))

# 文件上传
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "20"))  # MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".docx", ".epub", ".mobi"}

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")