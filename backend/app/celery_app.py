"""Celery 应用实例。

启动 worker（独立进程，与 API 进程分开跑）：
    cd backend
    celery -A app.celery_app:celery_app worker --loglevel=info --concurrency=2

Windows 下必须加 --pool=solo，原因见文件末尾注释。
"""
from celery import Celery

from app.config import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    DOC_TASK_MAX_RETRIES,
    DOC_TASK_RETRY_DELAY,
    DOC_TASK_TIMEOUT_SECONDS,
)

celery_app = Celery(
    "rag",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    # 显式列出任务模块，比 autodiscover 更可控（不会漏扫或误扫）
    include=["app.tasks.document_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,

    # ---- 可靠性：这几项决定了"任务会不会丢" ----
    # acks_late：任务**执行完成后**才向 broker 确认。
    #   默认的 acks_early 是"一领到就确认"，worker 在执行中崩溃时，
    #   任务既没完成也已被确认，直接从队列消失 —— 正是我们要修掉的问题。
    task_acks_late=True,
    # worker 被杀时把任务退回队列，而不是随 worker 一起消失
    task_reject_on_worker_lost=True,
    # 一次只预取一个任务。默认值 4 会让 worker 囤积任务，
    # 排在后面的文档要等前面的长任务跑完，队列看起来像卡死了。
    worker_prefetch_multiplier=1,
    # broker 启动时不可用则重试，而不是直接崩溃（容器编排下 broker 可能后起）
    broker_connection_retry_on_startup=True,
    # 结果保留 1 小时即可，避免 Redis 无限增长
    result_expires=3600,

    # ---- 超时 ----
    # 硬超时：到点直接杀掉任务，防止解析超大 PDF 时永久占住 worker
    task_time_limit=DOC_TASK_TIMEOUT_SECONDS,
    # 软超时：先抛异常让任务自己收尾（把文档标成失败），比被直接杀掉体验好
    task_soft_time_limit=max(60, DOC_TASK_TIMEOUT_SECONDS - 60),

    # 默认重试策略，任务内可用 self.retry() 覆盖
    task_default_retry_delay=DOC_TASK_RETRY_DELAY,
    task_default_max_retries=DOC_TASK_MAX_RETRIES,
)


# Windows 说明：
# Celery 默认使用 prefork 进程池，在 Windows 上与 asyncio/事件循环冲突会报错。
# Windows 下启动 worker 必须显式指定 --pool=solo（单进程串行执行）。
# Linux/macOS 用默认值即可，并发数由 --concurrency 控制。
