"""LRU 内存缓存工具"""
import hashlib
import json
import functools
import time
from collections import OrderedDict
from typing import Any, Callable

from app.config import CACHE_TTL, CACHE_MAX_SIZE


class LRUCache:
    """线程安全的 LRU 缓存，支持 TTL"""

    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl: int = CACHE_TTL):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def _make_key(self, *args, **kwargs) -> str:
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()

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
    """
    size = len(_cache._cache)
    _cache.clear()
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

    wrapper.cache_clear = _cache.clear  # type: ignore
    return wrapper