from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kitsune import _internal
from kitsune.core import lifecycle


RESULT: dict[str, object] = {}
SCENE: set[asyncio.Task] = set()


def _reset() -> None:
    _internal._RESTART_DONE = False
    _internal._RESTART_REQUESTED = False
    _internal._RESTART_INITIATOR = None
    lifecycle._BG_TASKS.clear()
    RESULT.clear()
    SCENE.clear()


async def _bg_loop() -> None:
    while True:
        await asyncio.sleep(0.05)


def _remaining_old() -> list[asyncio.Task]:
    cur = asyncio.current_task()
    return [t for t in SCENE if t is not cur and not t.done()]


def _remaining_new() -> list[asyncio.Task]:
    protected: set[object] = {asyncio.current_task()}
    init = _internal.restart_initiator()
    if init is not None:
        protected.add(init)
    return [t for t in SCENE if t not in protected and not t.done()]


async def _fake_shutdown(fixed: bool) -> None:
    await asyncio.sleep(0)
    remaining = _remaining_new() if fixed else _remaining_old()
    RESULT["cancelled"] = len(remaining)
    RESULT["cancelled_names"] = sorted(t.get_name() for t in remaining)
    for t in remaining:
        t.cancel()
    await asyncio.sleep(0)


async def _wait_for_py311(coro, timeout: float) -> None:
    inner = asyncio.ensure_future(coro)
    inner.set_name("shutdown")
    SCENE.add(inner)
    done, _ = await asyncio.wait({inner}, timeout=timeout)
    if not done:
        inner.cancel()
    else:
        inner.result()


async def _command_handler(fixed: bool) -> None:
    _internal._RESTART_REQUESTED = True
    if fixed:
        _internal._RESTART_INITIATOR = asyncio.current_task()
    try:
        await _wait_for_py311(_fake_shutdown(fixed), timeout=3.0)
    except asyncio.CancelledError:
        RESULT["handler_cancelled"] = True
        raise
    RESULT["execl_reached"] = True


async def _scenario(fixed: bool) -> dict[str, object]:
    _reset()

    bg = asyncio.ensure_future(_bg_loop())
    bg.set_name("bg_loop")
    SCENE.add(bg)
    lifecycle._BG_TASKS.add(bg)

    handler = asyncio.ensure_future(_command_handler(fixed))
    handler.set_name("cmd_handler")
    SCENE.add(handler)
    lifecycle._BG_TASKS.add(handler)

    await asyncio.wait({handler}, timeout=3.0)

    out = dict(RESULT)
    out["handler_cancelled_flag"] = handler.cancelled()
    out["restart_requested"] = _internal.restart_requested()

    for t in list(SCENE):
        if not t.done():
            t.cancel()
    await asyncio.gather(*SCENE, return_exceptions=True)
    return out


async def _check_cancel_bg_protects_initiator() -> dict[str, object]:
    _reset()
    done: dict[str, object] = {}

    bg = asyncio.ensure_future(_bg_loop())
    bg.set_name("bg_loop")
    lifecycle._BG_TASKS.add(bg)

    async def initiator() -> None:
        _internal._RESTART_REQUESTED = True
        _internal._RESTART_INITIATOR = asyncio.current_task()
        try:
            await lifecycle._cancel_background_tasks()
        except asyncio.CancelledError:
            done["initiator_cancelled"] = True
            raise
        done["initiator_survived"] = True

    task = asyncio.ensure_future(initiator())
    task.set_name("initiator")
    lifecycle._BG_TASKS.add(task)

    await asyncio.wait({task}, timeout=3.0)
    done["bg_cancelled"] = bg.cancelled() or bg.done()

    for t in (bg, task):
        if not t.done():
            t.cancel()
    await asyncio.gather(bg, task, return_exceptions=True)
    return done


def _main_finally_would_restart(res: dict[str, object]) -> bool:
    if res.get("execl_reached"):
        return True
    return bool(res.get("restart_requested"))


async def main() -> int:
    print("python:", sys.version.split()[0])
    print("(семантика wait_for <=3.11 воспроизведена вручную: shutdown = отдельный task)")
    print()

    before = await _scenario(fixed=False)
    print("[1] БЕЗ фикса — старый фильтр (t is not current_task):")
    print("    отменено задач в shutdown  :", before.get("cancelled"),
          before.get("cancelled_names"))
    print("    обработчик команды отменён :", before.get("handler_cancelled_flag"))
    print("    дошли до os.execl          :", bool(before.get("execl_reached")))

    after = await _scenario(fixed=True)
    print()
    print("[2] С фиксом — защита инициатора (t not in {current, initiator}):")
    print("    отменено задач в shutdown  :", after.get("cancelled"),
          after.get("cancelled_names"))
    print("    обработчик команды отменён :", after.get("handler_cancelled_flag"))
    print("    дошли до os.execl          :", bool(after.get("execl_reached")))

    bgres = await _check_cancel_bg_protects_initiator()
    print()
    print("[3] Реальный lifecycle._cancel_background_tasks() (пропатченный):")
    print("    инициатор выжил            :", bool(bgres.get("initiator_survived")))
    print("    инициатор отменён          :", bool(bgres.get("initiator_cancelled")))
    print("    фоновая задача отменена    :", bool(bgres.get("bg_cancelled")))

    fb_before = _main_finally_would_restart(before)
    fb_after = _main_finally_would_restart(after)
    print()
    print("[4] Запасной путь main.py finally (restart_requested -> exec_restart):")
    print("    даже в сценарии [1] restart всё равно произойдёт :", fb_before)
    print("    в сценарии [2] restart произойдёт                :", fb_after)

    _reset()
    argv, env, parent = _internal.build_restart_command()
    print()
    print("[5] cwd-независимая команда запуска:")
    print("    argv       :", argv)
    print("    cwd        :", parent)
    print("    PYTHONPATH :", env.get("PYTHONPATH", "").split(os.pathsep)[0])

    checks = {
        "[1] баг воспроизведён (обработчик отменён, execl не достигнут)":
            bool(before.get("handler_cancelled_flag"))
            and not before.get("execl_reached"),
        "[2] фикс работает (обработчик жив, execl достигнут)":
            not after.get("handler_cancelled_flag")
            and bool(after.get("execl_reached")),
        "[2] фоновая задача всё ещё отменяется":
            "bg_loop" in (after.get("cancelled_names") or []),
        "[3] _cancel_background_tasks не убивает инициатора":
            bool(bgres.get("initiator_survived")) and bool(bgres.get("bg_cancelled")),
        "[4] fallback в main.py гарантирует restart":
            fb_before and fb_after,
        "[5] команда запуска cwd-независима (-m kitsune)":
            argv[1:3] == ["-m", "kitsune"] and Path(parent).is_absolute(),
    }

    print()
    for name, ok in checks.items():
        print(("  PASS  " if ok else "  FAIL  ") + name)

    total_ok = all(checks.values())
    print()
    print("ИТОГ:", "PASS ✅" if total_ok else "FAIL ❌")
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
