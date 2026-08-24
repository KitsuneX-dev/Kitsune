from __future__ import annotations

import asyncio

import pytest

from kitsune.tl_cache import KitsuneTelegramClient, _HookedUpdatesQueue


def _make_client() -> KitsuneTelegramClient:
    return KitsuneTelegramClient(":memory:", 1, "test")


def test_hook_is_shared_with_sender() -> None:
    async def run() -> None:
        client = _make_client()
        assert isinstance(client._updates_queue, _HookedUpdatesQueue)
        assert client._updates_queue is client._sender._updates_queue

    asyncio.run(run())


def test_sender_side_update_reaches_update_loop() -> None:
    async def run() -> None:
        client = _make_client()
        client._sender._updates_queue.put_nowait("update")
        assert client._updates_queue.qsize() == 1
        assert client._updates_queue.get_nowait() == "update"

    asyncio.run(run())


def test_raw_updates_processor_still_fires() -> None:
    async def run() -> None:
        client = _make_client()
        seen: list[object] = []
        client.raw_updates_processor = seen.append
        client._sender._updates_queue.put_nowait("update")
        assert seen == ["update"]

    asyncio.run(run())


def test_processor_exception_does_not_drop_update() -> None:
    async def run() -> None:
        client = _make_client()

        def boom(_: object) -> None:
            raise RuntimeError("processor failure")

        client.raw_updates_processor = boom
        client._sender._updates_queue.put_nowait("update")
        assert client._updates_queue.get_nowait() == "update"

    asyncio.run(run())


def test_desync_is_self_healed() -> None:
    async def run() -> None:
        client = _make_client()
        hooked = client._updates_queue
        stray: asyncio.Queue = asyncio.Queue()
        stray.put_nowait("stray")
        client._sender._updates_queue = stray

        client._verify_updates_queue_wiring()

        assert client._sender._updates_queue is hooked
        assert hooked.get_nowait() == "stray"

    asyncio.run(run())


def test_hook_preserves_updates_queued_before_install() -> None:
    async def run() -> None:
        client = _make_client()
        plain: asyncio.Queue = asyncio.Queue()
        plain.put_nowait("early")
        client._updates_queue = plain
        client._sender._updates_queue = plain

        client._install_updates_queue_hook()

        assert client._updates_queue is client._sender._updates_queue
        assert isinstance(client._updates_queue, _HookedUpdatesQueue)
        assert client._updates_queue.get_nowait() == "early"

    asyncio.run(run())


def test_hook_skipped_when_queue_not_shared() -> None:
    async def run() -> None:
        client = _make_client()
        client._updates_queue = asyncio.Queue()
        client._sender._updates_queue = asyncio.Queue()
        before = client._updates_queue

        client._install_updates_queue_hook()

        assert client._updates_queue is before

    asyncio.run(run())


@pytest.mark.parametrize("attr", ["_updates_queue", "_sender"])
def test_hook_tolerates_missing_attributes(attr: str) -> None:
    async def run() -> None:
        client = _make_client()
        setattr(client, attr, None)
        client._install_updates_queue_hook()
        client._verify_updates_queue_wiring()

    asyncio.run(run())
