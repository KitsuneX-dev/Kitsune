
from __future__ import annotations

import asyncio

import pytest

from kitsune.web.setup import SetupServer


def _server() -> SetupServer:
    return SetupServer(save_config_fn=lambda *a, **kw: None, get_config_fn=lambda: {})


@pytest.mark.asyncio
async def test_spawn_registers_and_autoremoves_task() -> None:
    srv = _server()
    assert srv._bg_tasks == set()

    started = asyncio.Event()

    async def _work() -> None:
        started.set()
        await asyncio.sleep(0)

    task = srv._spawn(_work())
    assert task in srv._bg_tasks, "задача обязана попасть в реестр (защита от GC)"

    await task
    await asyncio.sleep(0)
    assert srv._bg_tasks == set(), "реестр не должен расти бесконечно"


@pytest.mark.asyncio
async def test_cancel_bg_tasks_and_wait_kills_long_runner() -> None:
    srv = _server()

    async def _forever() -> None:
        await asyncio.sleep(3600)

    task = srv._spawn(_forever())
    await asyncio.sleep(0)
    assert not task.done()

    await srv._cancel_bg_tasks_and_wait()
    assert task.done() and task.cancelled()
    assert srv._bg_tasks == set()


@pytest.mark.asyncio
async def test_cancel_code_task_drops_previous_send() -> None:
    srv = _server()

    async def _slow_sendcode() -> None:
        await asyncio.sleep(3600)

    first = srv._spawn(_slow_sendcode())
    srv._code_task = first
    await asyncio.sleep(0)

    srv._cancel_code_task()
    assert first.cancelled() or first.cancelling() > 0
    assert srv._code_task is None

    second = srv._spawn(_slow_sendcode())
    srv._code_task = second
    await srv._cancel_bg_tasks_and_wait()
    assert second.done()


@pytest.mark.asyncio
async def test_cancel_code_task_is_safe_when_idle_or_done() -> None:
    srv = _server()
    srv._cancel_code_task()
    assert srv._code_task is None

    async def _noop() -> None:
        return None

    done = srv._spawn(_noop())
    await done
    srv._code_task = done
    srv._cancel_code_task()
    assert srv._code_task is None


@pytest.mark.asyncio
async def test_wait_done_cancels_pending_background_work() -> None:
    srv = _server()

    async def _forever() -> None:
        await asyncio.sleep(3600)

    leftover = srv._spawn(_forever())
    srv._code_task = srv._spawn(_forever())
    await asyncio.sleep(0)

    srv._done.set()
    await asyncio.wait_for(srv.wait_done(), timeout=10)

    assert leftover.done(), "фоновая задача переживает завершение визарда"
    assert srv._bg_tasks == set()
    assert srv._code_task is None
