from __future__ import annotations
import typing

try:
    import orjson as _orjson
    def dumps(value: typing.Any) -> str:
        return _orjson.dumps(value, option=_orjson.OPT_NON_STR_KEYS).decode("utf-8")
    def dumps_bytes(value: typing.Any) -> bytes:
        return _orjson.dumps(value, option=_orjson.OPT_NON_STR_KEYS)
    loads = _orjson.loads
    HAVE_ORJSON = True
except ImportError:
    import json as _json
    def dumps(value: typing.Any) -> str:
        return _json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    def dumps_bytes(value: typing.Any) -> bytes:
        return dumps(value).encode("utf-8")
    loads = _json.loads
    HAVE_ORJSON = False
def is_serializable(value: typing.Any) -> bool:
    try:
        dumps(value)
        return True
    except (TypeError, ValueError):
        return False
