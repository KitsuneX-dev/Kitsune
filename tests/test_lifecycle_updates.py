from __future__ import annotations

import asyncio

import pytest

from kitsune.core import lifecycle


class _BlockingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.update_started = asyncio.Event()
        self.catch_up_started = asyncio.Event()

    async def run_until_disconnected(self) -> None:
        self.calls.append("updates")
        self.update_started.set()
        await asyncio.Event().wait()

    async def catch_up(self) -> None:
        self.calls.append("catch_up")
        self.catch_up_started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_live_updates_do_not_wait_for_stuck_catch_up() -> None:
    client = _BlockingClient()

    update_task = lifecycle.start_telethon_updates(client)
    await asyncio.wait_for(client.update_started.wait(), timeout=1.0)
    await asyncio.wait_for(client.catch_up_started.wait(), timeout=1.0)

    assert client.calls[0] == "updates"
    assert not update_task.done()

    await lifecycle._cancel_background_tasks()


class _FailingClient:
    async def run_until_disconnected(self) -> None:
        raise ConnectionError("update transport failed")

    async def catch_up(self) -> None:
        return None


@pytest.mark.asyncio
async def test_update_loop_failure_remains_observable() -> None:
    update_task = lifecycle.start_telethon_updates(_FailingClient())

    with pytest.raises(ConnectionError, match="update transport failed"):
        await update_task

    await lifecycle._cancel_background_tasks()
