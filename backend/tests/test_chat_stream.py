"""问答接口的流式返回测试。

**这个文件是为了一个真实发生过的线上故障而写的。**

故障现象：回答能正常流式吐出来，但吐完之后前端收到一个 error 事件，
助手消息没能存进数据库。

根因：`StreamingResponse` 的生成器**在路由函数返回之后**才真正执行，
而此时依赖注入的收尾逻辑已经跑完、数据库会话已经关闭。
会话关闭会让其中所有 ORM 实例「过期 + 脱离」，此后哪怕只是读一下
`conv.id` 这种看起来很安全的属性，也会触发一次重新加载并抛
`Instance <Conversation> is not bound to a Session`。

**为什么这次特别值得记下来**：它取决于中途有没有 commit，以及有没有
恰好读过一次那个属性。每次 commit 都会让会话里的对象过期，只要在流式返回
之前恰好读过一次 `conv.id`，对象就被顺带刷新了，问题不出现。
换句话说——**代码"碰巧是对的"**。一旦调整中间语句的顺序
（当时只是挪动了一行"取历史"的位置），就会从"一直没事"变成"必现"。

所以这里的断言不是"能返回 200"，而是"**流里必须出现 done、不能出现 error**"。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.database import Base, get_db
from app.middleware.auth import get_current_user
from app.utils import rate_limit


@pytest.fixture
def sessions():
    """按**请求**发放会话，而不是所有请求共用一个。

    这一点很关键：生产里 `get_db` 每次请求都 `SessionLocal()` 拿一个新会话，
    并在请求结束时关闭它。如果测试里让多个请求共用同一个会话对象，
    第一个请求的 close 会污染第二个请求，测出来的失败是脚手架造的假象。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _parse_sse(text: str) -> list[dict]:
    """把 SSE 文本解析成事件列表。"""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@pytest.fixture
def chat_client(sessions, monkeypatch):
    from app.models.user import User

    setup = sessions()
    user = User(username="alice", password_hash="x", role="admin")
    setup.add(user)
    setup.commit()
    setup.refresh(user)
    user_id = user.id
    setup.close()

    monkeypatch.setattr(rate_limit, "_store", rate_limit._MemoryStore())
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(chat_api, "RATE_LIMIT_CHAT", "1000/minute")

    # 检索与改写都换成假的：这里要验的是**数据库会话的生命周期**，
    # 不是检索质量，不该把向量库和 LLM 拖进来
    monkeypatch.setattr(chat_api, "QUERY_REWRITE_ENABLED", False)
    monkeypatch.setattr(
        chat_api, "search_knowledge",
        lambda *a, **k: ("参考内容", [{"doc_name": "a.md"}], {"collection_names": [], "latency_ms": 1}),
    )

    async def _fake_stream(query, context, history):
        yield "这是"
        yield "回答"

    monkeypatch.setattr(chat_api, "generate_chat_stream", _fake_stream)

    # 用游离对象冒充当前用户：它不属于任何会话，正好符合生产里的实际情况
    # （认证依赖用完会话也会关掉），也避免测试去踩会话生命周期的边。
    fake_user = User(id=user_id, username="alice", password_hash="x", role="admin")

    app = FastAPI()
    app.include_router(chat_api.router)
    app.dependency_overrides[get_current_user] = lambda: fake_user

    def _override_db():
        # 刻意复刻生产里 get_db 的行为：每次请求新建会话，请求处理函数返回后关闭。
        # 少了 finally 里的 close，这个测试就抓不到任何东西。
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestStreamingCompletes:
    def test_stream_ends_with_done_not_error(self, chat_client):
        r = chat_client.post("/api/chat/send", json={"query": "你好"})

        assert r.status_code == 200
        events = _parse_sse(r.text)
        types = [e["type"] for e in events]

        assert "done" in types, f"流里没有 done 事件，实际事件序列: {types}"
        assert "error" not in types, (
            "流里出现了 error 事件，说明流式返回阶段访问了已脱离会话的 ORM 对象。"
            f"错误内容: {[e for e in events if e['type'] == 'error']}"
        )

    def test_chunks_are_delivered(self, chat_client):
        r = chat_client.post("/api/chat/send", json={"query": "你好"})
        chunks = [e["content"] for e in _parse_sse(r.text) if e["type"] == "chunk"]
        assert "".join(chunks) == "这是回答"

    def test_done_event_carries_conversation_id(self, chat_client):
        """done 事件里必须带上 conversation_id —— 前端靠它继续多轮对话。"""
        r = chat_client.post("/api/chat/send", json={"query": "你好"})
        done = next(e for e in _parse_sse(r.text) if e["type"] == "done")
        assert isinstance(done["conversation_id"], int)
        assert isinstance(done["message_id"], int)


class TestMessagesArePersisted:
    def test_assistant_message_is_saved_after_stream(self, chat_client, sessions):
        """流式返回结束后，助手消息必须落库。

        这正是当初失败的环节：生成器里保存消息时，会话已经关了。
        """
        from app.models.message import Message

        chat_client.post("/api/chat/send", json={"query": "你好"})

        with sessions() as s:
            roles = [m.role for m in s.query(Message).order_by(Message.id).all()]
        assert roles == ["user", "assistant"]

    def test_conversation_title_is_updated(self, chat_client, sessions):
        from app.models.conversation import Conversation

        chat_client.post("/api/chat/send", json={"query": "这是一句比较长的问题用来当标题"})

        with sessions() as s:
            conv = s.query(Conversation).first()
            assert conv is not None
            assert conv.title != "新会话", "助手消息保存后应当顺带把会话标题改掉"


class TestMultiTurn:
    def test_second_turn_reuses_conversation(self, chat_client, sessions):
        from app.models.conversation import Conversation

        first = chat_client.post("/api/chat/send", json={"query": "第一问"})
        conv_id = next(e for e in _parse_sse(first.text) if e["type"] == "done")["conversation_id"]

        second = chat_client.post("/api/chat/send", json={"query": "第二问", "conversation_id": conv_id})
        assert second.status_code == 200
        assert "error" not in [e["type"] for e in _parse_sse(second.text)]

        with sessions() as s:
            assert s.query(Conversation).count() == 1, "第二轮应当复用同一个会话，而不是新建"
