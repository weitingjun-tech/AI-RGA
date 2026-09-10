# RAG 企业级知识库问答系统 - 后端配置
import os
from pathlib import Path

from dotenv import load_dotenv

# 配置以 backend 目录为锚点加载，保证从任意工作目录启动都读到同一份 .env
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def resolve_path(p: str) -> str:
    """把配置里的相对路径统一解析到 backend 目录下。

    为什么需要：CHROMA_PERSIST_DIR / UPLOAD_DIR 若按工作目录解析，
    从别的目录（如测试脚本、eval 脚本）启动时会静默连到一个**空的数据目录**，
    表现为「知识库明明有数据却检索不到」，且不报任何错，极难排查。
    """
    path = Path(p)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return str(path)

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
CHROMA_PERSIST_DIR = resolve_path(os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"))
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "ecommerce_knowledge")

# 分块
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.3"))

# 混合检索（向量 + BM25）
# 纯向量检索对型号、错误码、专有名词类查询召回差，BM25 恰好擅长这些，
# 两者用 RRF（倒数排序融合）合并，无需训练即可显著提升召回。
HYBRID_SEARCH_ENABLED = os.getenv("HYBRID_SEARCH_ENABLED", "true").lower() == "true"
# 每路检索的候选数量（宽召回，后续再融合 + 去冗 + 截断）
HYBRID_CANDIDATE_K = int(os.getenv("HYBRID_CANDIDATE_K", "20"))
# RRF 融合常数，业界常用 60
RRF_K = int(os.getenv("RRF_K", "60"))
# MMR / 去冗余：移除与已选片段高度重复的候选，避免 Top-K 被近似内容占满
DEDUP_ENABLED = os.getenv("DEDUP_ENABLED", "true").lower() == "true"
DEDUP_JACCARD_THRESHOLD = float(os.getenv("DEDUP_JACCARD_THRESHOLD", "0.8"))
# 是否将每次检索的明细写入 retrieval_logs 表（用于 bad case 归因与效果分析）
RETRIEVAL_LOG_ENABLED = os.getenv("RETRIEVAL_LOG_ENABLED", "true").lower() == "true"

# RAG 系统提示词（可按业务场景通过环境变量覆盖，占位符 {context} 会被替换为检索到的知识库内容）
RAG_SYSTEM_PROMPT = os.getenv("RAG_SYSTEM_PROMPT", """你是一位专业的技术支持工程师，服务于 CloudFlow 智能数据集成平台的客户。

请严格遵守以下规则：
1. 只依据下方「知识库参考内容」作答，不要依赖你自己的先验知识编造产品细节
2. 引用知识库内容时，用 **[来源: 文档名]** 标注出处，便于用户核查
3. 若知识库中没有相关信息，必须诚实说明「知识库中未收录该信息」，并建议用户提交工单或联系技术支持
4. 严禁编造任何知识库中没有的具体信息，包括但不限于：
   邮箱地址、电话号码、网址、人名、公司名、地址、价格、版本号、参数数值
5. 即使是用户明确索要的联系方式，若知识库未提供，也只能回答「知识库中未收录」，不要给出任何示例或推测值
6. 涉及操作步骤时给出清晰的编号步骤；涉及报错时先给排查顺序，再给解决方案
7. 回答结构清晰，适当使用列表、分段；语气专业、准确、简洁

知识库参考内容：
{context}""")

# 缓存
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # 5分钟
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "128"))

# 文件上传
UPLOAD_DIR = resolve_path(os.getenv("UPLOAD_DIR", "./uploads"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "20"))  # MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".docx", ".epub", ".mobi"}

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")