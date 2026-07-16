import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import time
import pytest
import pytest_asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeDB:
    def __init__(self):
        self._d = {}
    def get(self, owner, key, default=None):
        return self._d.get(owner, {}).get(key, default)
    async def set(self, owner, key, value):
        self._d.setdefault(owner, {})[key] = value
        return True
def _msg(sender_id=None, chat_id=None):
    return SimpleNamespace(sender_id=sender_id, chat_id=chat_id)
def _client(me_id=1000):
    c = MagicMock()
    c.tg_me = None
    c.tg_id = None
    c.get_me = AsyncMock(return_value=SimpleNamespace(id=me_id))
    c.get_permissions = AsyncMock()
    return c
@pytest_asyncio.fixture
async def manager():
    from kitsune.core.security import SecurityManager
    db = _FakeDB()
    cl = _client(me_id=1000)
    mgr = SecurityManager(cl, db)
    await mgr.init()
    return mgr
def test_bitmap_constants_unique():
    from kitsune.core import security as sec
    bits = [sec.OWNER, sec.SUDO, sec.SUPPORT, sec.GROUP_OWNER,
            sec.GROUP_ADMIN_ADD_ADMINS, sec.GROUP_ADMIN_CHANGE_INFO,
            sec.GROUP_ADMIN_BAN_USERS, sec.GROUP_ADMIN_DELETE_MSGS,
            sec.GROUP_ADMIN_PIN_MESSAGES, sec.GROUP_ADMIN_INVITE_USERS,
            sec.GROUP_ADMIN, sec.GROUP_MEMBER, sec.PM, sec.EVERYONE]
    assert len(set(bits)) == len(bits)
    for b in bits:
        assert b > 0
        assert (b & (b - 1)) == 0
def test_bitmap_dict_populated():
    from kitsune.core import security as sec
    assert "OWNER" in sec.BITMAP
    assert sec.BITMAP["OWNER"] == sec.OWNER
    assert "SUDO" in sec.BITMAP
    assert "EVERYONE" in sec.BITMAP
def test_group_admin_any_includes_all():
    from kitsune.core import security as sec
    expected = (
        sec.GROUP_ADMIN_ADD_ADMINS | sec.GROUP_ADMIN_CHANGE_INFO
        | sec.GROUP_ADMIN_BAN_USERS | sec.GROUP_ADMIN_DELETE_MSGS
        | sec.GROUP_ADMIN_PIN_MESSAGES | sec.GROUP_ADMIN_INVITE_USERS
        | sec.GROUP_ADMIN
    )
    assert sec.GROUP_ADMIN_ANY == expected
def test_default_permissions_is_owner():
    from kitsune.core import security as sec
    assert sec.DEFAULT_PERMISSIONS == sec.OWNER
@pytest.mark.asyncio
async def test_owner_can_pass_owner_check(manager):
    from kitsune.core.security import OWNER
    msg = _msg(sender_id=1000, chat_id=1000)
    assert await manager.check(msg, OWNER) is True
@pytest.mark.asyncio
async def test_non_owner_fails_owner_check(manager):
    from kitsune.core.security import OWNER
    msg = _msg(sender_id=2000, chat_id=2000)
    assert await manager.check(msg, OWNER) is False
@pytest.mark.asyncio
async def test_owner_implies_pm_in_private_chat(manager):
    from kitsune.core.security import OWNER, PM, EVERYONE
    msg = _msg(sender_id=1000, chat_id=1000)
    assert await manager.check(msg, OWNER) is True
@pytest.mark.asyncio
async def test_co_owner_resolved_as_owner(manager):
    from kitsune.core.security import OWNER
    await manager._db.set("kitsune.security", "co_owners", [555])
    msg = _msg(sender_id=555, chat_id=555)
    assert await manager.check(msg, OWNER) is True
@pytest.mark.asyncio
async def test_none_sender_id_returns_false(manager):
    from kitsune.core.security import OWNER
    msg = _msg(sender_id=None, chat_id=1)
    assert await manager.check(msg, OWNER) is False
@pytest.mark.asyncio
async def test_get_sudo_users_default_empty(manager):
    assert manager.get_sudo_users() == []
@pytest.mark.asyncio
async def test_add_sudo(manager):
    await manager.add_sudo(123)
    assert 123 in manager.get_sudo_users()
@pytest.mark.asyncio
async def test_add_sudo_idempotent(manager):
    await manager.add_sudo(123)
    await manager.add_sudo(123)
    sudo = manager.get_sudo_users()
    assert sudo.count(123) == 1
@pytest.mark.asyncio
async def test_add_multiple_sudo(manager):
    await manager.add_sudo(111)
    await manager.add_sudo(222)
    await manager.add_sudo(333)
    sudo = manager.get_sudo_users()
    assert {111, 222, 333}.issubset(set(sudo))
@pytest.mark.asyncio
async def test_remove_sudo(manager):
    await manager.add_sudo(123)
    await manager.add_sudo(456)
    await manager.remove_sudo(123)
    sudo = manager.get_sudo_users()
    assert 123 not in sudo
    assert 456 in sudo
@pytest.mark.asyncio
async def test_remove_nonexistent_sudo_safe(manager):
    await manager.remove_sudo(99999)
    assert manager.get_sudo_users() == []
@pytest.mark.asyncio
async def test_sudo_user_check_passes(manager):
    from kitsune.core.security import SUDO
    await manager.add_sudo(777)
    msg = _msg(sender_id=777, chat_id=999)
    manager._client.get_permissions = AsyncMock(side_effect=Exception("not a participant"))
    assert await manager.check(msg, SUDO) is True
@pytest.mark.asyncio
async def test_support_user_check_passes(manager):
    from kitsune.core.security import SUPPORT
    await manager._db.set("kitsune.security", "support", [888])
    msg = _msg(sender_id=888, chat_id=999)
    manager._client.get_permissions = AsyncMock(side_effect=Exception("nope"))
    assert await manager.check(msg, SUPPORT) is True
@pytest.mark.asyncio
async def test_get_support_users_default(manager):
    assert manager.get_support_users() == []
@pytest.mark.asyncio
async def test_pm_bit_set_in_private_chat(manager):
    from kitsune.core.security import PM
    msg = _msg(sender_id=2000, chat_id=2000)
    assert await manager.check(msg, PM) is True
@pytest.mark.asyncio
async def test_pm_bit_not_set_in_group(manager):
    from kitsune.core.security import PM
    manager._client.get_permissions = AsyncMock(side_effect=Exception("anything"))
    msg = _msg(sender_id=2000, chat_id=-100123)
    assert await manager.check(msg, PM) is False
@pytest.mark.asyncio
async def test_everyone_bit_always_set_with_chat(manager):
    from kitsune.core.security import EVERYONE
    msg = _msg(sender_id=2000, chat_id=2000)
    assert await manager.check(msg, EVERYONE) is True
@pytest.mark.asyncio
async def test_group_creator_gets_owner_bit(manager):
    from kitsune.core.security import GROUP_OWNER, GROUP_MEMBER
    perm = SimpleNamespace(is_creator=True, is_admin=False, banned_rights=None, admin_rights=None)
    manager._client.get_permissions = AsyncMock(return_value=perm)
    msg = _msg(sender_id=2000, chat_id=-100999)
    assert await manager.check(msg, GROUP_OWNER) is True
    assert await manager.check(msg, GROUP_MEMBER) is True
@pytest.mark.asyncio
async def test_group_admin_with_rights(manager):
    from kitsune.core.security import (
        GROUP_ADMIN, GROUP_ADMIN_BAN_USERS, GROUP_ADMIN_PIN_MESSAGES
    )
    rights = SimpleNamespace(
        add_admins=False, change_info=False, ban_users=True,
        delete_messages=False, pin_messages=True, invite_users=False
    )
    perm = SimpleNamespace(is_creator=False, is_admin=True,
                           banned_rights=None, admin_rights=rights)
    manager._client.get_permissions = AsyncMock(return_value=perm)
    msg = _msg(sender_id=3000, chat_id=-100888)
    assert await manager.check(msg, GROUP_ADMIN) is True
    assert await manager.check(msg, GROUP_ADMIN_BAN_USERS) is True
    assert await manager.check(msg, GROUP_ADMIN_PIN_MESSAGES) is True
@pytest.mark.asyncio
async def test_regular_group_member(manager):
    from kitsune.core.security import GROUP_MEMBER, GROUP_ADMIN
    perm = SimpleNamespace(is_creator=False, is_admin=False,
                           banned_rights=None, admin_rights=None)
    manager._client.get_permissions = AsyncMock(return_value=perm)
    msg = _msg(sender_id=4000, chat_id=-100777)
    assert await manager.check(msg, GROUP_MEMBER) is True
    assert await manager.check(msg, GROUP_ADMIN) is False
@pytest.mark.asyncio
async def test_get_permissions_exception_returns_member_only(manager):
    from kitsune.core.security import GROUP_MEMBER, GROUP_ADMIN
    manager._client.get_permissions = AsyncMock(side_effect=Exception("api error"))
    msg = _msg(sender_id=5000, chat_id=-100666)
    assert await manager.check(msg, GROUP_MEMBER) is True
    assert await manager.check(msg, GROUP_ADMIN) is False
@pytest.mark.asyncio
async def test_cache_populated_after_check(manager):
    from kitsune.core.security import GROUP_MEMBER
    perm = SimpleNamespace(is_creator=False, is_admin=False,
                           banned_rights=None, admin_rights=None)
    manager._client.get_permissions = AsyncMock(return_value=perm)
    msg = _msg(sender_id=6000, chat_id=-100555)
    await manager.check(msg, GROUP_MEMBER)
    assert (-100555, 6000) in manager._cache
@pytest.mark.asyncio
async def test_cache_hit_avoids_second_call(manager):
    from kitsune.core.security import GROUP_MEMBER
    perm = SimpleNamespace(is_creator=False, is_admin=False,
                           banned_rights=None, admin_rights=None)
    mock_perm = AsyncMock(return_value=perm)
    manager._client.get_permissions = mock_perm
    msg = _msg(sender_id=7000, chat_id=-100444)
    await manager.check(msg, GROUP_MEMBER)
    await manager.check(msg, GROUP_MEMBER)
    await manager.check(msg, GROUP_MEMBER)
    assert mock_perm.call_count == 1
@pytest.mark.asyncio
async def test_invalidate_cache_clears_all(manager):
    from kitsune.core.security import GROUP_MEMBER
    perm = SimpleNamespace(is_creator=False, is_admin=False,
                           banned_rights=None, admin_rights=None)
    manager._client.get_permissions = AsyncMock(return_value=perm)
    msg1 = _msg(sender_id=8000, chat_id=-100333)
    msg2 = _msg(sender_id=9000, chat_id=-100222)
    await manager.check(msg1, GROUP_MEMBER)
    await manager.check(msg2, GROUP_MEMBER)
    assert len(manager._cache) >= 2
    manager.invalidate_cache()
    assert len(manager._cache) == 0
@pytest.mark.asyncio
async def test_invalidate_cache_specific_chat(manager):
    from kitsune.core.security import GROUP_MEMBER
    perm = SimpleNamespace(is_creator=False, is_admin=False,
                           banned_rights=None, admin_rights=None)
    manager._client.get_permissions = AsyncMock(return_value=perm)
    msg_a = _msg(sender_id=10001, chat_id=-1001)
    msg_b = _msg(sender_id=10002, chat_id=-1002)
    await manager.check(msg_a, GROUP_MEMBER)
    await manager.check(msg_b, GROUP_MEMBER)
    assert (-1001, 10001) in manager._cache
    assert (-1002, 10002) in manager._cache
    manager.invalidate_cache(chat_id=-1001)
    assert (-1001, 10001) not in manager._cache
    assert (-1002, 10002) in manager._cache
@pytest.mark.asyncio
async def test_cache_expires_after_ttl(manager, monkeypatch):
    from kitsune.core import security as sec
    from kitsune.core.security import GROUP_MEMBER
    monkeypatch.setattr(sec, "_CACHE_TTL", 0.05)
    perm = SimpleNamespace(is_creator=False, is_admin=False,
                           banned_rights=None, admin_rights=None)
    mock_perm = AsyncMock(return_value=perm)
    manager._client.get_permissions = mock_perm
    msg = _msg(sender_id=11000, chat_id=-1001111)
    await manager.check(msg, GROUP_MEMBER)
    await asyncio.sleep(0.1)
    await manager.check(msg, GROUP_MEMBER)
    assert mock_perm.call_count == 2
@pytest.mark.asyncio
async def test_init_loads_me():
    from kitsune.core.security import SecurityManager
    db = _FakeDB()
    cl = _client(me_id=42)
    mgr = SecurityManager(cl, db)
    assert mgr._me is None
    await mgr.init()
    assert mgr._me is not None
    assert mgr._me.id == 42
@pytest.mark.asyncio
async def test_check_lazy_inits_me():
    from kitsune.core.security import SecurityManager, OWNER
    db = _FakeDB()
    cl = _client(me_id=42)
    mgr = SecurityManager(cl, db)
    assert mgr._me is None
    msg = _msg(sender_id=42, chat_id=42)
    result = await mgr.check(msg, OWNER)
    assert result is True
    assert mgr._me is not None
@pytest.mark.asyncio
async def test_check_with_combined_required(manager):
    from kitsune.core.security import OWNER, SUDO
    msg = _msg(sender_id=1000, chat_id=1000)
    assert await manager.check(msg, OWNER | SUDO) is True
@pytest.mark.asyncio
async def test_persistent_sudo_across_instances(tmp_path):
    from kitsune.core.security import SecurityManager, SUDO
    db = _FakeDB()
    cl = _client(me_id=1)
    mgr1 = SecurityManager(cl, db)
    await mgr1.init()
    await mgr1.add_sudo(12345)
    mgr2 = SecurityManager(cl, db)
    await mgr2.init()
    assert 12345 in mgr2.get_sudo_users()
