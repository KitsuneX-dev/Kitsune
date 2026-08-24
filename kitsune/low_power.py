from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("kitsune.low_power")

_ENV_LOW_POWER = "KITSUNE_LOW_POWER"

_TRUTHY = frozenset({"1", "true", "yes", "on", "y", "t"})

_DEFAULT_SAVE_DELAY = 0.2
_LOW_POWER_SAVE_DELAY = 1.5
_MIN_SAVE_DELAY = 1.0
_MAX_SAVE_DELAY = 2.0

_DEFAULT_RETRIES = 10
_DEFAULT_RETRY_DELAY = 3.0
_LOW_POWER_RETRIES = 3
_LOW_POWER_RETRY_DELAY = 1.0

_enabled: bool | None = None

_config_cache: dict[str, Any] | None = None
_config_mtime: float = 0.0

_no_toml_warned = False

_config_warned_reasons: set[str] = set()


def _warn_no_toml_once() -> None:
    global _no_toml_warned
    if _no_toml_warned:
        return
    _no_toml_warned = True
    logger.warning(
        "optional dependency 'toml' is not installed: config.toml cannot be "
        "parsed, low_power settings fall back to defaults (only the "
        "%s environment variable is honoured). Install it with: pip install toml",
        _ENV_LOW_POWER,
    )


def _warn_config_unreadable_once(reason: str) -> None:
    if reason in _config_warned_reasons:
        return
    _config_warned_reasons.add(reason)
    logger.warning(
        "config.toml is unreadable (%s): low_power settings fall back to "
        "defaults / cached values (only the %s environment variable is "
        "honoured)",
        reason,
        _ENV_LOW_POWER,
    )


def reset_optional_dep_warnings() -> None:
    global _no_toml_warned
    _no_toml_warned = False
    _config_warned_reasons.clear()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return False


def resolve(cfg: dict[str, Any]) -> bool:
    raw = os.environ.get(_ENV_LOW_POWER, "").strip()
    if raw:
        return _as_bool(raw)
    return _as_bool(cfg.get("low_power"))


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def enabled() -> bool:
    if _enabled is None:
        return resolve(load_config())
    return _enabled


def reset_cache() -> None:
    global _enabled, _config_cache, _config_mtime
    _enabled = None
    _config_cache = None
    _config_mtime = 0.0


def load_config() -> dict[str, Any]:
    global _config_cache, _config_mtime
    try:
        from .paths import effective_config_path
        path = effective_config_path()
    except Exception as exc:
        _warn_config_unreadable_once(f"config path unavailable: {exc!r}")
        return _config_cache or {}
    try:
        mtime = Path(path).stat().st_mtime
    except OSError as exc:
        _warn_config_unreadable_once(f"cannot stat {path}: {exc!r}")
        return _config_cache or {}
    if _config_cache is not None and mtime == _config_mtime:
        return _config_cache
    try:
        import toml
    except ImportError:
        _warn_no_toml_once()
        return _config_cache or {}
    try:
        data = toml.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_config_unreadable_once(f"cannot parse {path}: {exc!r}")
        return _config_cache or {}
    _config_cache = data
    _config_mtime = mtime
    return data


def save_delay(cfg: dict[str, Any]) -> float:
    if not resolve(cfg):
        return _DEFAULT_SAVE_DELAY
    try:
        value = float(cfg.get("low_power_save_delay", _LOW_POWER_SAVE_DELAY))
    except (TypeError, ValueError):
        value = _LOW_POWER_SAVE_DELAY
    return min(max(value, _MIN_SAVE_DELAY), _MAX_SAVE_DELAY)


def retry_policy(cfg: dict[str, Any]) -> tuple[int, float]:
    if resolve(cfg):
        return _LOW_POWER_RETRIES, _LOW_POWER_RETRY_DELAY
    return _DEFAULT_RETRIES, _DEFAULT_RETRY_DELAY


def disable_hydrogram(cfg: dict[str, Any]) -> bool:
    if not resolve(cfg):
        return False
    return not _as_bool(cfg.get("hydrogram"))


def disable_web(cfg: dict[str, Any]) -> bool:
    if not resolve(cfg):
        return False
    return not _as_bool(cfg.get("web"))
