from __future__ import annotations

import re
import string
import sys
import typing

def _is_tty() -> bool:
    return sys.stdout.isatty() and sys.stdin.isatty()

def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)

def tty_print(text: str, tty: bool | None = None) -> None:
    if tty is None:
        tty = _is_tty()
    print(text if tty else _strip_ansi(text))

def tty_input(prompt: str, tty: bool | None = None) -> str:
    if tty is None:
        tty = _is_tty()
    return input(prompt if tty else _strip_ansi(prompt))

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

def _valid_api_id(value: str) -> bool:
    return value.strip().isdigit() and int(value.strip()) > 0

def _valid_api_hash(value: str) -> bool:
    v = value.strip()
    return len(v) == 32 and all(c in string.hexdigits for c in v)

def _valid_phone(value: str) -> bool:
    v = value.strip().replace(" ", "").replace("-", "")
    return v.startswith("+") and v[1:].isdigit() and 7 <= len(v) <= 16

def _ask(
    prompt: str,
    validator: typing.Callable[[str], bool] | None = None,
    secret: bool = False,
    default: str = "",
    tty: bool = True,
) -> str:
    while True:
        try:
            if secret:
                import getpass
                raw = getpass.getpass(_strip_ansi(prompt) if not tty else prompt)
            else:
                raw = tty_input(prompt, tty=tty)
        except (EOFError, KeyboardInterrupt):
            tty_print(f"\n{_R}Прервано.{_Z}", tty=tty)
            sys.exit(1)

        value = raw.strip() or default

        if not value:
            tty_print(f"  {_Y}⚠ Поле обязательно.{_Z}", tty=tty)
            continue

        if validator and not validator(value):
            tty_print(f"  {_R}✗ Некорректное значение, попробуй снова.{_Z}", tty=tty)
            continue

        return value

def api_config(tty: bool | None = None) -> dict:
    if tty is None:
        tty = _is_tty()

    line = "━" * 44

    tty_print(f"\n{_M}{line}{_Z}", tty=tty)
    tty_print(f"  🦊 {_C}Kitsune Userbot{_Z} — первоначальная настройка", tty=tty)
    tty_print(f"{_M}{line}{_Z}\n", tty=tty)
    tty_print(
        f"  Получи API ID и API Hash на {_C}https://my.telegram.org{_Z}\n"
        f"  → «API development tools» → создай приложение.\n",
        tty=tty,
    )

    api_id = _ask(
        f"  {_W}API ID{_Z}: ",
        validator=_valid_api_id,
        tty=tty,
    )

    api_hash = _ask(
        f"  {_W}API Hash{_Z}: ",
        validator=_valid_api_hash,
        tty=tty,
    )

    phone = _ask(
        f"  {_W}Номер телефона{_Z} (формат +79001234567): ",
        validator=_valid_phone,
        tty=tty,
    )

    tty_print(f"\n{_G}✓ Данные приняты. Kitsune запускается...{_Z}\n", tty=tty)

    return {
        "api_id":   int(api_id.strip()),
        "api_hash": api_hash.strip(),
        "phone":    phone.strip(),
    }

def configure_proxy(tty: bool | None = None) -> dict | None:
    if tty is None:
        tty = _is_tty()

    tty_print(f"\n  {_W}Нужен прокси? (y/N){_Z} ", tty=tty)
    try:
        answer = tty_input("  → ", tty=tty).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None

    if answer not in ("y", "yes", "да"):
        return None

    tty_print(
        f"\n  Тип прокси:\n"
        f"    {_C}1{_Z}) SOCKS5  {_C}2{_Z}) SOCKS4  {_C}3{_Z}) HTTP  {_C}4{_Z}) MTProto\n",
        tty=tty,
    )

    type_map = {"1": "SOCKS5", "2": "SOCKS4", "3": "HTTP", "4": "MTPROTO"}
    ptype_raw = _ask(f"  Выбери тип (1-4): ", tty=tty)
    ptype = type_map.get(ptype_raw.strip(), "SOCKS5")

    host = _ask(f"  Хост прокси: ", tty=tty)
    port = _ask(f"  Порт прокси: ", validator=lambda v: v.strip().isdigit(), tty=tty)

    cfg: dict = {"type": ptype, "host": host.strip(), "port": int(port.strip())}

    if ptype == "MTPROTO":
        secret = _ask(f"  MTProto secret (hex): ", tty=tty)
        cfg["secret"] = secret.strip()
    else:
        user = tty_input(f"  Логин (Enter — пропустить): ").strip()
        if user:
            pwd = _ask(f"  Пароль: ", secret=True, tty=tty)
            cfg["username"] = user
            cfg["password"] = pwd

    return cfg
