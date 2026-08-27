from __future__ import annotations
import logging
import os
import sys
import typing

logger = logging.getLogger(__name__)

_interactive: bool | None = None
_tty_stream: typing.Any = None
_tty_failed = False


def _tty_readable() -> bool:
    if os.name == "nt":
        return False
    try:
        return os.access("/dev/tty", os.R_OK)
    except Exception:
        return False


def is_interactive() -> bool:
    global _interactive
    if _interactive is not None:
        return _interactive
    result = False
    try:
        if sys.stdin is not None and sys.stdout is not None:
            if sys.stdin.isatty() and sys.stdout.isatty():
                result = True
    except Exception:
        logger.debug("console: isatty() failed", exc_info=True)
    if not result:
        result = _tty_readable()
    _interactive = bool(result)
    return _interactive


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin is not None and sys.stdin.isatty())
    except Exception:
        return False


def _get_tty_stream() -> typing.Any:
    global _tty_stream, _tty_failed
    if _tty_stream is not None:
        return _tty_stream
    if _tty_failed or os.name == "nt":
        return None
    try:
        _tty_stream = open("/dev/tty", "r", errors="replace")
    except Exception:
        _tty_failed = True
        _tty_stream = None
        logger.debug("console: /dev/tty недоступен", exc_info=True)
    return _tty_stream


def prompt(text: str = "") -> str:
    if _stdin_is_tty():
        return input(text)
    stream = _get_tty_stream()
    if stream is None:
        return input(text)
    try:
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
        line = stream.readline()
    except (EOFError, KeyboardInterrupt):
        raise
    except Exception:
        logger.debug("console: чтение из /dev/tty не удалось", exc_info=True)
        return input(text)
    if line == "":
        raise EOFError("console: /dev/tty закрыт")
    return line.rstrip("\r\n")


def reset_cache() -> None:
    global _interactive, _tty_stream, _tty_failed
    _interactive = None
    _tty_failed = False
    stream = _tty_stream
    _tty_stream = None
    if stream is not None:
        try:
            stream.close()
        except Exception:
            logger.debug("console: не удалось закрыть /dev/tty", exc_info=True)
