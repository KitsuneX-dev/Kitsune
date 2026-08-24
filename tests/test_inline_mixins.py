
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_manager():
    from kitsune.inline.core import InlineManager

    client = MagicMock()
    client.tg_id = 777
    client.delete_messages = AsyncMock()
    return InlineManager(client, MagicMock(), "123:token")


def test_utils_is_single_package_without_shadowed_module():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.find_spec("kitsune.utils")
    assert spec.submodule_search_locations is not None
    root = Path(spec.origin).parent.parent
    assert not (root / "utils.py").exists()
    assert not (root / "utils_additions.py").exists()
    assert not (root / "secure").exists()


def test_utils_exposes_merged_api():
    from kitsune import utils

    for name in (
        "ensure_kitsune_folder", "detect_environment", "answer", "answer_file",
        "get_args", "get_args_raw", "get_args_html", "escape_html", "get_chat_id",
        "smart_split", "ProgressMessage", "find_caller", "asset_channel", "rand",
        "chunks", "truncate", "is_serializable", "auto_delete", "progress_bar",
    ):
        assert hasattr(utils, name), name


def test_escape_html_escapes_all_specials():
    from kitsune.utils import escape_html

    assert escape_html('<b>&"x"') == "&lt;b&gt;&amp;&quot;x&quot;"


def test_inline_manager_has_all_mixins():
    from kitsune.inline.bot_pm import BotPM
    from kitsune.inline.core import InlineManager
    from kitsune.inline.gallery import Gallery
    from kitsune.inline.list import InlineList
    from kitsune.inline.query_gallery import QueryGallery

    for cls in (InlineList, Gallery, QueryGallery, BotPM):
        assert cls in InlineManager.__mro__


def test_inline_manager_provides_mixin_attributes():
    im = _make_manager()
    assert isinstance(im._units, dict)
    assert isinstance(im._custom_map, dict)
    assert im._me == 777
    assert len(im._rand(16)) == 16
    assert im._rand(12) != im._rand(12)
    assert im.bot is None
    assert callable(im._invoke_unit)
    assert callable(im._delete_unit_message)


def test_inline_manager_state_is_not_shared_between_instances():
    a, b = _make_manager(), _make_manager()
    a.register_query_gallery("only-a", ["https://x/1.jpg"])
    a._fsm.set(1, "waiting_answer")
    assert "only-a" not in b._query_galleries
    assert b._fsm.get(1) is None


async def test_list_renders_paginates_and_closes():
    im = _make_manager()
    sent = MagicMock(id=42, chat_id=-100500)

    async def fake_invoke(unit_id, message):
        return sent

    im._invoke_unit = fake_invoke
    message = MagicMock(out=True)
    message.edit = AsyncMock(return_value=MagicMock(delete=AsyncMock()))

    result = await im.list(message, [f"item {i}" for i in range(25)], title="Список")
    assert result is sent

    uid = next(u for u, d in im._units.items() if d.get("type") == "list")
    assert im._units[uid]["message_id"] == 42
    assert im._units[uid]["chat"] == -100500

    text, markup = im._build_list_page(uid)
    assert "item 0" in text and "1 / 3" in text
    assert markup

    im.edit = AsyncMock()
    call = MagicMock(from_user=MagicMock(id=777))
    call.answer = AsyncMock()
    await im._list_page(call, 1, unit_id=uid)
    assert im._units[uid]["current_page"] == 1

    await im._list_page(call, "close", unit_id=uid)
    assert uid not in im._units
    im._client.delete_messages.assert_awaited()


async def test_gallery_builds_unit_and_switches_pages():
    im = _make_manager()
    im._bot = MagicMock()
    im._bot.edit_message_media = AsyncMock()
    sent = MagicMock(id=42, chat_id=-100500)
    urls = ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"]

    async def fake_invoke(unit_id, message):
        future = im._units[unit_id].get("future")
        if future is not None:
            future.set()
        return sent

    im._invoke_unit = fake_invoke
    message = MagicMock(out=True)
    message.edit = AsyncMock(return_value=MagicMock(delete=AsyncMock()))

    assert await im.gallery(message, urls, caption="cap") is sent

    uid = next(u for u, d in im._units.items() if d.get("type") == "gallery")
    unit = im._units[uid]
    assert unit["photos"] == urls
    assert unit["message_id"] == 42
    assert unit["btn_call_data"] in im._custom_map
    assert im._gallery_markup(uid) is not None

    call = MagicMock(inline_message_id="iid1")
    call.answer = AsyncMock()
    await im._gallery_page(call, 1, unit_id=uid)
    assert im._units[uid]["current_index"] == 1
    im._bot.edit_message_media.assert_awaited()


async def test_gallery_inline_result_uses_thumbnail_url():
    im = _make_manager()
    urls = ["https://x/1.jpg"]
    uid = im._rand(16)
    im._units[uid] = {
        "type": "gallery",
        "photos": urls,
        "current_index": 0,
        "next_handler": urls,
        "caption": "cap",
        "gif": False,
        "uid": uid,
        "future": asyncio.Event(),
    }
    query = MagicMock(query=uid, from_user=MagicMock(id=777))
    query.answer = AsyncMock()

    await im._gallery_inline_handler(query)

    query.answer.assert_awaited()
    result = query.answer.await_args[0][0][0]
    assert result.thumbnail_url == urls[0]
    assert im._units[uid]["future"].is_set()


async def test_query_gallery_registration_and_answer():
    im = _make_manager()
    urls = ["https://x/1.jpg", "https://x/2.jpg"]
    im.register_query_gallery("cats", urls, caption="c")

    query = MagicMock(query="cats")
    query.answer = AsyncMock()
    assert await im._handle_query_gallery(query) is True
    assert len(query.answer.await_args[0][0]) == 2

    assert im.unregister_query_gallery("cats") is True
    query2 = MagicMock(query="cats")
    query2.answer = AsyncMock()
    assert await im._handle_query_gallery(query2) is False


async def test_bot_pm_ask_receives_answer_via_on_message():
    im = _make_manager()
    im._bot = MagicMock()
    im._bot.send_message = AsyncMock()
    im._bot_username = "kitsune_bot"
    received = {}

    async def handler(message, value):
        received["value"] = value

    assert await im.ask(777, "Введи значение?", handler) is True
    assert im.is_waiting(777)

    pm = MagicMock(from_user=MagicMock(id=777), text="ответ")
    await im._on_message(pm)

    assert received["value"] == "ответ"
    assert not im.is_waiting(777)


async def test_custom_map_callback_is_routed():
    im = _make_manager()
    hits = []

    async def handler(call, page):
        hits.append(page)

    im._custom_map["cb1"] = {"handler": handler, "args": (3,)}
    call = MagicMock(data="cb1", inline_message_id=None, from_user=MagicMock(id=777))
    call.answer = AsyncMock()
    call.message = MagicMock(chat=MagicMock(id=1), message_id=2, edit_text=AsyncMock())

    await im._on_callback(call)
    assert hits == [3]
