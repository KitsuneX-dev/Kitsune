import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio

import pytest

from kitsune.inline.types import InlineCall


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeMessage:
    def __init__(self, chat_id=555, message_id=777):
        self.chat = _FakeChat(chat_id)
        self.message_id = message_id

    async def edit_text(self, *args, **kwargs):
        return None


class _FakeCallbackQuery:

    def __init__(self, data, from_user, message=None, inline_message_id=None):
        self.id = "cbq-1"
        self.data = data
        self.from_user = from_user
        self.message = message
        self.inline_message_id = inline_message_id
        self.answers = []

    async def answer(self, text="", show_alert=False):
        self.answers.append((text, show_alert))


def _make_manager():
    from kitsune.inline.core import InlineManager

    client = type("C", (), {"tg_id": 12345})()
    db = object()
    return InlineManager(client, db, token="0:test")


def test_inline_call_has_from_user_id_field():
    call = InlineCall(
        id="x",
        chat_id=1,
        message_id=2,
        data="d",
        _answer=lambda **kw: None,
        _edit=lambda **kw: None,
    )
    assert hasattr(call, "from_user_id")
    assert call.from_user_id is None


def test_inline_call_from_user_id_can_be_set_explicitly():
    call = InlineCall(
        id="x",
        chat_id=1,
        message_id=2,
        data="d",
        _answer=lambda **kw: None,
        _edit=lambda **kw: None,
        from_user_id=999,
    )
    assert call.from_user_id == 999


def test_on_callback_sets_from_user_id():
    manager = _make_manager()

    captured = {}

    async def handler(call, *args, **kwargs):
        captured["call"] = call

                                                                   
                                                         
    cb_id = "cb12345"
    manager._callbacks[cb_id] = (handler, (), manager._client.tg_id, False, {})

    cbq = _FakeCallbackQuery(
        data=cb_id,
        from_user=_FakeUser(manager._client.tg_id),
        message=_FakeMessage(),
    )

    asyncio.run(manager._on_callback(cbq))

    assert "call" in captured, "handler не был вызван"
    assert isinstance(captured["call"], InlineCall)
    assert captured["call"].from_user_id == manager._client.tg_id


def test_on_callback_from_user_id_none_when_no_user():
    manager = _make_manager()

    captured = {}

    async def handler(call, *args, **kwargs):
        captured["call"] = call

    cb_id = "cbnouser"
                                                                          
    manager._callbacks[cb_id] = (handler, (), manager._client.tg_id, True, {})

    cbq = _FakeCallbackQuery(
        data=cb_id,
        from_user=None,
        message=_FakeMessage(),
    )

    asyncio.run(manager._on_callback(cbq))

    assert "call" in captured, "handler не был вызван"
    assert captured["call"].from_user_id is None
