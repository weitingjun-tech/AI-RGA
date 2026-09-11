# RAG 企业级知识库问答系统 - 后端配置
import os
import secrets
import sys
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

# 运行环境：development / production
# 影响 JWT 密钥校验强度、/docs 是否开放、异常是否返回细节
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# JWT
_JWT_SECRET_PLACEHOLDER = "my-secret-key-change-in-production"
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()

# 密钥必须显式配置且足够长。
# 为什么不能有兜底默认值：默认值一旦公开，任何人都能自己签一个
# {"sub": "1", "role": "admin"} 的 token 冒充管理员——这不是"弱口令"，是后门。
if not JWT_SECRET or JWT_SECRET == _JWT_SECRET_PLACEHOLDER:
    if IS_PRODUCTION:
        raise RuntimeError(
            "生产环境必须设置 JWT_SECRET（当前未设置或仍是默认占位值）。\n"
            "生成方式：python -c \"import secrets; print(secrets.token_urlsafe(48))\"\n"
            "然后写入 backend/.env 的 JWT_SECRET=..."
        )
    # 开发环境：随机生成，保证"至少不可预测"。
    # 代价是重启后旧 token 全部失效（需要重新登录），这是刻意为之——
    # 宁可开发者多登录一次，也不能让固定密钥被带进生产。
    JWT_SECRET = secrets.token_urlsafe(48)
    print(
        "[配置警告] 未设置 JWT_SECRET，已生成临时随机密钥。"
        "重启后需重新登录。生产环境请务必在 .env 中显式配置。",
        file=sys.stderr,
    )
elif len(JWT_SECRET) < 32:
    message = (
        f"JWT_SECRET 长度仅 {len(JWT_SECRET)} 字符，低于 32 字符下限，"
        "存在被暴力破解的风险。\n"
        "生成方式：python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
    if IS_PRODUCTION:
        raise RuntimeError(message)
    print(f"[配置警告] {message}", file=sys.stderr)

JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", "120"))  # 2小时
JWT_REFRESH_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))

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
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",") if o.strip()]

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")  # text | json

# ---------------------------------------------------------------------------
# 启动行为
# ---------------------------------------------------------------------------
# 启动时自动执行 alembic upgrade head。
# 单副本部署可以开着（省事）；多副本生产**必须关掉**，
# 改由发布流水线执行迁移，否则多个副本会并发跑同一批 DDL。
RUN_MIGRATIONS_ON_STARTUP = (
    os.getenv("RUN_MIGRATIONS_ON_STARTUP", "true").lower() == "true"
)

# 启动时把卡在 queued/processing 的历史文档重新入队
RECONCILE_ON_STARTUP = os.getenv("RECONCILE_ON_STARTUP", "true").lower() == "true"

# ---------------------------------------------------------------------------
# 异步任务队列（Celery + Redis）
# ---------------------------------------------------------------------------
# 文档入库是耗时操作（解析 + 分块 + 逐块算 embedding），必须异步执行。
# 历史实现用的是 threading.Thread(daemon=True)，有三个硬伤：
#   1. 进程重启 → 未完成的任务直接消失，文档状态永久卡在 processing
#   2. 失败无人重试，也没有失败记录
#   3. 没有并发上限，批量上传会瞬间打满 CPU
# 换成 Celery 后这三个问题分别由 broker 持久化、retry 策略、worker 并发数解决。
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

# 任务投递模式：
#   auto   —— 探测 broker，可用则走 Celery，否则降级本地线程（默认，便于开箱即用）
#   celery —— 强制 Celery，broker 不可用直接报错（**生产建议**）
#   thread —— 强制本地线程（纯本地开发，会丢任务）
TASK_QUEUE_MODE = os.getenv("TASK_QUEUE_MODE", "auto").strip().lower()

# 文档处理任务的重试策略
DOC_TASK_MAX_RETRIES = int(os.getenv("DOC_TASK_MAX_RETRIES", "3"))
DOC_TASK_RETRY_DELAY = int(os.getenv("DOC_TASK_RETRY_DELAY", "30"))  # 秒

# 任务被 worker 领取后多久算超时（超过则视为 worker 崩溃，由对账逻辑重新入队）
DOC_TASK_TIMEOUT_SECONDS = int(os.getenv("DOC_TASK_TIMEOUT_SECONDS", "1800"))

# ---------------------------------------------------------------------------
# 接口限流
# ---------------------------------------------------------------------------
# 问答接口会真实消耗 LLM 算力，不限流的话一个脚本就能把服务刷满。
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "10/minute")      # 防暴力破解
RATE_LIMIT_REGISTER = os.getenv("RATE_LIMIT_REGISTER", "5/hour")   # 防批量注册
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "30/minute")        # 问答
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "60/hour")      # 上传

# 登录失败锁定：同一账号连续失败 N 次后锁定 M 分钟
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))

# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
# 记录"谁在什么时候对什么对象做了什么"。企业合规要求，出事时用来定责。
AUDIT_LOG_ENABLED = os.getenv("AUDIT_LOG_ENABLED", "true").lower() == "true"

# ---------------------------------------------------------------------------
# 权限（ACL）
# ---------------------------------------------------------------------------
# true  = 普通用户只能检索被显式授权的知识库（企业默认，最小权限）
# false = 所有登录用户可访问全部知识库（仅适合单人开发调试）
# 管理员始终可访问全部。
KB_ACL_ENABLED = os.getenv("KB_ACL_ENABLED", "true").lower() == "true"