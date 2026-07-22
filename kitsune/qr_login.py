from __future__ import annotations
import asyncio
import contextlib
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from colorama import Fore, Style, init as _cinit
    _cinit(autoreset=True)
    _C = Fore.CYAN
    _M = Fore.MAGENTA
    _G = Fore.GREEN
    _Y = Fore.YELLOW
    _R = Fore.RED
    _W = Style.BRIGHT
    _Z = Style.RESET_ALL
except ImportError:
    _C = _M = _G = _Y = _R = _W = _Z = ""

_QR_RECREATE_INTERVAL: float = 25.0
_QR_TOTAL_TIMEOUT: float = 600.0


def _is_tty() -> bool:
    return sys.stdout.isatty() and sys.stdin.isatty()


def ask_login_method(tty: bool | None = None) -> bool:
    if tty is None:
        tty = _is_tty()
    if not tty:
        return False
    line = "━" * 44
    print(f"\n{_M}{line}{_Z}")
    print(f"  🦊 {_C}Kitsune Userbot{_Z} — выбор способа входа")
    print(f"{_M}{line}{_Z}\n")
    print(f"  {_W}Хочешь войти через QR-код (как в Telegram Desktop)?{_Z}")
    print(f"    {_C}Y{_Z} — да, ввести API_ID/API_HASH в консоли и показать QR")
    print(f"    {_C}N{_Z} — нет, открыть веб-страницу для регистрации/входа\n")
    while True:
        try:
            choice = input(f"  → {_W}Выбор [Y/N]{_Z}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_R}Прервано.{_Z}")
            sys.exit(1)
        if choice in ("y", "yes", "д", "да"):
            return True
        if choice in ("n", "no", "н", "нет", ""):
            return False
        print(f"  {_Y}⚠ Введи Y или N.{_Z}")


def _ask_api_credentials() -> tuple[int, str]:
    from .configurator import _ask, _valid_api_id, _valid_api_hash
    line = "━" * 44
    print(f"\n{_M}{line}{_Z}")
    print(f"  🦊 {_C}QR-вход{_Z} — нужны API ID и API Hash")
    print(f"{_M}{line}{_Z}\n")
    print(
        f"  Получи их на {_C}https://my.telegram.org{_Z}\n"
        f"  → «API development tools» → создай приложение.\n"
    )
    api_id_raw = _ask(f"  {_W}API ID{_Z}: ", validator=_valid_api_id, tty=True)
    api_hash_raw = _ask(f"  {_W}API Hash{_Z}: ", validator=_valid_api_hash, tty=True)
    return int(api_id_raw.strip()), api_hash_raw.strip()


def _print_qr(url: str) -> None:
    from .qr import make_qr_text
    try:
        qr_text = make_qr_text(url)
    except Exception as exc:
        logger.warning("qr_login: make_qr_text failed: %s", exc)
        qr_text = ""
    print("\n" + qr_text)
    print(f"\n  {_W}🦊 Отсканируй QR-код в Telegram{_Z}")
    print(f"     Settings → Devices → Link Desktop Device\n")
    print(f"  {_C}Или открой вручную:{_Z} {url}\n")


async def _qr_wait_loop(qr_login: Any) -> Any:
    deadline = asyncio.get_event_loop().time() + _QR_TOTAL_TIMEOUT
    while True:
        _print_qr(qr_login.url)
        now = asyncio.get_event_loop().time()
        remaining = deadline - now
        if remaining <= 0:
            raise asyncio.TimeoutError("QR login overall timeout exceeded")
        step = min(_QR_RECREATE_INTERVAL, remaining)
        try:
            return await asyncio.wait_for(asyncio.shield(qr_login.wait()), timeout=step)
        except asyncio.TimeoutError:
            pass
        if asyncio.get_event_loop().time() >= deadline:
            raise asyncio.TimeoutError("QR login overall timeout exceeded")
        try:
            await qr_login.recreate()
        except Exception as exc:
            logger.warning("qr_login: recreate failed: %s", exc)
            raise


async def _handle_2fa(client: Any) -> Any:
    from telethon.errors import PasswordHashInvalidError, FloodWaitError
    from getpass import getpass
    print(f"\n  {_Y}🔐 Включена двухфакторная аутентификация.{_Z}")
    for _ in range(3):
        try:
            password = getpass(f"  {_W}Пароль 2FA{_Z}: ")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_R}Прервано.{_Z}")
            sys.exit(1)
        password = (password or "").strip()
        if not password:
            print(f"  {_Y}⚠ Пароль не может быть пустым.{_Z}")
            continue
        try:
            return await client.sign_in(password=password)
        except PasswordHashInvalidError:
            print(f"  {_R}✗ Неверный пароль, попробуй ещё раз.{_Z}")
        except FloodWaitError as exc:
            print(f"  {_R}⏳ Flood wait: {exc.seconds}s.{_Z}")
            sys.exit(1)
    print(f"  {_R}✗ Слишком много неверных попыток.{_Z}")
    sys.exit(1)


async def run_console_qr_login(
    cfg: dict[str, Any],
    save_config_fn,
    get_config_fn,
    session_path: Path,
) -> Any:
    from telethon.errors import (
        SessionPasswordNeededError,
        ApiIdInvalidError,
        FloodWaitError,
    )
    from .core.connection import build_proxy, verify_proxy, build_telethon_client

    api_id, api_hash = _ask_api_credentials()

    fresh_cfg = get_config_fn() or {}
    fresh_cfg["api_id"] = api_id
    fresh_cfg["api_hash"] = api_hash
    save_config_fn(fresh_cfg)
    cfg.update(fresh_cfg)

    session_file = Path(str(session_path) + ".session")
    for suf in ("", "-wal", "-shm", "-journal"):
        target = Path(str(session_file) + suf)
        with contextlib.suppress(Exception):
            if target.exists():
                target.unlink()

    proxy, connection = build_proxy(cfg)
    if proxy:
        ok = await verify_proxy(cfg)
        if not ok:
            proxy = None
            connection = None

    client = build_telethon_client(session_path, api_id, api_hash, proxy, connection)

    print(f"\n  {_C}🌐 Подключаюсь к Telegram…{_Z}")
    try:
        await asyncio.wait_for(client.connect(), timeout=30)
    except asyncio.TimeoutError:
        print(f"  {_R}✗ Не удалось подключиться (timeout). Проверь интернет.{_Z}")
        sys.exit(1)
    except ApiIdInvalidError:
        print(f"  {_R}✗ Невалидные API_ID / API_HASH.{_Z}")
        sys.exit(1)

    try:
        qr_login = await client.qr_login()
    except Exception as exc:
        logger.exception("qr_login: client.qr_login() failed")
        print(f"  {_R}✗ Не удалось создать QR-сессию: {exc}{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)

    try:
        await _qr_wait_loop(qr_login)
    except SessionPasswordNeededError:
        await _handle_2fa(client)
    except asyncio.TimeoutError:
        print(f"  {_R}✗ Время ожидания QR-входа истекло.{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)
    except FloodWaitError as exc:
        print(f"  {_R}⏳ Flood wait: {exc.seconds}s.{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{_R}Прервано.{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)
    except Exception as exc:
        logger.exception("qr_login: wait loop failed")
        print(f"  {_R}✗ QR-вход не удался: {exc}{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)

    try:
        me = await client.get_me()
    except Exception as exc:
        logger.exception("qr_login: get_me() failed")
        print(f"  {_R}✗ Не удалось получить данные пользователя: {exc}{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)

    if me is None:
        print(f"  {_R}✗ Авторизация прошла, но get_me() вернул None.{_Z}")
        with contextlib.suppress(Exception):
            await client.disconnect()
        sys.exit(1)

    try:
        client.session.save()
    except Exception:
        logger.debug("qr_login: session.save() raised", exc_info=True)

    name = getattr(me, "first_name", "") or "user"
    print(f"\n  {_G}✓ Авторизация прошла успешно!{_Z}")
    print(f"  {_W}👤 {name}{_Z}  |  id: {me.id}\n")

    client.flood_sleep_threshold = 60
    client.system_version = "1.0"
    client.tg_id = me.id
    client.tg_me = me
    return client
