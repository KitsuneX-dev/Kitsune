
from __future__ import annotations

import asyncio
import typing
from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeRunner:

    def __init__(self, *args, **kwargs) -> None:
        self.bot = None
        self.dp = None
        self._polling_task: typing.Any = None
        self.started_tokens: list[str] = []

    async def start(self, token: str, first_run: bool = False) -> None:
        self.started_tokens.append(token)
        await asyncio.sleep(3600)

    async def stop(self) -> None:
        return None


class _FakeUpdater:
    def __init__(self, *args, **kwargs) -> None:
        self.stopped = False

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    async def notify_update_done(self) -> None:
        await asyncio.sleep(3600)


class _FakeSetup:
    def __init__(self, *args, **kwargs) -> None:
        self.saved_tokens: list[str] = []

    def load_token_from_config(self):
        return None

    def save_token_to_config(self, token: str) -> None:
        self.saved_tokens.append(token)

    async def enable_inline_mode(self, username: str) -> None:
        return None

    async def get_token_for_bot(self, username: str):
        return "222222222:" + "B" * 35


@pytest.fixture()
def notifier(fake_client, fake_db, monkeypatch):
    import kitsune.modules.notifier as notifier_pkg

    monkeypatch.setattr(notifier_pkg, "BotSetup", _FakeSetup)
    monkeypatch.setattr(notifier_pkg, "BotRunner", _FakeRunner)
    monkeypatch.setattr(notifier_pkg, "UpdateChecker", _FakeUpdater)

    mod = notifier_pkg.NotifierModule(fake_client, fake_db)
    mod._setup = _FakeSetup()
    mod._runner = _FakeRunner()
    mod._updater = _FakeUpdater()
    return mod


def _alive(mod) -> list[asyncio.Task]:
    return [t for t in mod._bg_tasks if not t.done()]


@pytest.mark.asyncio
async def test_on_load_registers_all_background_tasks(notifier, fake_db):
    fake_db.store["kitsune.notifier"] = {"bot_token": "111111111:" + "A" * 35}
    await notifier.on_load()
    await asyncio.sleep(0)

    assert len(_alive(notifier)) == 4, "должны отслеживаться все 4 фоновые задачи"

    await notifier.on_unload()
    assert _alive(notifier) == []


@pytest.mark.asyncio
async def test_on_load_without_token_tracks_auto_setup(notifier, fake_db):
    notifier.client.get_me = AsyncMock(side_effect=asyncio.CancelledError)
    await notifier.on_load()
    await asyncio.sleep(0)

    assert len(notifier._bg_tasks) == 1

    await notifier.on_unload()
    assert _alive(notifier) == []


@pytest.mark.asyncio
async def test_setbot_cancels_previous_bot_tasks(notifier, fake_db):
    fake_db.store["kitsune.notifier"] = {"bot_token": "111111111:" + "A" * 35}
    await notifier.on_load()
    await asyncio.sleep(0)
    first_generation = set(_alive(notifier))
    assert len(first_generation) == 4


    event = MagicMock()
    msg = MagicMock()
    msg.edit = AsyncMock()
    event.reply = AsyncMock(return_value=msg)
    notifier.get_args = MagicMock(return_value="@some_kitsune_bot")

    await notifier.setbot_cmd(event)
    await asyncio.sleep(0)


    assert all(t.cancelled() or t.done() for t in first_generation)

    alive_now = _alive(notifier)
    assert len(alive_now) == 3
    assert not (set(alive_now) & first_generation)


    await notifier.setbot_cmd(event)
    await asyncio.sleep(0)
    assert len(_alive(notifier)) == 3

    await notifier.on_unload()
    assert _alive(notifier) == []


@pytest.mark.asyncio
async def test_resetbot_cancels_watchdog(notifier, fake_db):
    fake_db.store["kitsune.notifier"] = {"bot_token": "111111111:" + "A" * 35}
    await notifier.on_load()
    await asyncio.sleep(0)
    assert _alive(notifier)

    event = MagicMock()
    event.reply = AsyncMock()
    await notifier.resetbot_cmd(event)

    assert _alive(notifier) == []


@pytest.mark.asyncio
async def test_done_tasks_do_not_accumulate(notifier):

    async def _noop() -> None:
        return None

    for _ in range(50):
        notifier._spawn(_noop())
    await asyncio.sleep(0.05)
    assert notifier._bg_tasks == set()


@pytest.mark.asyncio
async def test_no_stray_tasks_left_in_event_loop(notifier, fake_db):
    fake_db.store["kitsune.notifier"] = {"bot_token": "111111111:" + "A" * 35}
    before = {id(t) for t in asyncio.all_tasks()}

    await notifier.on_load()
    await asyncio.sleep(0)
    await notifier.on_unload()
    await asyncio.sleep(0)

    stray = [
        t for t in asyncio.all_tasks()
        if id(t) not in before and not t.done()
    ]
    assert stray == [], f"остались незавершённые задачи: {stray}"
