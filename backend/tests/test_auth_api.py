"""认证接口测试（走完整的 HTTP 路径）。

**为什么要在单元测试之外再做一层接口测试**
`test_rate_limit.py` 已经验证了"连续失败 5 次会被锁定"这个逻辑本身，
但那只证明了函数是对的。这里要证明的是**接线是对的**：
依赖注入有没有真的生效、锁定检查是在验密码**之前**还是之后、
中间件有没有正确解析 token——这些只有走完整请求才能验证。

用独立的 FastAPI 实例挂载 router，而不是 `app.main:app`：
后者的启动钩子会执行数据库迁移和任务对账，测试不该有这些副作用。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.database import get_db
from app.services.auth_service import seed_admin
from app.utils import rate_limit

PASSWORD = "123456"


@pytest.fixture
def client(db, monkeypatch):
    # 限流计数换成进程内实现，测试不依赖 Redis
    monkeypatch.setattr(rate_limit, "_store", rate_limit._MemoryStore())
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", True)
    # 把登录限流放宽：这些用例测的是"账号锁定"，不是"IP 限流"，
    # 默认 10/minute 会先于锁定逻辑触发，让断言变得含糊
    monkeypatch.setattr(auth_api, "RATE_LIMIT_LOGIN", "1000/minute")
    monkeypatch.setattr(auth_api, "RATE_LIMIT_REGISTER", "1000/minute")

    app = FastAPI()
    app.include_router(auth_api.router)
    app.dependency_overrides[get_db] = lambda: db

    # raise_server_exceptions=False：让未捕获异常也走真实的 500 响应，
    # 而不是在测试里直接抛出。这样"本该 422 却变成 500"的问题才会被测出来。
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def admin(db):
    seed_admin(db)
    return "admin"


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


class TestRegister:
    def test_register_returns_tokens(self, client):
        r = client.post(
            "/api/auth/register", json={"username": "alice", "password": PASSWORD}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "alice"
        assert body["access_token"] and body["refresh_token"]

    def test_register_defaults_to_non_admin_role(self, client):
        """注册接口**不能**让调用方指定角色，否则就是一条提权路径。"""
        r = client.post(
            "/api/auth/register",
            json={"username": "bob", "password": PASSWORD, "role": "admin"},
        )
        assert r.json()["role"] == "user"

    def test_duplicate_username_is_rejected(self, client):
        client.post("/api/auth/register", json={"username": "alice", "password": PASSWORD})
        r = client.post("/api/auth/register", json={"username": "alice", "password": PASSWORD})
        assert r.status_code == 409

    def test_short_password_is_rejected(self, client):
        r = client.post("/api/auth/register", json={"username": "alice", "password": "123"})
        assert r.status_code == 422


class TestPasswordByteLimit:
    """bcrypt 只吃前 72 个**字节**，超了会抛 ValueError。

    修复前：这里会返回 500（服务端异常，用户看到"服务器错误"，无从下手）。
    修复后：返回 422 并给出可读提示。

    坑点在于长度限制是**字节**不是字符——一个汉字 3 字节，
    只写 max_length=100（字符）挡不住 25 个汉字的密码。
    """

    def test_ascii_password_at_byte_limit_is_accepted(self, client):
        r = client.post("/api/auth/register", json={"username": "alice", "password": "a" * 72})
        assert r.status_code == 200

    def test_ascii_password_over_byte_limit_is_422_not_500(self, client):
        r = client.post("/api/auth/register", json={"username": "alice", "password": "a" * 73})
        assert r.status_code == 422, "超长密码应当是校验失败（422），不能是服务端错误（500）"

    def test_chinese_password_over_byte_limit_is_rejected(self, client):
        """25 个汉字 = 75 字节 > 72。这类密码完全合法，只是超了 bcrypt 的字节上限。"""
        pw = "中" * 25
        assert len(pw) <= 100, "字符数在 max_length 之内，只靠字符限制挡不住"
        assert len(pw.encode("utf-8")) > 72

        r = client.post("/api/auth/register", json={"username": "alice", "password": pw})
        assert r.status_code == 422
        assert "字节" in r.text, "错误提示要说清楚是字节超限，否则用户只会觉得莫名其妙"

    def test_chinese_password_within_limit_is_accepted(self, client):
        r = client.post("/api/auth/register", json={"username": "alice", "password": "中" * 20})
        assert r.status_code == 200

    def test_change_password_also_checks_byte_limit(self, client):
        """改密码走的是另一个 Schema，容易漏掉同样的校验。"""
        client.post("/api/auth/register", json={"username": "alice", "password": PASSWORD})
        token = _login(client, "alice", PASSWORD).json()["access_token"]

        r = client.post(
            "/api/auth/change-password",
            json={"old_password": PASSWORD, "new_password": "中" * 25},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 422


class TestLogin:
    def test_login_success(self, client, admin):
        r = _login(client, "admin", PASSWORD)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_login_is_case_sensitive_for_password(self, client, admin):
        assert _login(client, "admin", "123456 ").status_code == 401

    def test_wrong_password_returns_401(self, client, admin):
        assert _login(client, "admin", "wrong-password").status_code == 401

    def test_unknown_user_returns_same_401_as_wrong_password(self, client):
        """两种情况返回相同的响应，避免通过错误信息枚举出有哪些用户存在。"""
        r = _login(client, "no-such-user", "whatever")
        assert r.status_code == 401
        assert r.json()["detail"] == _login(client, "admin", "wrong").json()["detail"]


class TestAccountLockout:
    """账号锁定：挡住"多 IP 撞库同一账号"，与 IP 限流互补。"""

    def test_locked_after_max_failures(self, client, admin):
        for i in range(5):
            r = _login(client, "admin", "wrong")
            assert r.status_code == 401, f"第 {i + 1} 次失败应当是 401"

        assert _login(client, "admin", "wrong").status_code == 429

    def test_lockout_blocks_the_correct_password_too(self, client, admin):
        """**这条是锁定的核心**：锁定期间即使密码正确也必须拒绝。

        如果正确密码能"解锁"，那么攻击者只要猜对一次就继续有 5 次机会，
        锁定就形同虚设。
        """
        for _ in range(5):
            _login(client, "admin", "wrong")

        assert _login(client, "admin", PASSWORD).status_code == 429

    def test_lockout_is_per_account(self, client, admin):
        client.post("/api/auth/register", json={"username": "alice", "password": PASSWORD})
        for _ in range(5):
            _login(client, "admin", "wrong")

        assert _login(client, "alice", PASSWORD).status_code == 200, "锁定不应影响其他账号"

    def test_successful_login_resets_the_counter(self, client, admin):
        for _ in range(4):
            _login(client, "admin", "wrong")

        assert _login(client, "admin", PASSWORD).status_code == 200
        # 计数已清零，所以这里应当重新拥有完整的 5 次机会
        for _ in range(4):
            assert _login(client, "admin", "wrong").status_code == 401
        assert _login(client, "admin", PASSWORD).status_code == 200


class TestMeEndpoint:
    def test_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_rejects_garbage_token(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert r.status_code == 401

    def test_returns_current_user(self, client, admin):
        token = _login(client, "admin", PASSWORD).json()["access_token"]
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["username"] == "admin"

    def test_refresh_token_is_not_accepted_as_access_token(self, client, admin):
        """两种 token 用途必须分离：refresh 有效期 7 天，若能当 access 用，
        等于把会话时长直接放大到 7 天。"""
        refresh = _login(client, "admin", PASSWORD).json()["refresh_token"]
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh}"})
        assert r.status_code == 401


class TestChangePassword:
    def test_wrong_old_password_is_rejected(self, client, admin):
        token = _login(client, "admin", PASSWORD).json()["access_token"]
        r = client.post(
            "/api/auth/change-password",
            json={"old_password": "wrong", "new_password": "newpass123"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400

    def test_password_actually_changes(self, client, admin):
        token = _login(client, "admin", PASSWORD).json()["access_token"]
        r = client.post(
            "/api/auth/change-password",
            json={"old_password": PASSWORD, "new_password": "newpass123"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        assert _login(client, "admin", PASSWORD).status_code == 401
        assert _login(client, "admin", "newpass123").status_code == 200

    def test_requires_authentication(self, client):
        r = client.post(
            "/api/auth/change-password",
            json={"old_password": PASSWORD, "new_password": "newpass123"},
        )
        assert r.status_code == 401


class TestRefresh:
    def test_refresh_issues_new_access_token(self, client, admin):
        refresh = _login(client, "admin", PASSWORD).json()["refresh_token"]
        r = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 200

        me = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
        )
        assert me.status_code == 200

    def test_access_token_cannot_be_used_to_refresh(self, client, admin):
        access = _login(client, "admin", PASSWORD).json()["access_token"]
        assert client.post("/api/auth/refresh", json={"refresh_token": access}).status_code == 401

    def test_invalid_refresh_token_is_rejected(self, client):
        r = client.post("/api/auth/refresh", json={"refresh_token": "garbage-token-value"})
        assert r.status_code == 401


class TestAuditTrail:
    def test_login_is_recorded(self, client, db, admin):
        """审计日志是合规要求：出事时要能回答"谁在什么时候登录过"。"""
        from app.models.audit_log import AuditLog

        _login(client, "admin", PASSWORD)

        actions = [row.action for row in db.query(AuditLog).all()]
        assert "auth.login" in actions

    def test_failed_login_is_recorded_with_submitted_username(self, client, db, admin):
        """登录失败时数据库里没有对应的用户对象，只能记**提交上来的**用户名——
        否则这条日志等于没写，事后查不出有人在爆破哪个账号。
        """
        from app.models.audit_log import AuditLog

        _login(client, "admin", "wrong")

        row = db.query(AuditLog).filter(AuditLog.action == "auth.login_failed").first()
        assert row is not None
        assert "admin" in str(row.detail)
        assert row.status == "failure"
