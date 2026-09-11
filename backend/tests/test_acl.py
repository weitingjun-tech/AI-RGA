"""知识库访问控制（ACL）测试。

这是整个测试体系里**最不能省**的一组：它守护的是一条安全边界，
逻辑写错的后果不是"功能不好用"，而是"机密内容泄露给不该看的人"。

其中 `TestNoPermissionMeansNothing` 是针对一个**真实存在过的越权漏洞**的回归测试：
原实现 `collection_names or list_collection_names()` 把"空列表"当成了 falsy，
于是"什么权限都没有"被解释成了"那就检索全部知识库"——
**过滤器反转成了授权器**。
"""
import pytest
from fastapi import HTTPException

from app.services.permission_service import (
    can_access_kb,
    get_accessible_kb_ids,
    require_kb_access,
    resolve_query_kb_ids,
)


class TestAccessibleKbIds:
    def test_admin_is_unrestricted(self, db, make_user):
        admin = make_user("root", role="admin")
        assert get_accessible_kb_ids(db, admin) is None, (
            "管理员必须返回 None（不受限），而不是全部 ID 的集合——"
            "两者的区别在于「以后新建的知识库」是否自动可见"
        )

    def test_acl_disabled_means_unrestricted(self, db, make_user, monkeypatch):
        from app.services import permission_service

        monkeypatch.setattr(permission_service, "KB_ACL_ENABLED", False)
        plain = make_user("bob")
        assert get_accessible_kb_ids(db, plain) is None

    def test_returns_only_granted_ids(self, db, make_user, make_kb, grant):
        user = make_user("alice")
        kb1, kb2, kb3 = make_kb("a"), make_kb("b"), make_kb("c")
        grant(user.id, kb1.id)
        grant(user.id, kb2.id)

        assert get_accessible_kb_ids(db, user) == {kb1.id, kb2.id}
        assert kb3.id not in get_accessible_kb_ids(db, user)

    def test_no_grant_returns_empty_set_not_none(self, db, make_user):
        """空集合和 None 是两回事，这是本模块最关键的一条不变式。"""
        user = make_user("carol")
        result = get_accessible_kb_ids(db, user)
        assert result == set()
        assert result is not None, (
            "空权限必须是「空的集合」而不能退化成 None——"
            "None 在调用方的语义是「不受限」，等于把没权限的人提升成管理员"
        )

    def test_need_write_filters_to_write_grants(self, db, make_user, make_kb, grant):
        user = make_user("dave")
        ro, rw = make_kb("ro"), make_kb("rw")
        grant(user.id, ro.id, permission="read")
        grant(user.id, rw.id, permission="write")

        assert get_accessible_kb_ids(db, user, need_write=True) == {rw.id}
        assert get_accessible_kb_ids(db, user, need_write=False) == {ro.id, rw.id}

    def test_other_users_grants_do_not_leak(self, db, make_user, make_kb, grant):
        alice = make_user("alice")
        bob = make_user("bob")
        kb = make_kb("secret")
        grant(alice.id, kb.id)

        assert get_accessible_kb_ids(db, bob) == set()


class TestCanAccessKb:
    def test_admin_can_access_anything(self, db, make_user):
        admin = make_user("root", role="admin")
        assert can_access_kb(db, admin, kb_id=99999) is True

    def test_user_with_grant(self, db, make_user, make_kb, grant):
        user = make_user("alice")
        kb = make_kb("a")
        grant(user.id, kb.id)
        assert can_access_kb(db, user, kb.id) is True

    def test_user_without_grant(self, db, make_user, make_kb):
        user = make_user("alice")
        kb = make_kb("a")
        assert can_access_kb(db, user, kb.id) is False

    def test_write_permission_required_for_write(self, db, make_user, make_kb, grant):
        user = make_user("alice")
        kb = make_kb("a")
        grant(user.id, kb.id, permission="read")

        assert can_access_kb(db, user, kb.id, need_write=False) is True
        assert can_access_kb(db, user, kb.id, need_write=True) is False


class TestRequireKbAccess:
    def test_raises_403_without_permission(self, db, make_user, make_kb):
        user = make_user("alice")
        kb = make_kb("a")
        with pytest.raises(HTTPException) as exc:
            require_kb_access(db, user, kb.id)
        assert exc.value.status_code == 403

    def test_passes_with_permission(self, db, make_user, make_kb, grant):
        user = make_user("alice")
        kb = make_kb("a")
        grant(user.id, kb.id)
        require_kb_access(db, user, kb.id)  # 不应抛异常


class TestResolveQueryKbIds:
    def test_admin_none_means_all(self, db, make_user):
        """管理员不传 kb_ids → 返回空列表，上层据此检索"全部"。"""
        admin = make_user("root", role="admin")
        assert resolve_query_kb_ids(db, admin, None) == []

    def test_admin_explicit_request_passes_through(self, db, make_user):
        admin = make_user("root", role="admin")
        assert resolve_query_kb_ids(db, admin, [3, 1]) == [3, 1]

    def test_user_none_expands_to_own_grants(self, db, make_user, make_kb, grant):
        user = make_user("alice")
        kb1, kb2 = make_kb("a"), make_kb("b")
        grant(user.id, kb1.id)
        grant(user.id, kb2.id)

        assert resolve_query_kb_ids(db, user, None) == sorted({kb1.id, kb2.id})

    def test_unauthorized_ids_are_removed_silently(self, db, make_user, make_kb, grant):
        """请求里混了无权限的库：剔除但不报错。

        报错等于告诉对方"存在一个你访问不了的知识库"，会泄露知识库的存在性。
        """
        user = make_user("alice")
        mine, others = make_kb("mine"), make_kb("others")
        grant(user.id, mine.id)

        assert resolve_query_kb_ids(db, user, [mine.id, others.id]) == [mine.id]

    def test_entirely_unauthorized_request_returns_empty(self, db, make_user, make_kb):
        user = make_user("alice")
        kb = make_kb("secret")
        assert resolve_query_kb_ids(db, user, [kb.id]) == []


class TestNoPermissionMeansNothing:
    """越权漏洞回归测试 —— 这组测试的存在本身就是修复的一部分。

    漏洞成因：空集合是 falsy 的，`x or y` 会把"没有权限"变成"那就全都检索"。
    只要有人把 `is None` 判断改回 `or`，这组测试必须立刻变红。
    """

    def test_none_request_with_no_grants_returns_empty(self, db, make_user):
        user = make_user("nobody")
        result = resolve_query_kb_ids(db, user, None)
        assert result == [], (
            "无任何授权的用户请求「全部知识库」，必须得到空列表。"
            "若这里返回 ['*'] 或全部 collection 名，就是权限绕过。"
        )

    def test_explicit_request_with_no_grants_returns_empty(
        self, db, make_user, make_kb
    ):
        user = make_user("nobody")
        kb = make_kb("secret")
        assert resolve_query_kb_ids(db, user, [kb.id]) == []

    def test_empty_request_is_not_a_wildcard(self, db, make_user, make_kb, grant):
        """传空 list 与传 None 都表示"我全部可访问的"，但都**不得超出授权范围**。"""
        user = make_user("alice")
        mine = make_kb("mine")
        other = make_kb("other")
        grant(user.id, mine.id)

        for requested in (None, []):
            resolved = resolve_query_kb_ids(db, user, requested)
            assert other.id not in resolved, (
                f"requested={requested!r} 时越权拿到了未授权的知识库"
            )
            assert resolved == [mine.id]
