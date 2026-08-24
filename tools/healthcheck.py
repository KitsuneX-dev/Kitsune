#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8080
TIMEOUT = 8.0

_TRUTHY = frozenset({"1", "true", "yes", "on", "y", "t"})


def _config_path() -> Path:
    override = os.environ.get("KITSUNE_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    data_dir = os.environ.get("KITSUNE_DATA_DIR", "").strip() or "/data"
    return Path(data_dir) / "config.toml"


def _load_config() -> dict:
    cfg = _config_path()
    if not cfg.exists():
        return {}
    try:
        try:
            import tomllib as _toml_reader
            data = _toml_reader.loads(cfg.read_text(encoding="utf-8"))
        except ImportError:
            import toml as _toml_reader  
            data = _toml_reader.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return False


def _web_disabled_by_low_power(data: dict) -> bool:
    raw = os.environ.get("KITSUNE_LOW_POWER", "").strip().lower()
    if raw not in _TRUTHY:
        return False
    return not _as_bool(data.get("web"))


def _web_port(data: dict | None = None) -> int:
    if data is None:
        data = _load_config()
    try:
        port = int(data.get("web_port", 0) or 0)
        if 0 < port < 65536:
            return port
    except Exception:
        pass
    try:
        port = int(os.environ.get("KITSUNE_WEB_PORT", "").strip() or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT
    return port if 0 < port < 65536 else DEFAULT_PORT


def _tolerable_degradation(body: bytes) -> bool:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return False
    if not isinstance(payload, dict) or payload.get("ok") is not False:
        return False
    tg = payload.get("telegram")
    sq = payload.get("sqlite")
    if not isinstance(tg, dict) or not isinstance(sq, dict):
        return False
    sqlite_alive = bool(sq.get("alive", True)) or sq.get("active", True) is False
    return sqlite_alive


def main() -> int:
    data = _load_config()
    if _web_disabled_by_low_power(data):
        return 0
    url = f"http://127.0.0.1:{_web_port(data)}/health"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read(65536)
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read(65536)
        except Exception:
            err_body = b""
        if _tolerable_degradation(err_body):
            print(
                f"healthcheck: {url} -> HTTP {exc.code}, readiness-деградация "
                "(процесс и БД живы) — рестарт не нужен",
                file=sys.stderr,
            )
            return 0
        print(f"healthcheck: {url} -> HTTP {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"healthcheck: {url} недоступен — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if status != 200:
        if _tolerable_degradation(body):
            print(
                f"healthcheck: {url} -> HTTP {status}, readiness-деградация "
                "(процесс и БД живы) — рестарт не нужен",
                file=sys.stderr,
            )
            return 0
        print(f"healthcheck: {url} -> HTTP {status}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return 0
    if isinstance(payload, dict) and payload.get("ok") is False:
        print(f"healthcheck: панель сообщает о деградации — {payload}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
