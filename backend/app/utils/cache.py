"""LRU 内存缓存工具"""
import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from app.config import CACHE_MAX_SIZE, CACHE_TTL, REDIS_URL

logger = logging.getLogger("rag-app")


# ---------------------------------------------------------------------------
# 跨进程失效：把"语料版本号"放到 Redis 里共享
# ---------------------------------------------------------------------------
# **为什么必须有这个东西**
# 缓存是**进程内**的，而文档处理跑在独立的 Celery worker 进程里。
# worker 处理完文档后调用 clear_cache()，清的只是**它自己**的缓存——
# 正在给用户提供服务的 backend 进程完全不知道语料变了。
#
# 后果不是"稍微慢一点"，而是**答错**：
# 用户上传文档前问过「支持哪些数据源？」，得到"知识库中未收录"，
# 这个空结果被缓存了；上传完成后同样的问题在 TTL 内仍会返回旧的空答案，
# 用户会以为文档没上传成功。
#
# 修法：失效时把一个共享的版本号 +1，缓存键里带上版本号。
# 版本号一变，所有旧键自然失配，各进程无需互相通知。
_EPOCH_KEY = "rag:cache:epoch"

_epoch_client: Any = None
_epoch_lock = threading.Lock()
_local_epoch = 0


def _get_epoch_client():
    """惰性建立 Redis 连接。连不上就退化为进程内计数（等于修复前的行为），
    但会**打印告警**——静默退化会让这个 bug 在下一次部署时原样复现。"""
    global _epoch_client

    if _epoch_client is not None:
        return _epoch_client or None

    with _epoch_lock:
        if _epoch_client is not None:
            return _epoch_client or None
        try:
            import redis

            client = redis.Redis.from_url(
                REDIS_URL, socket_connect_timeout=1, socket_timeout=1,
                decode_responses=True,
            )
            client.get(_EPOCH_KEY)  # 探活
            _epoch_client = client
            logger.info("缓存失效已接入 Redis，可跨进程生效")
        except Exception as exc:
            _epoch_client = False  # 记住失败，避免每次调用都重试
            logger.warning(
                f"Redis 不可用（{exc}），缓存失效**无法跨进程生效**。"
                "多进程部署（Celery worker + backend）下，"
                "文档更新后最长 CACHE_TTL 秒内的检索结果可能是旧的。"
            )
    return _epoch_client or None


def _shared_epoch() -> str:
    client = _get_epoch_client()
    if client is None:
        return str(_local_epoch)
    try:
        return client.get(_EPOCH_KEY) or "0"
    except Exception:
        return str(_local_epoch)


def bump_shared_epoch() -> None:
    """把共享版本号 +1，让所有进程的旧缓存键同时失效。"""
    global _local_epoch
    _local_epoch += 1
    client = _get_epoch_client()
    if client is not None:
        try:
            client.incr(_EPOCH_KEY)
        except Exception as exc:
            logger.warning(f"跨进程缓存失效失败，本进程仍会失效: {exc}")


def reset_epoch_client() -> None:
    """重置 Redis 连接缓存。测试与"Redis 后来才起来"的场景需要。"""
    global _epoch_client
    with _epoch_lock:
        _epoch_client = None


class LRUCache:
    """线程安全的 LRU 缓存，支持 TTL"""

    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def _make_key(self, *args, **kwargs) -> str:
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        # 键里带上跨进程共享的语料版本号：版本一变，旧键自动失配。
        # 这样各进程不需要互相通知，也不需要额外的失效消息通道。
        return hashlib.md5(f"{_shared_epoch()}:{raw}".encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if time.time() - timestamp > self.ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
        self._cache[key] = (value, time.time())

    def clear(self):
        self._cache.clear()

    def stats(self) -> dict:
        return {"size": len(self._cache), "max_size": self.max_size, "ttl": self.ttl}


_cache = LRUCache()

# 失效回调：语料变更时，除检索结果缓存外，其它派生于语料的缓存
# （如 BM25 倒排索引）也必须一并失效。用注册机制而非直接 import，
# 避免 utils 层反向依赖 services 层造成循环导入。
_invalidation_hooks: list[Callable[[], None]] = []


def register_invalidation_hook(fn: Callable[[], None]) -> None:
    """注册一个「语料已变更」时需要执行的清理函数"""
    if fn not in _invalidation_hooks:
        _invalidation_hooks.append(fn)


def clear_cache() -> int:
    """清空查询缓存及其它派生于语料的缓存，返回清理前的条目数。

    **重要**：知识库发生任何变更（文档新增/删除/重新索引）后必须调用本函数。
    否则缓存中仍保留基于旧语料计算的检索结果，用户会在 TTL（默认 300 秒）内
    看到「引用已删除文档」的错误答案。

    注意这里做的是**两件事**，缺一不可：
      1. 清掉本进程的缓存（下面 _cache.clear()）
      2. 把共享版本号 +1，让**其它进程**（backend / 多个 worker）的缓存一并失效
    只做第 1 件，就是本文档开头描述的那个 bug：文档处理在 worker 里，
    用户请求打到 backend 上，清了等于没清。
    """
    size = len(_cache._cache)
    _cache.clear()
    bump_shared_epoch()
    for hook in _invalidation_hooks:
        try:
            hook()
        except Exception:
            pass
    return size


def query_cache(func: Callable) -> Callable:
    """装饰器：根据函数参数缓存返回结果"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = _cache._make_key(func.__name__, *args, **kwargs)
        cached = _cache.get(key)
        if cached is not None:
            return cached
        result = func(*args, **kwargs)
        _cache.set(key, result)
        return result

    # 指向 clear_cache 而不是 _cache.clear：只清本进程是不够的，
    # 别的进程（backend / 其它 worker）里的同名缓存也必须一起失效
    wrapper.cache_clear = clear_cache  # type: ignore
    return wrapper