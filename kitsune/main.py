from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import logging
import os
import stat
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

BASE_PATH = Path(BASE_DIR)

CONFIG_PATH = BASE_PATH / "config.toml"

DATA_DIR = Path.home() / ".kitsune"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _mode = stat.S_IMODE(DATA_DIR.stat().st_mode)
    if not (_mode & stat.S_IWUSR):
        os.chmod(DATA_DIR, 0o755)
except Exception:
    pass

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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kitsune Userbot")
    p.add_argument("--no-web", action="store_true", help="Disable web interface")
    p.add_argument("--no-hydrogram", action="store_true", help="Disable Hydrogram secondary client")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    return p.parse_args()


def main() -> None:
    from .core.lifecycle import startup

    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        asyncio.run(startup(args, _load_raw_config, _save_config, _HAVE_UVLOOP))
    except KeyboardInterrupt:
        pass
