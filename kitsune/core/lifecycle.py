from __future__ import annotations
import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sqlite3
import threading
import time as _time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from ..paths import data_dir as _kdd
DATA_DIR = _kdd()

_BG_TASKS: set[asyncio.Task] = set()
_WATCHDOG_STOP = threading.Event()
_WATCHDOG_THREAD: threading.Thread | None = None


def spawn(coro) -> asyncio.Task:
    task = asyncio.ensure_future(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


def print_banner(me: Any) -> None:
    from ..version import __version_str__
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    print(
        f"\n{Fore.MAGENTA}{'━' * 42}{Style.RESET_ALL}\n"
        f"  🦊 {Fore.CYAN}Kitsune Userbot{Style.RESET_ALL} v{__version_str__}\n"
        f"  👤 {me.first_name} (id: {me.id})\n"
        f"  👨‍💻 Developer: Yushi — @Mikasu32\n"
        f"{Fore.MAGENTA}{'━' * 42}{Style.RESET_ALL}\n"
    )


async def setup_kitsune_folder(client: Any, db: Any) -> None:
    try:
        await asyncio.sleep(8)
    except asyncio.CancelledError:
        return
    try:
        from ..utils import ensure_kitsune_folder
        await ensure_kitsune_folder(client, db)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("lifecycle: не удалось настроить папку Kitsune")


def install_signal_handlers(stop_event: asyncio.Event, loop: asyncio.AbstractEventLoop) -> None:
    _state = {"count": 0}

    def _shutdown(*_: object) -> None:
        _state["count"] += 1
        if _state["count"] == 1:
            logger.info("main: received shutdown signal")
            loop.call_soon_threadsafe(stop_event.set)
        elif _state["count"] >= 2:
            logger.warning("main: second shutdown signal — forcing exit")
            os._exit(130)

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, OSError, RuntimeError):
            loop.add_signal_handler(sig, _shutdown)


    def _raw_signal(signum, frame) -> None:
        _shutdown()

    with contextlib.suppress(Exception):
        signal.signal(signal.SIGINT, _raw_signal)
    with contextlib.suppress(Exception):
        signal.signal(signal.SIGTERM, _raw_signal)


def start_watchdog(stop_event: asyncio.Event, loop: asyncio.AbstractEventLoop) -> None:
    global _WATCHDOG_THREAD
    _WATCHDOG_STOP.clear()
    _wdog_last_tick = [_time.monotonic()]

    def _tick_cb() -> None:
        _wdog_last_tick[0] = _time.monotonic()

    def _watchdog_thread() -> None:
        while not _WATCHDOG_STOP.is_set() and not stop_event.is_set():
            if _WATCHDOG_STOP.wait(timeout=10.0):
                return
            if stop_event.is_set() or _WATCHDOG_STOP.is_set():
                return
            if loop.is_closed() or not loop.is_running():
                return
            try:
                loop.call_soon_threadsafe(_tick_cb)
            except RuntimeError:
                return
            except Exception:
                pass
            if _WATCHDOG_STOP.wait(timeout=5.0):
                return
            if stop_event.is_set() or _WATCHDOG_STOP.is_set():
                return
            if _time.monotonic() - _wdog_last_tick[0] > 45:
                logger.critical(
                    "main: event loop FROZEN >45s — принудительный перезапуск процесса"
                )
                try:
                    os.kill(os.getpid(), signal.SIGTERM)
                except Exception:
                    os._exit(1)
                return

    _WATCHDOG_THREAD = threading.Thread(
        target=_watchdog_thread, name="kitsune-watchdog", daemon=True
    )
    _WATCHDOG_THREAD.start()
    logger.info("main: watchdog started (threshold=45s)")


def stop_watchdog() -> None:
    _WATCHDOG_STOP.set()
    th = _WATCHDOG_THREAD
    if th is not None and th.is_alive():
        with contextlib.suppress(Exception):
            th.join(timeout=2.0)


async def _cancel_background_tasks() -> None:
    tasks = [t for t in list(_BG_TASKS) if not t.done()]
    for t in tasks:
        t.cancel()
    if not tasks:
        return
    with contextlib.suppress(Exception):
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=5.0,
        )


async def shutdown(client: Any, db: Any) -> None:
    logger.info("main: shutting down…")
    stop_watchdog()
    from ..session_enc import encrypt_session_file
    from .connection import _release_hydro_lock

    _acc_mgr = getattr(client, "_kitsune_accounts", None)
    if _acc_mgr is not None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(_acc_mgr.shutdown_all(), timeout=25.0)

    if getattr(client, "hydrogram", None):
        with contextlib.suppress(Exception):
            await asyncio.wait_for(client.hydrogram.stop(), timeout=10.0)
        with contextlib.suppress(Exception):
            _release_hydro_lock()

    try:
        for _t in list(asyncio.all_tasks()):
            _coro = getattr(_t, "get_coro", lambda: None)()
            _name = getattr(_coro, "__qualname__", "") or ""
            if "_run_until_disconnected" in _name and not _t.done():
                _t.cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(_t), timeout=2.0)
    except Exception:
        logger.debug("main: cancel update-loop failed", exc_info=True)

    await _cancel_background_tasks()

    try:
        await asyncio.wait_for(db.shutdown(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("main: db shutdown timed out")
    except Exception:
        logger.exception("main: db shutdown failed")

    try:
        sess = getattr(client, "session", None)
        sess_file = getattr(sess, "filename", None)
        if sess_file and sess_file != ":memory:":
            with contextlib.suppress(Exception):
                _con = sqlite3.connect(sess_file)
                try:
                    _cc = _con.cursor()
                    _cc.execute(
                        "CREATE TABLE IF NOT EXISTS entities ("
                        "id integer primary key, hash integer not null, "
                        "username text, phone integer, name text, "
                        "date integer)"
                    )
                    _cc.execute(
                        "CREATE TABLE IF NOT EXISTS sent_files ("
                        "md5_digest blob, file_size integer, "
                        "type integer, id integer, hash integer, "
                        "primary key(md5_digest, file_size, type))"
                    )
                    _cc.execute(
                        "CREATE TABLE IF NOT EXISTS update_state ("
                        "id integer primary key, pts integer, "
                        "qts integer, date integer, seq integer)"
                    )
                    _con.commit()
                finally:
                    _con.close()
    except Exception:
        logger.debug("main: pre-disconnect schema heal skipped", exc_info=True)

    try:
        await asyncio.wait_for(client.disconnect(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("main: client disconnect timed out")
    except sqlite3.OperationalError as _se:
        if "no such table" in str(_se).lower():
            logger.info(
                "main: client disconnect: session-db без таблицы entities — "
                "это не критично, игнорирую (%s)", _se,
            )
        else:
            logger.exception("main: client disconnect failed")
    except Exception:
        logger.exception("main: client disconnect failed")

    try:
        encrypt_session_file()
    except Exception:
        logger.exception("main: session encrypt failed")

    remaining = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]
    if remaining:
        for t in remaining:
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                asyncio.gather(*remaining, return_exceptions=True),
                timeout=3.0,
            )

    try:
        from .loader import flush_ast_scan_cache
        flush_ast_scan_cache()
    except Exception:
        logger.debug("main: AST scan cache flush skipped", exc_info=True)

    logger.info("main: goodbye 🦊")


    try:
        from ..net.http_pool import close_shared_session
        await close_shared_session()
    except Exception:
        logger.debug("main: shared HTTP session close skipped", exc_info=True)

    try:
        from .. import log as _log_mod
        _log_mod.shutdown()
    except Exception:
        pass


async def startup(
    args: argparse.Namespace,
    load_config_fn,
    save_config_fn,
    have_uvloop: bool,
) -> None:
    from .. import log
    from ..tl_cache import KitsuneTelegramClient
    from ..database import DatabaseManager
    from .security import SecurityManager
    from .dispatcher import CommandDispatcher
    from .loader import Loader
    from ..translations import Translator
    from .session import restore_session, ensure_authorized
    from .connection import start_hydrogram, keepalive
    from .reliability import get_breaker

    log.init()
    if have_uvloop:
        logger.info("main: uvloop enabled")
    try:
        logger.info(
            "main: event loop = %s", type(asyncio.get_running_loop()).__module__
        )
    except RuntimeError:
        pass
    cfg = load_config_fn()
    api_id: int = int(cfg.get("api_id") or os.environ.get("API_ID", 0))
    api_hash: str = str(cfg.get("api_hash") or os.environ.get("API_HASH", ""))
    prefix: str = str(cfg.get("prefix", "."))
    session_path = DATA_DIR / "kitsune"

    client, cfg = await restore_session(
        cfg, api_id, api_hash, session_path, save_config_fn, load_config_fn,
    )
    api_id = int(cfg.get("api_id", api_id) or api_id)
    api_hash = str(cfg.get("api_hash", api_hash) or api_hash)
    prefix = str(cfg.get("prefix", prefix))

    client, me = await ensure_authorized(client, cfg, save_config_fn, load_config_fn)
    try:
        from ..mtproto_replay import ensure_replay_protection
        _replay_status = ensure_replay_protection(client)
        logger.info("main: MTProto replay-protection: %s", _replay_status)
    except Exception:
        logger.debug("main: replay-protection setup skipped", exc_info=True)
    client.tg_id = me.id
    client.tg_me = me
    client._kitsune_bot_ready = asyncio.Event()
    logger.info("main: logged in as %s (id=%d)", me.first_name, me.id)

    try:
        get_breaker("telegram_api", failure_threshold=5, cooldown=60.0)
        get_breaker("redis_io", failure_threshold=3, cooldown=30.0)
        get_breaker("hydrogram_io", failure_threshold=3, cooldown=300.0)
    except Exception:
        logger.debug("main: reliability breakers preregister failed", exc_info=True)

    hydro_task: asyncio.Task | None = None
    if not args.no_hydrogram:
        hydro_task = asyncio.create_task(
            start_hydrogram(
                api_id, api_hash, str(session_path),
                load_config_fn, save_config_fn,
            ),
            name="hydrogram-startup",
        )

    db = DatabaseManager(client)
    db_task = asyncio.create_task(db.init(), name="db-init")
    await db_task
    client._kitsune_db = db

    security = SecurityManager(client, db)
    await security.init()
    client._kitsune_security = security

    db_prefix = db.get("kitsune.core", "prefix", None)
    if db_prefix and isinstance(db_prefix, str):
        prefix = db_prefix

    translator = Translator(db)
    _saved_lang = db.get("kitsune.core", "lang", "ru")
    translator.set_language(_saved_lang if isinstance(_saved_lang, str) else "ru")
    client._kitsune_translator = translator

    dispatcher = CommandDispatcher(client, db, security, prefix=prefix)
    dispatcher.set_owner(me.id)
    client._kitsune_dispatcher = dispatcher

    loader = Loader(client, db, dispatcher)
    client._kitsune_loader = loader

    async def _start_telethon_updates() -> None:
        try:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.catch_up(), timeout=15.0)
            spawn(client.run_until_disconnected())
            logger.info("main: Telethon update loop started (run_until_disconnected)")
        except Exception:
            logger.exception(
                "main: failed to start update loop — "
                "commands and watchers will NOT work until this is fixed!"
            )

    update_loop_task = asyncio.create_task(
        _start_telethon_updates(), name="telethon-update-startup"
    )

    async def _load_all_modules() -> None:
        await asyncio.gather(
            loader.load_all_builtin(),
            loader.load_all_user(),
        )

    load_task = asyncio.create_task(_load_all_modules(), name="loader-load-all")

    hydro = None
    if hydro_task is not None:
        try:
            hydro = await hydro_task
        except Exception:
            logger.exception("main: Hydrogram startup task raised")
            hydro = None
        client.hydrogram = hydro
        if hydro:
            from .hydro_bridge import setup_hydrogram_bridge
            try:
                await setup_hydrogram_bridge(hydro, client, dispatcher, db)
                logger.info(
                    "main: HydrogramBridge active — single dispatcher for both clients"
                )
            except Exception:
                logger.exception(
                    "main: setup_hydrogram_bridge failed, continuing without bridge"
                )

    await load_task

    try:
        saved_aliases = db.get("kitsune.core", "aliases", {}) or {}
        if isinstance(saved_aliases, dict) and saved_aliases:
            dispatcher.load_aliases(
                {str(name): str(target) for name, target in saved_aliases.items()}
            )
            logger.info("main: restored %d command alias(es)", len(dispatcher.get_aliases()))
    except Exception:
        logger.exception("main: failed to restore command aliases")

    try:
        saved_disabled = db.get("kitsune.core", "disabled_commands", []) or []
        if isinstance(saved_disabled, (list, tuple)) and saved_disabled:
            dispatcher.load_disabled_commands([str(cmd) for cmd in saved_disabled])
            logger.info("main: restored %d disabled command(s)", len(dispatcher.get_disabled_commands()))
    except Exception:
        logger.exception("main: failed to restore disabled commands")

    _saved_lang = db.get("kitsune.core", "lang", "ru")
    translator.set_language(_saved_lang if isinstance(_saved_lang, str) else "ru")

    if not args.no_web:
        try:
            from ..web.core import WebCore
            web = WebCore(client, db)
            client._kitsune_web = web
            spawn(web.start(
                host=cfg.get("web_host", "127.0.0.1"),
                port=int(cfg.get("web_port", 8080)),
            ))
            logger.info(
                "main: web interface starting on port %d",
                cfg.get("web_port", 8080),
            )
        except ImportError:
            logger.info("main: web dependencies not installed, skipping web UI")
        except Exception:
            logger.exception("main: web startup failed")

    spawn(log.setup_tg_logging(client))
    spawn(setup_kitsune_folder(client, db))
    print_banner(me)
    spawn(keepalive(client))

    try:
        from ..paths import is_secondary
        if not is_secondary():
            from ..accounts_manager import get_manager
            _acc_mgr = get_manager()
            client._kitsune_accounts = _acc_mgr
            spawn(_acc_mgr.start_enabled())
            logger.info("main: менеджер доп.аккаунтов инициализирован")
    except Exception:
        logger.exception("main: не удалось инициализировать менеджер доп.аккаунтов")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event, loop)
    start_watchdog(stop_event, loop)

    await update_loop_task

    try:
        await stop_event.wait()
    finally:
        with contextlib.suppress(Exception):
            await shutdown(client, db)
