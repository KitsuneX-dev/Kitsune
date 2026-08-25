from __future__ import annotations

import asyncio
import functools
import html
import inspect
import logging
import typing

__all__ = [
    "UPDATE_STATE_KEYS",
    "format_update_error",
    "clear_update_state",
    "report_update_failure",
    "guarded_update",
    "guard_task",
    "spawn_guarded",
]

logger = logging.getLogger(__name__)

UPDATE_STATE_KEYS = (
    "update_msg_chat",
    "update_msg_id",
    "update_msg_inline_id",
    "update_msg_via_telethon",
    "update_start_time",
    "pending_update",
    "pending_restart",
)

_MAX_ERROR_LEN = 600


def format_update_error(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:_MAX_ERROR_LEN]


def _error_text(exc: BaseException) -> str:
    detail = html.escape(format_update_error(exc))
    hint = ""
    low = detail.lower()
    if "cryptg" in low or "could not find a version" in low or "requires-python" in low:
        hint = (
            "\n\n<b>Похоже, версия Python слишком старая для зависимостей.</b>\n"
            "Kitsune попробует поставить новый Python сам; если не вышло — "
            "установи его вручную и запусти обновление снова."
        )
    return (
        "❌ <b>Обновление не удалось</b>\n\n"
        f"<code>{detail}</code>{hint}\n\n"
        "Состояние обновления сброшено, бот продолжает работать."
    )


async def _maybe_await(result: typing.Any) -> typing.Any:
    if inspect.isawaitable(result):
        return await result
    return result


async def clear_update_state(
    db: typing.Any,
    owners: typing.Sequence[str],
    keys: typing.Sequence[str] = UPDATE_STATE_KEYS,
) -> None:
    if db is None:
        return
    for owner in owners:
        for key in keys:
            try:
                await _maybe_await(db.delete(owner, key))
            except Exception:
                logger.debug("update_guard: не удалось удалить %s/%s", owner, key, exc_info=True)
    try:
        await _maybe_await(db.force_save())
    except Exception:
        logger.debug("update_guard: force_save не удался", exc_info=True)


async def _store_last_error(
    db: typing.Any,
    owners: typing.Sequence[str],
    exc: BaseException,
) -> None:
    if db is None:
        return
    text = format_update_error(exc)
    for owner in owners:
        try:
            await _maybe_await(db.set(owner, "last_update_error", text[:300]))
        except Exception:
            logger.debug("update_guard: не удалось сохранить last_update_error", exc_info=True)
    try:
        await _maybe_await(db.force_save())
    except Exception:
        logger.debug("update_guard: force_save не удался", exc_info=True)


async def report_update_failure(
    exc: BaseException,
    *,
    db: typing.Any = None,
    owners: typing.Sequence[str] = (),
    notify: typing.Any = None,
    keys: typing.Sequence[str] = UPDATE_STATE_KEYS,
    store_error: bool = True,
) -> str:
    logger.exception("update_guard: обновление завершилось ошибкой", exc_info=exc)
    text = _error_text(exc)
    await clear_update_state(db, owners, keys)
    if store_error:
        await _store_last_error(db, owners, exc)
    if notify is not None:
        try:
            await _maybe_await(notify(text))
        except Exception:
            logger.debug("update_guard: не удалось отправить сообщение об ошибке", exc_info=True)
    return text


async def guarded_update(
    coro_factory: typing.Any,
    *,
    db: typing.Any = None,
    owners: typing.Sequence[str] = (),
    notify: typing.Any = None,
    keys: typing.Sequence[str] = UPDATE_STATE_KEYS,
    store_error: bool = True,
) -> bool:
    try:
        result = coro_factory() if callable(coro_factory) else coro_factory
        await _maybe_await(result)
        return True
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        await report_update_failure(
            exc,
            db=db,
            owners=owners,
            notify=notify,
            keys=keys,
            store_error=store_error,
        )
        return False


def guard_task(
    task: typing.Any,
    *,
    db: typing.Any = None,
    owners: typing.Sequence[str] = (),
    notify: typing.Any = None,
    keys: typing.Sequence[str] = UPDATE_STATE_KEYS,
    store_error: bool = True,
) -> typing.Any:
    def _done(finished: typing.Any) -> None:
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.exception("update_guard: фоновая задача обновления упала", exc_info=exc)
            return
        loop.create_task(
            report_update_failure(
                exc,
                db=db,
                owners=owners,
                notify=notify,
                keys=keys,
                store_error=store_error,
            )
        )

    task.add_done_callback(_done)
    return task


def spawn_guarded(
    coro: typing.Any,
    *,
    db: typing.Any = None,
    owners: typing.Sequence[str] = (),
    notify: typing.Any = None,
    keys: typing.Sequence[str] = UPDATE_STATE_KEYS,
    store_error: bool = True,
) -> typing.Any:
    task = asyncio.ensure_future(coro)
    return guard_task(
        task,
        db=db,
        owners=owners,
        notify=notify,
        keys=keys,
        store_error=store_error,
    )


def guard_entrypoint(
    *,
    owners: typing.Sequence[str] = (),
    keys: typing.Sequence[str] = UPDATE_STATE_KEYS,
) -> typing.Callable[..., typing.Any]:
    def decorator(func: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
        @functools.wraps(func)
        async def wrapper(self: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            try:
                return await func(self, *args, **kwargs)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                await report_update_failure(
                    exc,
                    db=getattr(self, "_db", None) or getattr(self, "db", None),
                    owners=owners,
                    keys=keys,
                )
                return None

        return wrapper

    return decorator
