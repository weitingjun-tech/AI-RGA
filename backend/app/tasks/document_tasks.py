"""文档处理的后台任务。

由独立进程的 Celery worker 执行，与 API 进程完全解耦：
API 只负责把任务丢进队列并立刻返回，用户不用等着解析完。

    cd backend
    celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo

任务体（_execute_once）被两条路径共用：Celery worker 走重试机制，
无 broker 时的降级线程走本文件里的简易重试循环。
"""
import logging
import os
import time

from celery.exceptions import SoftTimeLimitExceeded

from app.celery_app import celery_app
from app.config import DOC_TASK_MAX_RETRIES, DOC_TASK_RETRY_DELAY
from app.database import SessionLocal
from app.models.document import Document
from app.services.kb_service import PermanentProcessingError, process_document
from app.utils.request_context import set_request_id

logger = logging.getLogger("rag-app")


def _mark_failed(db, doc_id: int, reason: str) -> None:
    """把文档标记为最终失败。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if doc:
        doc.status = "error"
        db.commit()
        logger.error(f"文档处理最终失败 doc_id={doc_id}: {reason}")


def _execute_once(doc_id: int, file_path: str, filename: str) -> dict:
    """完整处理一个文档。失败时抛异常，由调用方决定重试还是判死。

    幂等性由两层保证：
      1. 执行前检查文档是否仍存在（可能已被用户删除）
      2. process_document 内部会先清掉该文档的旧向量
    因此同一任务被重复投递（worker 崩溃后重投）不会产生重复数据。
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            # 用户在上传后、处理前删掉了文档 —— 正常情况，不是错误
            logger.info(f"文档已不存在，跳过处理 doc_id={doc_id}")
            return {"status": "skipped", "reason": "document_deleted"}

        if not os.path.exists(file_path):
            _mark_failed(db, doc_id, f"源文件不存在: {file_path}")
            return {"status": "failed", "reason": "file_missing"}

        # 标记为处理中，让前端能从"排队中"切到"处理中"
        doc.status = "processing"
        db.commit()

        process_document(db, doc_id, file_path, filename)

        db.refresh(doc)
        return {"status": "ready", "doc_id": doc_id, "chunks": doc.chunk_count}

    except PermanentProcessingError as exc:
        # 重试也不会变好的失败（格式不支持、扫描件无文本），直接判死
        _mark_failed(db, doc_id, str(exc))
        return {"status": "failed", "reason": str(exc)}

    except Exception:
        # 临时性失败：不在这里改状态，交给调用方决定重试还是最终判死。
        # 若在这里就置 error，用户会在重试期间看到闪烁的"失败→处理中→失败"。
        db.rollback()
        raise

    finally:
        db.close()


@celery_app.task(bind=True, name="documents.process", max_retries=DOC_TASK_MAX_RETRIES)
def process_document_task(self, doc_id: int, file_path: str, filename: str) -> dict:
    """Celery 版入口：由 broker 持久化任务，失败按指数退避重试。"""
    # worker 里没有 HTTP 请求上下文，用任务 id 造一个 request_id，
    # 这样该任务产生的日志也能被串成一条链路
    task_id = self.request.id or "local"
    set_request_id(f"task-{task_id[:12]}")

    try:
        result = _execute_once(doc_id, file_path, filename)
        if result["status"] == "ready":
            logger.info(
                f"任务完成 doc_id={doc_id} chunks={result.get('chunks')} "
                f"重试次数={self.request.retries}"
            )
        return result

    except SoftTimeLimitExceeded:
        # 超时通常是文件过大，重试大概率还是超时，但保留一次机会
        logger.warning(f"文档处理超时 doc_id={doc_id}")
        if self.request.retries >= self.max_retries:
            _finalize_failure(doc_id, "处理超时（文件过大或解析卡住）")
            return {"status": "failed", "reason": "timeout"}
        raise self.retry(exc=SoftTimeLimitExceeded(), countdown=10)

    except Exception as exc:
        if self.request.retries >= self.max_retries:
            _finalize_failure(doc_id, f"{type(exc).__name__}: {exc}")
            return {"status": "failed", "reason": str(exc)}

        # 指数退避：30s, 60s, 120s… 避免持续失败的任务把 worker 占满
        countdown = min(600, DOC_TASK_RETRY_DELAY * (2 ** self.request.retries))
        logger.warning(
            f"文档处理失败，{countdown}s 后第 {self.request.retries + 1} 次重试 "
            f"doc_id={doc_id}: {exc}"
        )
        raise self.retry(exc=exc, countdown=countdown)


def _finalize_failure(doc_id: int, reason: str) -> None:
    """重试耗尽后落库标记失败（重开一个 session，调用方的已回滚）。"""
    db = SessionLocal()
    try:
        _mark_failed(db, doc_id, reason)
    finally:
        db.close()


def run_with_retries(doc_id: int, file_path: str, filename: str) -> dict:
    """无 broker 时的降级路径：本地线程里同步重试。

    重试策略与 Celery 版保持一致，只是缺少跨进程的持久化——
    进程若在此期间挂掉，任务仍然会丢。所以这条路径只适合开发/演示环境，
    生产必须用 worker（见 task_dispatch 的告警）。
    """
    for attempt in range(DOC_TASK_MAX_RETRIES + 1):
        try:
            result = _execute_once(doc_id, file_path, filename)
            if result["status"] == "ready":
                logger.info(f"任务完成（本地线程）doc_id={doc_id} chunks={result.get('chunks')}")
            return result
        except Exception as exc:
            if attempt >= DOC_TASK_MAX_RETRIES:
                _finalize_failure(doc_id, f"{type(exc).__name__}: {exc}")
                return {"status": "failed", "reason": str(exc)}
            countdown = min(600, DOC_TASK_RETRY_DELAY * (2 ** attempt))
            logger.warning(
                f"文档处理失败，{countdown}s 后重试（本地线程）doc_id={doc_id}: {exc}"
            )
            time.sleep(countdown)
    return {"status": "failed", "reason": "retries_exhausted"}
