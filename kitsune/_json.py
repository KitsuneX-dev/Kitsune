from __future__ import annotations
import logging
import os
import typing

logger = logging.getLogger(__name__)

_FORCE_STDLIB = bool(os.environ.get("KITSUNE_NO_ORJSON"))

_orjson: typing.Any = None

if not _FORCE_STDLIB:
    try:
        import orjson as _orjson
    except Exception as _exc:
        _orjson = None
        logger.debug("_json: orjson недоступен (%s) — использую стандартный json", _exc)

if _orjson is not None:
    _OPT = getattr(_orjson, "OPT_NON_STR_KEYS", 0)

    def dumps(value: typing.Any) -> str:
        return _orjson.dumps(value, option=_OPT).decode("utf-8")

    def dumps_bytes(value: typing.Any) -> bytes:
        return _orjson.dumps(value, option=_OPT)

    def loads(value: typing.Any) -> typing.Any:
        return _orjson.loads(value)

    HAVE_ORJSON = True
    BACKEND = "orjson"
else:
    import json as _json

    def dumps(value: typing.Any) -> str:
        return _json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def dumps_bytes(value: typing.Any) -> bytes:
        return dumps(value).encode("utf-8")

    def loads(value: typing.Any) -> typing.Any:
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8")
        return _json.loads(value)

    HAVE_ORJSON = False
    BACKEND = "json"


def backend_name() -> str:
    return BACKEND


def is_serializable(value: typing.Any) -> bool:
    try:
        dumps(value)
        return True
    except (TypeError, ValueError):
        return False
