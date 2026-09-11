"""查询缓存与**跨进程失效**测试。

这个文件守护的是一个真实发生过的故障：

容器部署下，文档处理跑在独立的 Celery worker 进程里。
worker 处理完后调用 `clear_cache()`，清的只是**它自己**的缓存 ——
正在给用户提供服务的 backend 进程完全不知道语料变了。

于是：用户上传文档前问过「支持哪些数据源？」，得到"未收录"，这个空结果被缓存；
上传完成后（worker 日志显示"清理检索缓存=0 条"，看起来一切正常），
同样的问题在 TTL 内仍然返回旧的空答案。用户会以为文档没传上去。

修法是把"语料版本号"放进缓存键并共享到 Redis：版本一变，所有进程的旧键同时失配。
"""
import pytest

from app.utils import cache as cache_mod
from app.utils.cache import LRUCache, clear_cache, query_cache


class _FakeRedis:
    """够用的假 Redis：只实现 get / incr。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.calls = {"get": 0, "incr": 0}

    def get(self, key):
        self.calls["get"] += 1
        return self.store.get(key)

    def incr(self, key):
        self.calls["incr"] += 1
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])


@pytest.fixture
def fake_redis(monkeypatch):
    """把共享版本号接到假 Redis 上，测试不依赖真实 Redis。"""
    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_epoch_client", fake)
    monkeypatch.setattr(cache_mod, "_local_epoch", 0)
    cache_mod._cache.clear()
    yield fake
    cache_mod._cache.clear()


@pytest.fixture
def no_redis(monkeypatch):
    """模拟 Redis 不可用：应退化为进程内失效，而不是直接坏掉。"""
    monkeypatch.setattr(cache_mod, "_epoch_client", False)
    monkeypatch.setattr(cache_mod, "_local_epoch", 0)
    cache_mod._cache.clear()
    yield
    cache_mod._cache.clear()


class TestLRUCacheBasics:
    def test_set_and_get(self):
        c = LRUCache(max_size=4, ttl=60)
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_missing_key_returns_none(self):
        assert LRUCache(max_size=4, ttl=60).get("nope") is None

    def test_expired_entry_returns_none(self, monkeypatch):
        # 先把"现在"取出来再 patch：cache_mod.time 就是 time 模块本身，
        # patch 之后再去调 time.time() 会调到自己造成无限递归
        now = cache_mod.time.time()
        c = LRUCache(max_size=4, ttl=60)
        c.set("k", "v")

        monkeypatch.setattr(cache_mod.time, "time", lambda: now + 61)
        assert c.get("k") is None

    def test_lru_eviction(self):
        c = LRUCache(max_size=2, ttl=60)
        c.set("a", 1)
        c.set("b", 2)
        c.get("a")          # a 变成最近使用
        c.set("c", 3)       # 应淘汰 b
        assert c.get("a") == 1
        assert c.get("b") is None

    def test_clear(self):
        c = LRUCache(max_size=4, ttl=60)
        c.set("k", "v")
        c.clear()
        assert c.get("k") is None


class TestQueryCacheDecorator:
    def test_caches_result(self, fake_redis):
        calls = []

        @query_cache
        def f(x):
            calls.append(x)
            return x * 2

        assert f(3) == 6
        assert f(3) == 6
        assert calls == [3], "第二次应当命中缓存，不应再调用原函数"

    def test_different_args_are_separate_entries(self, fake_redis):
        @query_cache
        def f(x):
            return x * 2

        assert f(1) == 2
        assert f(2) == 4


class TestCrossProcessInvalidation:
    """**本文件的核心**：别的进程改了语料，本进程必须立刻感知到。"""

    def test_epoch_is_part_of_the_key(self, fake_redis):
        c = LRUCache(max_size=8, ttl=60)
        key_before = c._make_key("q")
        cache_mod.bump_shared_epoch()
        assert c._make_key("q") != key_before, "版本号变了，缓存键必须跟着变"

    def test_cached_result_is_dropped_after_external_bump(self, fake_redis):
        """模拟真实故障场景：

        1. backend 进程缓存了一个（此时语料还是旧的）结果
        2. worker 进程处理完文档，调用 clear_cache() → 版本号 +1
        3. backend 再来同样的请求，**必须重新计算**，而不是返回旧值
        """
        calls = []

        @query_cache
        def retrieve(query):
            calls.append(query)
            return f"结果{len(calls)}"

        first = retrieve("支持哪些数据源")
        assert first == "结果1"

        # 另一个进程（worker）让缓存失效
        cache_mod.bump_shared_epoch()

        second = retrieve("支持哪些数据源")
        assert second == "结果2", (
            "版本号已经变了，却仍然返回了旧结果——"
            "这正是「上传文档后仍回答未收录」的成因"
        )
        assert len(calls) == 2

    def test_clear_cache_also_bumps_shared_epoch(self, fake_redis):
        """clear_cache 必须**同时**做两件事：清本进程 + 通知别的进程。

        少了后者，文档处理（在 worker 里）就白清了。
        """
        cache_mod._cache.set("k", "v")
        before = fake_redis.store.get(cache_mod._EPOCH_KEY, "0")

        clear_cache()

        after = fake_redis.store.get(cache_mod._EPOCH_KEY, "0")
        assert int(after) == int(before) + 1, "共享版本号没有被推进，别的进程不会失效"
        assert cache_mod._cache.get("k") is None, "本进程的缓存也必须被清掉"

    def test_epoch_client_failure_is_tolerated(self, fake_redis):
        """Redis 中途挂掉时，缓存读不到版本号也不能让请求失败。"""

        class _Broken:
            def get(self, _k):
                raise ConnectionError("redis down")

            def incr(self, _k):
                raise ConnectionError("redis down")

        cache_mod._epoch_client = _Broken()
        assert cache_mod._shared_epoch().isdigit()  # 退化为本地计数，不抛异常
        cache_mod.bump_shared_epoch()               # 也不应抛异常


class TestWithoutRedis:
    """Redis 不可用时退化为进程内失效 —— 单进程部署下依然正确。"""

    def test_local_epoch_still_invalidates(self, no_redis):
        calls = []

        @query_cache
        def f(q):
            calls.append(q)
            return len(calls)

        assert f("x") == 1
        assert f("x") == 1
        cache_mod.bump_shared_epoch()
        assert f("x") == 2, "没有 Redis 时，本进程内的失效也必须生效"

    def test_fallback_epoch_is_numeric(self, no_redis):
        assert cache_mod._shared_epoch().isdigit()
