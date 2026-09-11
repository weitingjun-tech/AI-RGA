"""任务投递入口：优先投给 Celery，broker 不可用时降级为本地线程。

**为什么要有降级**
Celery 依赖 Redis。本地开发/演示机器未必装得起 Redis（Windows 上尤其麻烦），
但"上传文档"是核心功能，不能因为缺一个中间件就整条链路不可用。

**为什么降级必须大声告警**
降级路径没有跨进程持久化——进程重启，队列里的任务就没了。
如果静默降级，生产环境 Redis 挂掉后会退化成单机线程模式，
表面上一切正常，实际上每次发版都会丢任务。所以这里每次都打 ERROR 级日志。

用 TASK_QUEUE_MODE 显式控制：
    auto（默认）—— 探测 broker，可用走 Celery，否则降级
    celery      —— 强制 Celery，broker 不可用直接报错（生产建议值）
    thread      —— 强制本地线程（纯本地开发）
"""
import logging
import threading
import time

from app.config import REDIS_URL, TASK_QUEUE_MODE

logger = logging.getLogger("rag-app")

# broker 可用性探测结果缓存，避免每次上传都去 ping 一次 Redis
_broker_probe: dict[str, float | bool | None] = {"checked_at": 0.0, "available": None}
_BROKER_PROBE_TTL = 10.0  # 秒

_warned_about_fallback = False


def broker_available() -> bool:
    """探测 Redis 是否可用（结果缓存 10 秒）。"""
    now = time.monotonic()
    if (
        _broker_probe["available"] is not None
        and now - float(_broker_probe["checked_at"]) < _BROKER_PROBE_TTL
    ):
        return bool(_broker_probe["available"])

    available = False
    try:
        import redis

        client = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        available = True
    except Exception:
        available = False

    _broker_probe.update(checked_at=now, available=available)
    return available


def enqueue_document_task(doc_id: int, file_path: str, filename: str) -> str:
    """把文档处理任务投递出去。

    返回实际使用的执行方式："celery" 或 "thread"，便于调用方在响应里
    如实告诉前端（例如提示"队列不可用，已降级处理"）。
    """
    global _warned_about_fallback

    if TASK_QUEUE_MODE == "thread":
        _dispatch_to_thread(doc_id, file_path, filename)
        return "thread"

    if TASK_QUEUE_MODE == "celery" or broker_available():
        try:
            from app.tasks.document_tasks import process_document_task

            process_document_task.delay(doc_id, file_path, filename)
            return "celery"
        except Exception as exc:
            if TASK_QUEUE_MODE == "celery":
                # 强制模式下一律不降级：宁可让上传失败并暴露问题，
                # 也不能悄悄退化成会丢任务的模式
                logger.error(f"任务投递失败（TASK_QUEUE_MODE=celery，不降级）: {exc}")
                raise
            logger.error(f"任务投递到 Celery 失败，降级为本地线程: {exc}")

    if not _warned_about_fallback:
        _warned_about_fallback = True
        logger.error(
            "=" * 70 + "\n"
            f"Redis 不可用（{REDIS_URL}），文档处理已降级为**本地线程**模式。\n"
            "该模式下：进程重启会丢失未完成的任务，也没有跨机重试。\n"
            "仅供本地开发使用，生产环境请启动 Redis 与 Celery worker：\n"
            "  docker run -d -p 6379:6379 redis:7-alpine\n"
            "  cd backend && celery -A app.celery_app:celery_app worker --pool=solo -l info\n"
            + "=" * 70
        )

    _dispatch_to_thread(doc_id, file_path, filename)
    return "thread"


def _dispatch_to_thread(doc_id: int, file_path: str, filename: str) -> None:
    """本地线程执行（降级路径）。

    注意：必须是**非守护线程**。守护线程会随主进程退出被强制杀掉，
    文档状态就永久停在 processing 了——这正是历史实现的问题所在。
    """
    from app.tasks.document_tasks import run_with_retries

    def _worker():
        try:
            run_with_retries(doc_id, file_path, filename)
        except Exception as exc:  # run_with_retries 理论上不抛，兜底防线程静默死亡
            logger.error(f"本地线程处理文档失败 doc_id={doc_id}: {exc}", exc_info=True)

    threading.Thread(
        target=_worker, name=f"doc-{doc_id}", daemon=False
    ).start()
