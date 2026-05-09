from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

try:

    import uvloop as _uvloop

    _uvloop.install()

    _HAVE_UVLOOP = True

except ImportError:

    _HAVE_UVLOOP = False

from . import install_patches

install_patches()

BASE_DIR = (

    "/data"

    if "DOCKER" in os.environ

    else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

)

BASE_PATH   = Path(BASE_DIR)

CONFIG_PATH = BASE_PATH / "config.toml"

DATA_DIR    = Path.home() / ".kitsune"

try:

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    import os as _os, stat as _stat

    _mode = _stat.S_IMODE(DATA_DIR.stat().st_mode)

    if not (_mode & _stat.S_IWUSR):

        _os.chmod(DATA_DIR, 0o755)

except Exception:

    pass

logger = logging.getLogger(__name__)

_BG_TASKS: set[asyncio.Task] = set()

def _spawn(coro) -> asyncio.Task:

    task = asyncio.ensure_future(coro)

    _BG_TASKS.add(task)

    task.add_done_callback(_BG_TASKS.discard)

    return task

_config_cache: dict[str, Any] | None = None

_config_mtime: float = 0.0

def _load_raw_config() -> dict[str, Any]:

    global _config_cache, _config_mtime

    if CONFIG_PATH.exists():

        try:

            mt = CONFIG_PATH.stat().st_mtime

        except OSError:

            mt = 0.0

        if _config_cache is not None and mt == _config_mtime:

            return _config_cache

        try:

            import toml

            data = toml.loads(CONFIG_PATH.read_text(encoding="utf-8"))

            _config_cache = data

            _config_mtime = mt

            return data

        except Exception:

            logger.exception("main: failed to parse config.toml")

            if _config_cache is not None:

                return _config_cache

    legacy = BASE_PATH / "config.json"

    if legacy.exists():

        with contextlib.suppress(Exception):

            data = json.loads(legacy.read_text(encoding="utf-8"))

            logger.info("main: migrating config.json → config.toml")

            _save_config(data)

            return data

    return {}

def _invalidate_config_cache() -> None:

    global _config_cache, _config_mtime

    _config_cache = None

    _config_mtime = 0.0

def _save_config(data: dict[str, Any]) -> None:

    try:

        import toml

        CONFIG_PATH.write_text(toml.dumps(data), encoding="utf-8")

        _invalidate_config_cache()

    except Exception:

        logger.exception("main: failed to save config.toml")

def get_config_key(key: str, default: Any = None) -> Any:

    return _load_raw_config().get(key, default)

def set_config_key(key: str, value: Any) -> None:

    data = _load_raw_config()

    data[key] = value

    _save_config(data)

async def _interactive_login(client: Any) -> None:

    from telethon.errors import (

        ApiIdInvalidError,

        AuthKeyDuplicatedError,

        FloodWaitError,

        PasswordHashInvalidError,

        PhoneNumberInvalidError,

        SessionPasswordNeededError,

    )

    phone = input("📱 Phone number (international format): ").strip()

    try:

        await client.send_code_request(phone)

    except FloodWaitError as exc:

        print(f"⏳ Flood wait: {exc.seconds}s. Please try again later.")

        sys.exit(1)

    except PhoneNumberInvalidError:

        print("❌ Invalid phone number.")

        sys.exit(1)

    code = input("🔑 Telegram code: ").strip()

    try:

        await client.sign_in(phone, code)

    except SessionPasswordNeededError:

        from getpass import getpass

        pwd = getpass("🔐 Two-factor password: ")

        try:

            await client.sign_in(password=pwd)

        except PasswordHashInvalidError:

            print("❌ Wrong password.")

            sys.exit(1)

    except ApiIdInvalidError:

        print("❌ Invalid API ID / API Hash. Check your config.")

        sys.exit(1)

    except AuthKeyDuplicatedError:

        print("❌ Session duplicated. Delete session file and retry.")

        sys.exit(1)

_HYDRO_LOCK_FILE = DATA_DIR / ".hydrogram.lock"
_hydro_lock_fd: int | None = None

def _acquire_hydro_lock() -> bool:
    global _hydro_lock_fd
    try:
        import fcntl
    except ImportError:
        return True
    try:
        fd = os.open(str(_HYDRO_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        _hydro_lock_fd = fd
        return True
    except Exception:
        return True

def _release_hydro_lock() -> None:
    global _hydro_lock_fd
    if _hydro_lock_fd is None:
        return
    try:
        import fcntl
        fcntl.flock(_hydro_lock_fd, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        os.close(_hydro_lock_fd)
    except Exception:
        pass
    _hydro_lock_fd = None
    with contextlib.suppress(Exception):
        _HYDRO_LOCK_FILE.unlink(missing_ok=True)

async def _start_hydrogram(api_id: int, api_hash: str, session_name: str) -> Any | None:

    hydro_session_file = DATA_DIR / f"{Path(session_name).name}_hydro.session"

    if not hydro_session_file.exists():

        logger.info("main: Hydrogram session not found, skipping to avoid console prompt")

        return None

    if not _acquire_hydro_lock():

        logger.warning(
            "main: another Kitsune instance already holds Hydrogram lock — skipping to avoid session-id war"
        )

        try:
            from .core.reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("another instance holds the session lock")
        except Exception:
            pass

        return None

    try:

        from hydrogram import Client as HydroClient
        from hydrogram.errors import AuthKeyUnregistered

    except ImportError:

        logger.info("main: hydrogram not installed, skipping secondary client")

        try:
            from .core.reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("hydrogram package not installed")
        except Exception:
            pass
        _release_hydro_lock()
        return None

    try:

        kwargs: dict = dict(

            name=str(DATA_DIR / f"{Path(session_name).name}_hydro"),

            api_id=api_id,

            api_hash=api_hash,

            workdir=str(DATA_DIR),

            no_updates=True,

            takeout=False,

        )

        try:

            import inspect

            sig = inspect.signature(HydroClient.__init__)

            if "sleep_threshold" in sig.parameters:

                kwargs["sleep_threshold"] = 60

            if "max_concurrent_transmissions" in sig.parameters:

                kwargs["max_concurrent_transmissions"] = 1

            if "device_model" in sig.parameters:

                kwargs["device_model"] = "Kitsune Userbot (media)"

            if "app_version" in sig.parameters:

                kwargs["app_version"] = "1.0.0"

            if "system_version" in sig.parameters:

                kwargs["system_version"] = "1.0"

            if "lang_code" in sig.parameters:

                kwargs["lang_code"] = "ru"

        except Exception:

            pass

        hydro = HydroClient(**kwargs)

        try:

            await asyncio.wait_for(hydro.start(), timeout=45.0)

        except asyncio.TimeoutError:

            logger.warning("main: Hydrogram start() timed out after 45s, skipping")

            with contextlib.suppress(Exception):
                await hydro.stop()

            try:
                from .core.reliability import flags as _deg_flags
                _deg_flags.mark_hydrogram_failed("startup timeout")
            except Exception:
                pass

            _release_hydro_lock()
            return None

        logger.info("main: Hydrogram client started (no_updates=True, lock acquired)")

        try:
            from .core.reliability import flags as _deg_flags
            _deg_flags.clear_hydrogram_failed()
        except Exception:
            pass

        return hydro

    except AuthKeyUnregistered:

        logger.warning("main: Hydrogram session invalid, skipping")

        try:
            from .core.reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed("AuthKeyUnregistered")
        except Exception:
            pass

        _release_hydro_lock()

        return None

    except Exception as _exc:

        logger.exception("main: Hydrogram startup failed, continuing without it")

        try:
            from .core.reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed(f"startup: {type(_exc).__name__}")
        except Exception:
            pass

        _release_hydro_lock()

        return None

async def _startup(args: argparse.Namespace) -> None:

    from . import log, utils
    from .tl_cache import KitsuneTelegramClient
    from .database import DatabaseManager
    from .core.security import SecurityManager
    from .core.dispatcher import CommandDispatcher
    from .core.loader import Loader
    from .translations import Translator

    log.init()

    if _HAVE_UVLOOP:

        logger.info("main: uvloop enabled")

    cfg = _load_raw_config()

    api_id:   int = int(cfg.get("api_id") or os.environ.get("API_ID", 0))

    api_hash: str = str(cfg.get("api_hash") or os.environ.get("API_HASH", ""))

    prefix:   str = str(cfg.get("prefix", "."))

    session_path = DATA_DIR / "kitsune"

    from telethon.network.connection import (

        ConnectionTcpFull,

    )

    proxy_cfg  = cfg.get("proxy") or {}

    proxy      = None

    connection = ConnectionTcpFull

    from .rkn_bypass import ensure_python_socks as _ensure_python_socks

    if isinstance(proxy_cfg, dict) and proxy_cfg.get("host") and proxy_cfg.get("port"):

        ptype = str(proxy_cfg.get("type", "MTPROTO")).upper()

        host  = str(proxy_cfg["host"])

        port  = int(proxy_cfg["port"])

        if not _ensure_python_socks():

            logger.error(

                "main: python-socks недоступен — прокси %s://%s:%d будет пропущен.",

                ptype, host, port,

            )

        elif ptype == "MTPROTO":

            secret     = proxy_cfg.get("secret", "00000000000000000000000000000000")

            from .rkn_bypass import get_mtproto_connection_class, normalize_secret

            secret     = normalize_secret(str(secret))

            proxy      = (host, port, secret)

            connection = get_mtproto_connection_class(secret)

            logger.info("main: MTProto proxy → %s:%s (%s)", host, port, connection.__name__)

        elif ptype in ("SOCKS5", "SOCKS4", "HTTP", "HTTPS"):

            try:

                import socks as _socks

                _type_map = {

                    "SOCKS5": _socks.SOCKS5,

                    "SOCKS4": _socks.SOCKS4,

                    "HTTP":   _socks.HTTP,

                    "HTTPS":  _socks.HTTP,

                }

                proxy = (

                    _type_map.get(ptype, _socks.SOCKS5),

                    host, port, True,

                    proxy_cfg.get("username") or None,

                    proxy_cfg.get("password") or None,

                )

                logger.info("main: %s proxy → %s:%s", ptype, host, port)

            except ImportError:

                logger.warning(

                    "main: PySocks не установлен (pip install PySocks) — SOCKS-прокси отключён"

                )

        else:

            logger.warning("main: неизвестный тип прокси '%s' — игнорирую", ptype)

    from .session_enc import (

        decrypt_session_file, _fix_session_permissions,

        _ensure_data_dir, _fix_db_readonly, _fix_all_permissions,

    )

    _fix_all_permissions()

    decrypt_session_file()

    session_file = Path(str(session_path) + ".session")

    if session_file.exists():

        _fix_session_permissions()

        _fix_db_readonly()

    need_setup = (not api_id or not api_hash or not session_file.exists())

    if need_setup:

        from .web.setup import SetupServer

        web_port = int(cfg.get("web_port", 8080))

        setup = SetupServer(save_config_fn=_save_config, get_config_fn=_load_raw_config)

        await setup.start(host="0.0.0.0", port=web_port)

        await setup.wait_done()

        client = setup.get_client()

        _fix_session_permissions()

        _fix_db_readonly()

        cfg      = _load_raw_config()

        api_id   = int(cfg.get("api_id", 0))

        api_hash = str(cfg.get("api_hash", ""))

        prefix   = str(cfg.get("prefix", "."))

        client.flood_sleep_threshold = 60

        client.system_version = "1.0"

    else:

        extra = {"proxy": proxy, "connection": connection} if proxy else {}

        if proxy:

            from .rkn_bypass import (

                test_connection as _proxy_tcp_check,

                mtproxy_handshake_check as _proxy_hs_check,

            )

            _phost = proxy_cfg.get("host")

            _pport = int(proxy_cfg.get("port") or 443)

            _psecret = str(proxy_cfg.get("secret") or "")

            logger.info("main: проверяю TCP-доступность прокси %s:%d…", _phost, _pport)

            _proxy_alive = await _proxy_tcp_check(_phost, _pport, timeout=8.0)

            if not _proxy_alive:

                logger.warning(

                    "main: прокси %s:%d НЕ отвечает на TCP за 8s — пропускаю и иду на fallback",

                    _phost, _pport,

                )

                extra = {}

            else:

                logger.info(

                    "main: TCP OK, проверяю MTProto handshake %s:%d…", _phost, _pport,

                )

                _hs_ok = await _proxy_hs_check(_phost, _pport, _psecret, timeout=10.0)

                if _hs_ok:

                    logger.info(

                        "main: handshake OK — поднимаю основное соединение через %s:%d",

                        _phost, _pport,

                    )

                else:

                    logger.warning(

                        "main: прокси %s:%d отвечает на TCP, но MTProto handshake провален. Иду на fallback.",

                        _phost, _pport,

                    )

                    extra = {}

        client = KitsuneTelegramClient(

            str(session_path),

            api_id=api_id,

            api_hash=api_hash,

            connection_retries=3,

            retry_delay=2,

            auto_reconnect=True,

            flood_sleep_threshold=60,

            device_model="Kitsune Userbot",

            system_version="1.0",

            app_version="1.0.0",

            lang_code="ru",

            **extra,

        )

        try:

            await asyncio.wait_for(client.connect(), timeout=30.0)

            logger.info("main: client.connect() OK")

        except (TimeoutError, OSError, ConnectionError, asyncio.TimeoutError) as exc:

            logger.warning("main: connection failed (%s: %s), trying RKN bypass…",

                           type(exc).__name__, exc)

            with contextlib.suppress(Exception):

                await client.disconnect()

            from .rkn_bypass import find_working_proxy, get_mtproto_connection_class

            if not _ensure_python_socks():

                print(

                    "\n❌ Не удалось подключиться к Telegram, а RKNBypass требует python-socks.\n"

                    "   Установи вручную: pip install 'python-socks[asyncio]'\n"

                )

                sys.exit(1)

            try:

                proxy_info = await find_working_proxy(deep_check=True)

            except Exception as _exc:

                logger.exception("main: find_working_proxy() failed: %s", _exc)

                proxy_info = None

            if proxy_info:

                host, port, secret = proxy_info

                logger.info("main: using MTProto proxy %s:%d for RKN bypass", host, port)

                conn_cls = get_mtproto_connection_class(secret)

                client = KitsuneTelegramClient(

                    str(session_path),

                    api_id=api_id,

                    api_hash=api_hash,

                    connection_retries=10,

                    retry_delay=3,

                    auto_reconnect=True,

                    flood_sleep_threshold=60,

                    device_model="Kitsune Userbot",

                    system_version="1.0",

                    app_version="1.0.0",

                    lang_code="ru",

                    proxy=(host, port, secret),

                    connection=conn_cls,

                )

                try:

                    cfg["proxy"] = {

                        "type":   "MTPROTO",

                        "host":   host,

                        "port":   int(port),

                        "secret": secret,

                    }

                    _save_config(cfg)

                    logger.info("main: рабочий MTProto-прокси сохранён в config.toml")

                except Exception:

                    logger.exception("main: не удалось сохранить прокси в config.toml")

                try:

                    await asyncio.wait_for(client.connect(), timeout=30.0)

                    logger.info("main: RKN-bypass client.connect() OK")

                except (TimeoutError, OSError, ConnectionError, asyncio.TimeoutError) as exc2:

                    logger.error(

                        "main: RKN-bypass прокси %s:%d тоже не отвечает (%s)",

                        host, port, exc2,

                    )

                    print(

                        "\n❌ Найденный RKN-bypass прокси оказался нерабочим.\n"

                        "   Попробуй .findproxy после старта или укажи прокси вручную.\n"

                    )

                    sys.exit(1)

            else:

                print(

                    "\n❌ Не удалось подключиться к Telegram.\n"

                    "   Текущий прокси из config.toml не отвечает на MTProto handshake,\n"

                    "   а публичные fallback-прокси тоже не сработали.\n\n"

                    "   Попробуй настроить прокси вручную в config.toml:\n\n"

                    "      [proxy]\n"

                    "      type = \"MTPROTO\"\n"

                    "      host = \"149.154.175.100\"\n"

                    "      port = 443\n"

                    "      secret = \"ee9000000000000000000000000000003900000000000000\"\n\n"

                    "   Или возьми свежий прокси из @MTProxyT / @proxyme и подставь его:\n"

                    "      .setproxy <host> <port> <secret>\n\n"

                    f"   Детали: {exc}\n"

                )

                sys.exit(1)

        session_size = session_file.stat().st_size if session_file.exists() else 0

        if session_size < 100:

            logger.info("main: session file too small (%d bytes), launching web setup", session_size)

            from .web.setup import SetupServer

            web_port = int(cfg.get("web_port", 8080))

            setup = SetupServer(save_config_fn=_save_config, get_config_fn=_load_raw_config)

            await setup.start(host="0.0.0.0", port=web_port)

            await setup.wait_done()

            client = setup.get_client()

        else:

            logger.info("main: session file OK (%d bytes), skipping auth check", session_size)

    me = await client.get_me()

    if me is None:

        logger.warning("main: get_me() returned None — session may be stale, checking authorization…")

        try:

            authorized = await client.is_user_authorized()

        except Exception:

            authorized = False

        if not authorized:

            logger.warning("main: not authorized — re-launching web setup to re-authenticate…")

            with contextlib.suppress(Exception):

                await client.disconnect()

            from .web.setup import SetupServer

            web_port = int(cfg.get("web_port", 8080))

            setup = SetupServer(save_config_fn=_save_config, get_config_fn=_load_raw_config)

            await setup.start(host="0.0.0.0", port=web_port)

            await setup.wait_done()

            client = setup.get_client()

            me = await client.get_me()

        else:

            logger.info("main: authorized but get_me() returned None — retrying after delay…")

            await asyncio.sleep(2)

            me = await client.get_me()

    if me is None:

        raise RuntimeError(
            "main: get_me() returned None after all retries — "
            "delete the session file and re-authenticate."
        )

    client.tg_id = me.id

    client.tg_me = me

    logger.info("main: logged in as %s (id=%d)", me.first_name, me.id)

    # Phase 3: предварительно регистрируем circuit breaker'ы в реестре,
    # чтобы /health видел их с самого старта.
    try:
        from .core.reliability import get_breaker
        get_breaker("telegram_api", failure_threshold=5, cooldown=60.0)
        get_breaker("redis_io", failure_threshold=3, cooldown=30.0)
        get_breaker("hydrogram_io", failure_threshold=3, cooldown=300.0)
    except Exception:
        logger.debug("main: reliability breakers preregister failed", exc_info=True)

    hydro = None

    if not args.no_hydrogram:

        hydro = await _start_hydrogram(api_id, api_hash, str(session_path))

        client.hydrogram = hydro

    db = DatabaseManager(client)

    await db.init()

    client._kitsune_db = db

    security = SecurityManager(client, db)

    await security.init()

    client._kitsune_security = security

    db_prefix = db.get("kitsune.core", "prefix", None)

    if db_prefix and isinstance(db_prefix, str):

        prefix = db_prefix

    dispatcher = CommandDispatcher(client, db, security, prefix=prefix)

    dispatcher.set_owner(me.id)

    if hydro:

        from .core.hydro_bridge import setup_hydrogram_bridge

        await setup_hydrogram_bridge(hydro, client, dispatcher, db)

        logger.info("main: HydrogramBridge active — single dispatcher for both clients")

    client._kitsune_dispatcher = dispatcher

    loader = Loader(client, db, dispatcher)

    client._kitsune_loader = loader

    await asyncio.gather(
        loader.load_all_builtin(),
        loader.load_all_user(),
    )

    translator = Translator(db)

    lang = db.get("kitsune.core", "lang", "ru")

    translator.set_language(lang)

    if not args.no_web:

        try:

            from .web.core import WebCore

            web = WebCore(client, db)

            _spawn(web.start(

                host=cfg.get("web_host", "0.0.0.0"),

                port=int(cfg.get("web_port", 8080)),

            ))

            logger.info("main: web interface starting on port %d", cfg.get("web_port", 8080))

        except ImportError:

            logger.info("main: web dependencies not installed, skipping web UI")

        except Exception:

            logger.exception("main: web startup failed")

    _spawn(log.setup_tg_logging(client))

    _spawn(_setup_kitsune_folder(client, db))

    _print_banner(me)

    _spawn(_keepalive(client))

    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:

        logger.info("main: received shutdown signal")

        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):

        with contextlib.suppress(OSError):

            asyncio.get_event_loop().add_signal_handler(sig, _shutdown)

    import threading, time as _time

    _wdog_last_tick = [_time.monotonic()]

    _wdog_loop = asyncio.get_event_loop()

    async def _wdog_tick() -> None:

        _wdog_last_tick[0] = _time.monotonic()

    def _watchdog_thread() -> None:

        while not stop_event.is_set():

            _time.sleep(10)

            try:

                asyncio.run_coroutine_threadsafe(_wdog_tick(), _wdog_loop)

            except Exception:

                pass

            _time.sleep(5)

            if _time.monotonic() - _wdog_last_tick[0] > 45:

                logger.critical("main: event loop FROZEN >45s — принудительный перезапуск процесса")

                import os

                os.kill(os.getpid(), signal.SIGTERM)

    _wt = threading.Thread(target=_watchdog_thread, name="kitsune-watchdog", daemon=True)

    _wt.start()

    logger.info("main: watchdog started (threshold=45s)")

    # ────────────────────────────────────────────────────────────────
    # КРИТИЧЕСКИ ВАЖНО: после client.connect() Telethon НЕ получает
    # апдейты автоматически — нужно явно запустить updates-loop.
    # Без этого add_event_handler(events.NewMessage(...)) никогда не
    # вызывается, и юзербот выглядит «мёртвым»: команды не отвечают,
    # watcher'ы не срабатывают, /start у бота-нотифаера тоже мимо.
    # ────────────────────────────────────────────────────────────────
    # Стартуем цикл получения апдейтов ОДИН раз, до await stop_event.wait().
    # client.run_until_disconnected() — это именно то, что
    # "включает" доставку NewMessage/MessageEdited/etc.
    # Без этого вызова add_event_handler регистрируется, но никогда
    # не вызывается — и любые команды/watcher'ы молчат. Именно это
    # приводило к «гробовой тишине» в логах.
    try:
        # Подтягиваем пропущенные апдейты — чтобы не потерять сообщения,
        # пришедшие пока юзербот был оффлайн.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(client.catch_up(), timeout=15.0)

        # Регистрируем run_until_disconnected() как фоновую задачу.
        # Она будет жить рядом с stop_event.wait() и внутри Telethon
        # запустит все нужные внутренние циклы для обработки апдейтов.
        _spawn(client.run_until_disconnected())
        logger.info("main: Telethon update loop started (run_until_disconnected)")
    except Exception:
        logger.exception(
            "main: failed to start update loop — "
            "commands and watchers will NOT work until this is fixed!"
        )

    try:

        await stop_event.wait()

    finally:

        logger.info("main: shutting down…")

        from .session_enc import encrypt_session_file

        if client.hydrogram:

            with contextlib.suppress(Exception):

                await client.hydrogram.stop()

            _release_hydro_lock()

        try:

            await db.shutdown()

        except Exception:

            logger.exception("main: db shutdown failed")

        try:

            encrypt_session_file()

        except Exception:

            logger.exception("main: session encrypt failed")

        await client.disconnect()

        logger.info("main: goodbye 🦊")

async def _safe_force_reconnect(client: Any) -> bool:

    """Phase 3: выполнить reconnect с экспоненциальным backoff.

    При отвале VPN/прокси делаем до 5 попыток (1с → 2с → 4с → 8с → 16с),
    помечаем degradation flag «vpn_down» пока идёт retry-цикл.
    """

    sender = getattr(client, "_sender", None)

    if sender is not None:

        for attr in ("_send_loop_handle", "_recv_loop_handle"):

            handle = getattr(sender, attr, None)

            if handle is None or handle.done():

                continue

            with contextlib.suppress(Exception):

                handle.cancel()

        for attr in ("_send_loop_handle", "_recv_loop_handle"):

            handle = getattr(sender, attr, None)

            if handle is None:

                continue

            with contextlib.suppress(Exception, asyncio.CancelledError, RuntimeError):

                await asyncio.wait_for(asyncio.shield(handle), timeout=2.0)

    with contextlib.suppress(Exception, RuntimeError):

        await client.disconnect()

    disc = getattr(sender, "_disconnected", None) if sender is not None else None

    if disc is not None:

        with contextlib.suppress(Exception, asyncio.CancelledError, RuntimeError):

            await asyncio.wait_for(asyncio.shield(disc), timeout=3.0)

    await asyncio.sleep(0.2)

    # Phase 3: retry с backoff
    try:
        from .core.reliability import retry_with_backoff, RetryPolicy, flags as _deg_flags
    except Exception:
        try:
            await asyncio.wait_for(client.connect(), timeout=30.0)
            return True
        except Exception as exc:
            logger.debug("keepalive: forced reconnect failed (%s: %s)",
                         type(exc).__name__, exc)
            return False

    _deg_flags.mark_vpn_down("keepalive: hard reconnect cycle")

    async def _do_connect() -> bool:
        await asyncio.wait_for(client.connect(), timeout=30.0)
        return True

    try:
        await retry_with_backoff(
            _do_connect,
            policy=RetryPolicy(
                base_delay=1.0,
                max_delay=16.0,
                multiplier=2.0,
                jitter=0.25,
                max_attempts=5,
            ),
            name="telegram_reconnect",
            expected_exceptions=(
                TimeoutError, asyncio.TimeoutError,
                ConnectionError, OSError,
            ),
        )
        _deg_flags.clear_vpn_down()
        return True
    except Exception as exc:
        logger.debug(
            "keepalive: forced reconnect failed after retries (%s: %s)",
            type(exc).__name__, exc,
        )
        return False

def _is_link_alive(client: Any) -> bool:

    try:

        if not client.is_connected():

            return False

    except Exception:

        return False

    sender = getattr(client, "_sender", None)

    if sender is None:

        return False

    conn = getattr(sender, "_connection", None)

    if conn is None:

        return False

    disc = getattr(sender, "_disconnected", None)

    if disc is not None:

        try:

            if disc.done():

                return False

        except Exception:

            pass

    return True

async def _keepalive(client: Any) -> None:

    HARD_RECONNECT_AFTER_S = 300

    PING_INTERVAL_S        = 60

    fail_streak_started: float | None = None

    attempts: int = 0

    try:
        from .core.reliability import flags as _deg_flags
    except Exception:
        _deg_flags = None

    while True:

        try:

            await asyncio.sleep(PING_INTERVAL_S)

        except asyncio.CancelledError:

            break

        try:

            if not _is_link_alive(client):

                raise ConnectionError("client disconnected")

            if fail_streak_started is not None:

                logger.info(

                    "keepalive: соединение восстановлено (после %d попыт(ок))",

                    attempts,

                )
                # Phase 3: снимаем флаг vpn_down при восстановлении
                if _deg_flags is not None:
                    try: _deg_flags.clear_vpn_down()
                    except Exception: pass

            fail_streak_started = None

            attempts = 0

        except asyncio.CancelledError:

            break

        except Exception as exc:

            import time as _time

            now = _time.monotonic()

            if fail_streak_started is None:

                fail_streak_started = now

            attempts += 1

            elapsed = now - fail_streak_started

            logger.debug(

                "keepalive: link down (%s: %s) — попытка %d, серия %.0fs",

                type(exc).__name__, exc, attempts, elapsed,

            )

            if elapsed < HARD_RECONNECT_AFTER_S:

                continue

            logger.warning(

                "keepalive: %d неудачных проверок за ~%.0fs — жёсткий reconnect",

                attempts, elapsed,

            )

            ok = await _safe_force_reconnect(client)

            if ok:

                logger.info(

                    "keepalive: hard reconnect успешен (после %d попыт(ок))",

                    attempts,

                )

                fail_streak_started = None

                attempts = 0

            else:

                fail_streak_started = now

async def _setup_kitsune_folder(client: Any, db: Any) -> None:

    await asyncio.sleep(8)

    try:

        from .utils import ensure_kitsune_folder

        await ensure_kitsune_folder(client, db)

    except Exception:

        pass

def _print_banner(me: Any) -> None:

    from .version import __version_str__
    from colorama import Fore, Style, init as colorama_init

    colorama_init(autoreset=True)

    print(

        f"\n{Fore.MAGENTA}{'━' * 42}{Style.RESET_ALL}\n"

        f"  🦊 {Fore.CYAN}Kitsune Userbot{Style.RESET_ALL} v{__version_str__}\n"

        f"  👤 {me.first_name} (id: {me.id})\n"

        f"  👨‍💻 Developer: Yushi — @Mikasu32\n"

        f"{Fore.MAGENTA}{'━' * 42}{Style.RESET_ALL}\n"

    )

def parse_args() -> argparse.Namespace:

    p = argparse.ArgumentParser(description="Kitsune Userbot")

    p.add_argument("--no-web",       action="store_true", help="Disable web interface")

    p.add_argument("--no-hydrogram", action="store_true", help="Disable Hydrogram secondary client")

    p.add_argument("--debug",        action="store_true", help="Enable DEBUG logging")

    return p.parse_args()

def main() -> None:

    args = parse_args()

    if args.debug:

        logging.getLogger().setLevel(logging.DEBUG)

    try:

        asyncio.run(_startup(args))

    except KeyboardInterrupt:

        pass
