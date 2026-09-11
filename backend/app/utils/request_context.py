"""请求上下文 —— 给同一次请求产生的所有日志打上同一个 request_id。

为什么需要：
一次问答会先后产生「检索」「BM25 融合」「LLM 调用」「写数据库」等十几条日志，
没有关联 id 时它们和别人的请求混在一起，出了问题（比如某个用户反馈"特别慢"）
根本无法把它们串成一条链路。带上 request_id 后，`grep <id>` 就能还原全过程。

实现用 ContextVar 而不是全局变量：FastAPI 的异步请求会并发跑在同一个线程里，
全局变量会被别的请求覆盖，ContextVar 则是每个协程独立的。
"""
import logging
import uuid
from contextvars import ContextVar

# 默认值 "-" 表示不在请求上下文中（如后台任务、启动脚本）
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str | None = None) -> str:
    """设置当前上下文的 request_id；不传或传空则自动生成一个。"""
    rid = (value or "").strip()[:64] or uuid.uuid4().hex[:16]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """给每条日志记录注入 request_id，供 Formatter 引用 %(request_id)s。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True
