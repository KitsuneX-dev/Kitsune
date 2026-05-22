from __future__ import annotations
import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".kitsune"

_BG_TASKS: set[asyncio.Task] = set()


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
    await asyncio.sleep(8)
    try:
        from ..utils import ensure_kitsune_folder
        await ensure_kitsune_folder(client, db)
    except Exception:
        pass


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    def _shutdown(*_: object) -> None:
        logger.info("main: received shutdown signal")
        stop_event.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(OSError):
            asyncio.get_event_loop().add_signal_handler(sig, _shutdown)


def start_watchdog(stop_event: asyncio.Event) -> None:
    import threading
    import time as _time
    _wdog_last_tick = [_time.monotonic()]
    _wdog_loop = asyncio.get_event_loop()

    async def _wdog_tick() -> None:
        _wdog_last_tick[0] = _time.monotonic()

    def _watchdog_thread() -> None:
        while not stop_event.is_set():
            _time.sleep(10)
            try:
                fut = asyncio.run_coroutine_threadsafe(_wdog_tick(), _wdog_loop)
                fut.result(timeout=5)
            except Exception:
                pass
            _time.sleep(5)
            if _time.monotonic() - _wdog_last_tick[0] > 45:
                logger.critical(
                    "main: event loop FROZEN >45s — принудительный перезапуск процесса"
                )
                os.kill(os.getpid(), signal.SIGTERM)

    _wt = threading.Thread(target=_watchdog_thread, name="kitsune-watchdog", daemon=True)
    _wt.start()
    logger.info("main: watchdog started (threshold=45s)")


async def shutdown(client: Any, db: Any) -> None:
    logger.info("main: shutting down…")
    from ..session_enc import encrypt_session_file
    from .connection import _release_hydro_lock

    if getattr(client, "hydrogram", None):
        with contextlib.suppress(Exception):
            await client.hydrogram.stop()
        _release_hydro_lock()
    try:
        await db.shutdown()
    except Exception:
        logger.exception("main: db shutdown failed")
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
    try:
        sess = getattr(client, "session", None)
        sess_file = getattr(sess, "filename", None)
        if sess_file and sess_file != ":memory:":
            import sqlite3 as _sq3
            with contextlib.suppress(Exception):
                _con = _sq3.connect(sess_file)
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
    logger.info("main: goodbye 🦊")


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

    dispatcher = CommandDispatcher(client, db, security, prefix=prefix)
    dispatcher.set_owner(me.id)
    client._kitsune_dispatcher = dispatcher

    loader = Loader(client, db, dispatcher)
    client._kitsune_loader = loader

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

    translator = Translator(db)
    lang = db.get("kitsune.core", "lang", "ru")
    translator.set_language(lang)

    if not args.no_web:
        try:
            from ..web.core import WebCore
            web = WebCore(client, db)
            spawn(web.start(
                host=cfg.get("web_host", "0.0.0.0"),
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

    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    start_watchdog(stop_event)

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

    try:
        await stop_event.wait()
    finally:
        await shutdown(client, db)
