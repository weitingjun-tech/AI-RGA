"""接口限流与登录失败锁定。

**为什么问答接口必须限流**
一次问答要跑嵌入 + 向量检索 + LLM 推理，是整条链路上最贵的操作。
不限流时，一个循环脚本就能把 GPU/CPU 占满，所有正常用户一起卡住——
这不是"理论风险"，是部署到公网后几小时内必然发生的事。

**为什么登录接口要单独限流**
不限流的话，攻击者可以对同一账号每秒尝试上千次密码。
配合 LOGIN_MAX_FAILURES 的账号锁定，把"暴力破解"的成本抬到不可行。

实现上不引入 slowapi 之类的依赖：固定窗口计数只需要 INCR + EXPIRE，
自己写反而更可控，也避免了为一个几十行的功能装一个包。
Redis 可用时用 Redis（多 worker 共享配额），否则退化为进程内计数。
"""
import logging
import threading
import time

from fastapi import Depends, HTTPException, Request, status

from app.config import RATE_LIMIT_ENABLED, REDIS_URL
from app.middleware.auth import get_current_user

logger = logging.getLogger("rag-app")

_PERIOD_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}


def parse_limit(spec: str) -> tuple[int, int]:
    """把 "30/minute" 解析成 (30, 60)。"""
    count_str, _, period = spec.partition("/")
    try:
        count = int(count_str)
        window = _PERIOD_SECONDS[period.strip().lower()]
    except (ValueError, KeyError):
        raise ValueError(f"限流配置格式错误: {spec!r}，应形如 '30/minute'")
    return count, window


# ---------------------------------------------------------------------------
# 计数器存储：Redis 优先，不可用时退化为进程内
# ---------------------------------------------------------------------------
class _MemoryStore:
    """进程内固定窗口计数器。

    仅适用于单进程部署；多 worker 时每个进程各算各的，实际配额会被放大 N 倍。
    因此它只是 Redis 不可用时的**降级方案**，不是等价替代。
    """

    def __init__(self) -> None:
        # key -> [计数, 窗口起始时间戳, 窗口长度]
        # 存窗口长度是为了 get() 时能判断是否已过期——没有它就只能返回陈旧计数，
        # 导致"锁定早已过期但用户仍被拒之门外"
        self._counters: dict[str, list] = {}
        self._lock = threading.Lock()

    def _entry(self, key: str, window: int) -> list:
        now = time.time()
        entry = self._counters.get(key)
        if entry is None or entry[1] <= now - entry[2]:
            entry = [0, now, window]
            self._counters[key] = entry
        return entry

    def incr(self, key: str, window: int) -> int:
        with self._lock:
            entry = self._entry(key, window)
            entry[0] += 1
            # 顺手清理已过期键，防止长期运行后字典无限膨胀
            if len(self._counters) > 10000:
                now = time.time()
                for k in [k for k, v in self._counters.items() if v[1] <= now - v[2]]:
                    self._counters.pop(k, None)
            return entry[0]

    def get(self, key: str) -> int:
        with self._lock:
            entry = self._counters.get(key)
            if entry is None:
                return 0
            if entry[1] <= time.time() - entry[2]:
                # 已过期，顺便清掉，避免下次误判
                self._counters.pop(key, None)
                return 0
            return entry[0]

    def delete(self, key: str) -> None:
        with self._lock:
            self._counters.pop(key, None)


class _RedisStore:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(
            url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
        )

    def incr(self, key: str, window: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)  # 只在键刚创建时设置过期
        return int(pipe.execute()[0])

    def get(self, key: str) -> int:
        value = self._client.get(key)
        return int(value) if value is not None else 0

    def delete(self, key: str) -> None:
        self._client.delete(key)


_store = None
_store_lock = threading.Lock()


def _get_store():
    """获取计数器存储，Redis 不可用时降级（只提示一次，避免刷屏）。"""
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is not None:
            return _store
        try:
            candidate = _RedisStore(REDIS_URL)
            candidate.incr("ratelimit:ping", 60)
            _store = candidate
            logger.info(f"限流使用 Redis 计数: {REDIS_URL}")
        except Exception as exc:
            _store = _MemoryStore()
            logger.warning(
                f"Redis 不可用（{exc}），限流降级为进程内计数。"
                "多 worker 部署时实际配额会被放大，生产环境请确保 Redis 可用。"
            )
    return _store


# ---------------------------------------------------------------------------
# 限流判定
# ---------------------------------------------------------------------------
def check_rate_limit(key: str, spec: str) -> None:
    """超限则抛 429。key 需调用方保证唯一（含作用域与身份）。"""
    if not RATE_LIMIT_ENABLED:
        return
    limit, window = parse_limit(spec)
    try:
        count = _get_store().incr(key, window)
    except Exception as exc:
        # 限流组件本身故障时放行，而不是把整个服务拒之门外。
        # 这是刻意的取舍：限流是保护措施，不该成为新的单点故障。
        logger.warning(f"限流计数失败，本次放行: {exc}")
        return

    if count > limit:
        retry_after = window
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"操作过于频繁，请在 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )


def client_ip(request: Request) -> str:
    """取客户端 IP。

    优先用 X-Forwarded-For 的第一段——反向代理后 request.client.host
    永远是代理的地址，按它限流等于给所有用户算同一个配额。
    注意：XFF 可被伪造，因此**只在可信代理后面**才应信任它。
    本项目的部署方式是 nginx 反代，属于可信场景。
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ip_rate_limit(scope: str, spec: str):
    """按客户端 IP 限流的依赖工厂，用于登录/注册这类还没有用户的接口。"""

    async def _dependency(request: Request) -> None:
        check_rate_limit(f"rl:{scope}:ip:{client_ip(request)}", spec)

    return _dependency


def user_rate_limit(scope: str, spec: str):
    """按登录用户限流的依赖工厂，用于问答/上传这类已认证的接口。"""

    async def _dependency(current_user=Depends(get_current_user)) -> None:
        check_rate_limit(f"rl:{scope}:user:{current_user.id}", spec)

    return _dependency


# ---------------------------------------------------------------------------
# 登录失败锁定
# ---------------------------------------------------------------------------
def _failure_key(username: str) -> str:
    return f"loginfail:{username.lower()}"


def is_account_locked(username: str, max_failures: int) -> bool:
    """账号是否因连续失败被锁定。"""
    if not RATE_LIMIT_ENABLED:
        return False
    try:
        return _get_store().get(_failure_key(username)) >= max_failures
    except Exception:
        # 计数组件故障时按"未锁定"处理：宁可放宽也不能把用户永久挡在门外
        return False


def record_login_failure(username: str, lockout_minutes: int) -> int:
    """记录一次登录失败，返回当前连续失败次数。

    计数窗口 = 锁定时长：只要在锁定时间内不再失败，计数会自动过期归零，
    不需要额外的解锁任务。
    """
    if not RATE_LIMIT_ENABLED:
        return 0
    try:
        return _get_store().incr(_failure_key(username), lockout_minutes * 60)
    except Exception:
        return 0


def clear_login_failures(username: str) -> None:
    """登录成功后清零失败计数。"""
    if not RATE_LIMIT_ENABLED:
        return
    try:
        _get_store().delete(_failure_key(username))
    except Exception:
        pass
