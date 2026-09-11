"""接口限流与登录失败锁定测试。

限流是"保护措施"，但保护措施自己出故障时**不能变成新的单点故障**——
所以除了"该拦的拦住"，这里同样测"组件故障时要放行"。
"""
import time

import pytest
from fastapi import HTTPException

from app.utils import rate_limit
from app.utils.rate_limit import (
    _MemoryStore,
    check_rate_limit,
    parse_limit,
)


@pytest.fixture
def mem_store(monkeypatch):
    """把计数器换成进程内实现，避免测试依赖 Redis。"""
    store = _MemoryStore()
    monkeypatch.setattr(rate_limit, "_store", store)
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", True)
    return store


class TestParseLimit:
    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("30/minute", (30, 60)),
            ("5/hour", (5, 3600)),
            ("10/second", (10, 1)),
            ("100/day", (100, 86400)),
            ("  7 / hour ", (7, 3600)),
        ],
    )
    def test_valid_specs(self, spec, expected):
        assert parse_limit(spec) == expected

    @pytest.mark.parametrize("spec", ["30", "abc/minute", "30/fortnight", "/minute"])
    def test_invalid_specs_raise(self, spec):
        """配置写错要**立刻报错**，而不是静默地不限流——

        静默失败会让"我明明配了限流"变成一句空话，直到被打爆才发现。
        """
        with pytest.raises(ValueError):
            parse_limit(spec)


class TestMemoryStore:
    def test_counts_up(self):
        store = _MemoryStore()
        assert store.incr("k", 60) == 1
        assert store.incr("k", 60) == 2
        assert store.incr("k", 60) == 3

    def test_get_returns_current_count(self):
        store = _MemoryStore()
        store.incr("k", 60)
        store.incr("k", 60)
        assert store.get("k") == 2

    def test_get_unknown_key_is_zero(self):
        assert _MemoryStore().get("nope") == 0

    def test_delete_resets(self):
        store = _MemoryStore()
        store.incr("k", 60)
        store.delete("k")
        assert store.get("k") == 0
        assert store.incr("k", 60) == 1

    def test_keys_are_independent(self):
        store = _MemoryStore()
        store.incr("a", 60)
        store.incr("a", 60)
        store.incr("b", 60)
        assert store.get("a") == 2
        assert store.get("b") == 1

    def test_expired_window_reads_as_zero(self):
        """窗口过期后必须读回 0。

        曾经的写法没有记录窗口长度，`get()` 只能返回陈旧计数，
        表现为「锁定时间早就过了，用户却依然被挡在门外」。
        """
        store = _MemoryStore()
        store._counters["k"] = [5, time.time() - 120, 60]  # 2 分钟前的 1 分钟窗口
        assert store.get("k") == 0

    def test_expired_window_restarts_counting(self):
        store = _MemoryStore()
        store._counters["k"] = [5, time.time() - 120, 60]
        assert store.incr("k", 60) == 1

    def test_stale_keys_are_garbage_collected(self):
        """长期运行不能把过期键一直留在字典里（内存会无限增长）。"""
        store = _MemoryStore()
        for i in range(10001):
            store.incr(f"expired-{i}", 60)
        for i in range(10001):
            store._counters[f"expired-{i}"][1] = time.time() - 120
        store.incr("trigger", 60)  # 触发一次清理
        assert len(store._counters) < 10000


class TestCheckRateLimit:
    def test_allows_up_to_the_limit(self, mem_store):
        for _ in range(3):
            check_rate_limit("k", "3/minute")

    def test_blocks_over_the_limit(self, mem_store):
        for _ in range(3):
            check_rate_limit("k", "3/minute")
        with pytest.raises(HTTPException) as exc:
            check_rate_limit("k", "3/minute")

        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers, (
            "429 必须带 Retry-After 头，客户端才知道该等多久再重试"
        )

    def test_different_keys_have_separate_quotas(self, mem_store):
        check_rate_limit("user:1", "1/minute")
        check_rate_limit("user:2", "1/minute")  # 不应因为 user:1 用满而失败

    def test_disabled_means_always_allowed(self, mem_store, monkeypatch):
        monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", False)
        for _ in range(100):
            check_rate_limit("k", "1/minute")

    def test_failure_of_store_lets_request_through(self, monkeypatch):
        """计数组件故障时放行，而不是拒绝服务。

        刻意的取舍：限流是保护措施，不该成为新的单点故障。
        """

        class _BrokenStore:
            def incr(self, *_a, **_kw):
                raise ConnectionError("redis is down")

        monkeypatch.setattr(rate_limit, "_store", _BrokenStore())
        monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", True)

        check_rate_limit("k", "1/minute")  # 不应抛异常


class TestLoginLockout:
    def test_not_locked_initially(self, mem_store):
        assert rate_limit.is_account_locked("alice", max_failures=5) is False

    def test_locked_after_threshold(self, mem_store):
        for _ in range(4):
            rate_limit.record_login_failure("alice", lockout_minutes=15)
        assert rate_limit.is_account_locked("alice", 5) is False

        rate_limit.record_login_failure("alice", lockout_minutes=15)
        assert rate_limit.is_account_locked("alice", 5) is True

    def test_successful_login_clears_counter(self, mem_store):
        for _ in range(5):
            rate_limit.record_login_failure("alice", lockout_minutes=15)
        rate_limit.clear_login_failures("alice")
        assert rate_limit.is_account_locked("alice", 5) is False

    def test_lockout_does_not_affect_other_accounts(self, mem_store):
        for _ in range(5):
            rate_limit.record_login_failure("alice", lockout_minutes=15)
        assert rate_limit.is_account_locked("bob", 5) is False

    def test_username_is_case_insensitive(self, mem_store):
        """按小写归并，否则换个大小写就能绕开锁定继续爆破。"""
        for _ in range(5):
            rate_limit.record_login_failure("Alice", lockout_minutes=15)
        assert rate_limit.is_account_locked("alice", 5) is True

    def test_lockout_expires_with_the_counting_window(self, mem_store):
        """计数窗口 = 锁定时间，因此不需要单独的解锁任务。"""
        for _ in range(5):
            rate_limit.record_login_failure("alice", lockout_minutes=15)
        mem_store._counters["loginfail:alice"][1] = time.time() - 16 * 60
        assert rate_limit.is_account_locked("alice", 5) is False
