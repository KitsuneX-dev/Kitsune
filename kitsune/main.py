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

BASE_DIR = (
    "/data"
    if "DOCKER" in os.environ
    else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)
BASE_PATH   = Path(BASE_DIR)
CONFIG_PATH = BASE_PATH / "config.toml"
DATA_DIR    = Path.home() / ".kitsune"
DATA_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

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

async def _start_hydrogram(api_id: int, api_hash: str, session_name: str) -> Any | None:
    try:
        from hydrogram import Client as HydroClient
        from hydrogram.errors import AuthKeyUnregistered
    except ImportError:
        logger.info("main: hydrogram not installed, skipping secondary client")
        return None

    try:
        hydro = HydroClient(
            name=f"{session_name}_hydro",
            api_id=api_id,
            api_hash=api_hash,
            workdir=str(DATA_DIR),
            no_updates=False,
        )
        await hydro.start()
        logger.info("main: Hydrogram client started")
        return hydro
    except AuthKeyUnregistered:
        logger.warning("main: Hydrogram session invalid, skipping")
        return None
    except Exception:
        logger.exception("main: Hydrogram startup failed, continuing without it")
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

    cfg = _load_raw_config()
    api_id:   int = int(cfg.get("api_id") or os.environ.get("API_ID", 0))
    api_hash: str = str(cfg.get("api_hash") or os.environ.get("API_HASH", ""))
    prefix:   str = str(cfg.get("prefix", "."))

    session_path = DATA_DIR / "kitsune"

    from telethon.network.connection import (
        ConnectionTcpFull,
        ConnectionTcpMTProxyRandomizedIntermediate,
    )
    proxy_cfg  = cfg.get("proxy") or {}
    proxy      = None
    connection = ConnectionTcpFull
    if proxy_cfg.get("host") and proxy_cfg.get("port"):
        ptype = str(proxy_cfg.get("type", "MTPROTO")).upper()
        if ptype == "MTPROTO":
            secret     = proxy_cfg.get("secret", "00000000000000000000000000000000")
            proxy      = (str(proxy_cfg["host"]), int(proxy_cfg["port"]), secret)
            connection = ConnectionTcpMTProxyRandomizedIntermediate
            logger.info("main: MTProto proxy → %s:%s", proxy_cfg["host"], proxy_cfg["port"])
        else:
            logger.warning("main: non-MTProto proxy in config — ignored (use MTProto)")

    from .session_enc import decrypt_session_file
    decrypt_session_file()

    session_file = Path(str(session_path) + ".session")
    need_setup = (not api_id or not api_hash or not session_file.exists())

    if need_setup:
        from .web.setup import SetupServer
        web_port = int(cfg.get("web_port", 8080))
        setup = SetupServer(save_config_fn=_save_config, get_config_fn=_load_raw_config)
        await setup.start(host="0.0.0.0", port=web_port)
        await setup.wait_done()
        client = setup.get_client()
        cfg      = _load_raw_config()
        api_id   = int(cfg.get("api_id", 0))
        api_hash = str(cfg.get("api_hash", ""))
        prefix   = str(cfg.get("prefix", "."))
        client.flood_sleep_threshold = 60
        client.system_version = "1.0"
    else:
        extra = {"proxy": proxy, "connection": connection} if proxy else {}

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
            **extra,
        )

        try:
            await client.connect()
        except (TimeoutError, OSError, ConnectionError) as exc:
            print(
                "\n❌ Не удалось подключиться к Telegram.\n"
                "   Попробуй настроить прокси в config.toml:\n\n"
                "      [proxy]\n"
                "      type = \"SOCKS5\"\n"
                "      host = \"127.0.0.1\"\n"
                "      port = 1080\n\n"
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
    client.tg_id = me.id
    client.tg_me = me
    logger.info("main: logged in as %s (id=%d)", me.first_name, me.id)

    if not args.no_hydrogram:
        hydro = await _start_hydrogram(api_id, api_hash, str(session_path))
        client.hydrogram = hydro

    db = DatabaseManager(client)
    await db.init()
    client._kitsune_db = db

    security = SecurityManager(client, db)
    await security.init()

    db_prefix = db.get("kitsune.core", "prefix", None)
    if db_prefix and isinstance(db_prefix, str):
        prefix = db_prefix
    dispatcher = CommandDispatcher(client, db, security, prefix=prefix)
    dispatcher.set_owner(me.id)

    client._kitsune_dispatcher = dispatcher
    loader = Loader(client, db, dispatcher)
    client._kitsune_loader = loader
    await loader.load_all_builtin()
    await loader.load_all_user()

    translator = Translator(db)
    lang = db.get("kitsune.core", "lang", "ru")
    translator.set_language(lang)

    if not args.no_web:
        try:
            from .web.core import WebCore
            web = WebCore(client, db)
            asyncio.ensure_future(web.start(
                host=cfg.get("web_host", "0.0.0.0"),
                port=int(cfg.get("web_port", 8080)),
            ))
            logger.info("main: web interface starting on port %d", cfg.get("web_port", 8080))
        except ImportError:
            logger.info("main: web dependencies not installed, skipping web UI")
        except Exception:
            logger.exception("main: web startup failed")

    _print_banner(me)

    asyncio.ensure_future(_keepalive(client))

    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:
        logger.info("main: received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(OSError):
            asyncio.get_event_loop().add_signal_handler(sig, _shutdown)

    try:
        await stop_event.wait()
    finally:
        logger.info("main: shutting down…")
        from .session_enc import encrypt_session_file
        if client.hydrogram:
            with contextlib.suppress(Exception):
                await client.hydrogram.stop()
        await client.disconnect()
        await db.force_save()
        encrypt_session_file()
        logger.info("main: goodbye 🦊")


async def _keepalive(client: Any) -> None:
    import contextlib
    while True:
        await asyncio.sleep(30)
        try:
            if not client.is_connected():
                logger.warning("keepalive: disconnected — reconnecting")
                await client.connect()
                logger.info("keepalive: reconnected")
            else:
                await client.get_me()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("keepalive: ping failed (%s) — reconnecting", exc)
            with contextlib.suppress(Exception):
                await client.disconnect()
            await asyncio.sleep(5)
            with contextlib.suppress(Exception):
                await client.connect()

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
