"""pytest 共享夹具。

**为什么用 SQLite 而不是连 MySQL**
单元测试要能在任何机器上、不依赖任何外部服务地跑起来（包括 CI）。
SQLite 内存库提供真实的 SQL 语义（真实的 WHERE / 唯一约束 / 外键），
比手写 Mock 更接近生产行为——尤其是权限过滤这种**靠 SQL 条件实现**的逻辑，
用 Mock 测等于什么都没测（Mock 会乖乖返回你让它返回的东西）。
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base  # noqa: E402

# 显式导入所有模型：SQLAlchemy 的 relationship 是按字符串名延迟解析的，
# 少导入一个模型，mapper 配置阶段就会报 "failed to locate a name"。
from app.models import (  # noqa: E402,F401
    audit_log,
    conversation,
    document,
    kb_permission,
    knowledge_base,
    message,
    retrieval_log,
    user,
)


@pytest.fixture
def db():
    """一个干净的 SQLite 内存库会话，每个测试独立。

    `StaticPool` 不是可选项，缺了它接口测试会莫名其妙地失败：
    SQLite 的内存库是**按连接**存在的，而 SQLAlchemy 默认给每个线程分配
    独立连接。FastAPI 又会把同步的 `def` 接口丢到线程池里执行——
    于是建表的线程和查表的线程各看各的库，表现为"表不存在"或"数据凭空消失"。
    StaticPool 让所有线程共用同一个连接，内存库才真的只有一份。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def make_user(db):
    """建一个用户并返回。role 默认 user。"""
    from app.models.user import User

    def _make(username: str = "alice", role: str = "user") -> User:
        u = User(username=username, password_hash="x", role=role)
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    return _make


@pytest.fixture
def make_kb(db):
    """建一个知识库并返回。"""
    from app.models.knowledge_base import KnowledgeBase

    def _make(name: str = "kb") -> KnowledgeBase:
        kb = KnowledgeBase(name=name, collection_name=f"col_{name}")
        db.add(kb)
        db.commit()
        db.refresh(kb)
        return kb

    return _make


@pytest.fixture
def grant(db):
    """给用户授予某个知识库的权限。"""
    from app.models.kb_permission import KbPermission

    def _grant(user_id: int, kb_id: int, permission: str = "read") -> KbPermission:
        p = KbPermission(user_id=user_id, kb_id=kb_id, permission=permission)
        db.add(p)
        db.commit()
        return p

    return _grant


@pytest.fixture(autouse=True)
def _acl_enabled_by_default(monkeypatch):
    """权限开关默认打开。

    `from app.config import KB_ACL_ENABLED` 是**按值导入**的，改环境变量不会生效，
    必须直接改模块属性，否则测试会静默地测到"关闭 ACL"的分支。
    """
    from app.services import permission_service

    monkeypatch.setattr(permission_service, "KB_ACL_ENABLED", True)


@pytest.fixture
def isolated_env(monkeypatch):
    """阻止测试读到开发机上的 .env —— 否则本地跑和 CI 跑结果会不一致。"""
    for key in ("JWT_SECRET", "APP_ENV"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def pytest_configure(config):
    # 让 `os.environ` 里可能的真实配置不影响测试
    os.environ.setdefault("APP_ENV", "development")
