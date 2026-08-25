from __future__ import annotations
import argparse
import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    import uvloop as _uvloop
    _HAVE_UVLOOP = True
except ImportError:
    _HAVE_UVLOOP = False


_runner = _uvloop.run if _HAVE_UVLOOP else asyncio.run

from . import install_patches
from ._migrations import cleanup_legacy_143_layout

from .paths import (
    data_dir as _kitsune_data_dir,
    config_path as _kitsune_config_path,
    is_secondary as _kitsune_is_secondary,
    in_docker as _kitsune_in_docker,
    harden_dir as _kitsune_harden_dir,
    DOCKER_DATA_DIR as _KITSUNE_DOCKER_DATA_DIR,
)

BASE_DIR = (
    _KITSUNE_DOCKER_DATA_DIR
    if _kitsune_in_docker()
    else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

BASE_PATH = Path(BASE_DIR)





cleanup_legacy_143_layout(BASE_PATH)
install_patches()

DATA_DIR = _kitsune_data_dir()

if _kitsune_is_secondary():
    CONFIG_PATH = _kitsune_config_path(DATA_DIR)
else:
    CONFIG_PATH = _kitsune_config_path(BASE_PATH)

try:


    _kitsune_harden_dir(DATA_DIR)
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


def _apply_low_power(args: argparse.Namespace) -> argparse.Namespace:
    from . import low_power

    try:
        cfg = _load_raw_config()
    except Exception:
        cfg = {}
    low_power.set_enabled(low_power.resolve(cfg))
    if not low_power.enabled():
        return args
    disabled = []
    if not getattr(args, "no_hydrogram", False) and low_power.disable_hydrogram(cfg):
        args.no_hydrogram = True
        disabled.append("hydrogram")
    if not getattr(args, "no_web", False) and low_power.disable_web(cfg):
        args.no_web = True
        disabled.append("web")
    logger.info(
        "main: low_power mode enabled (disabled: %s)",
        ", ".join(disabled) if disabled else "nothing",
    )
    return args


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kitsune Userbot")
    p.add_argument("--no-web", action="store_true", help="Disable web interface")
    p.add_argument("--no-hydrogram", action="store_true", help="Disable Hydrogram secondary client")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    return _apply_low_power(p.parse_args())


def main() -> None:
    from .core.lifecycle import startup

    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        _runner(startup(args, _load_raw_config, _save_config, _HAVE_UVLOOP))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            from ._internal import restart_requested, exec_restart
            if restart_requested():
                logger.info("main: restart requested — замещаю процесс")
                exec_restart()
        except Exception:
            logger.exception("main: exec_restart в finally не удался")
        os._exit(0)
