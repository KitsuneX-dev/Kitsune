from __future__ import annotations

import logging
import sys
import types
import typing

logger = logging.getLogger(__name__)

_SHIM_APPLIED = False

def apply() -> None:
    global _SHIM_APPLIED
    if _SHIM_APPLIED:
        return

    from .hikka import (
        apply as _hikka_apply,
        _command_decorator,
        _watcher_decorator,
        _inline_handler_decorator,
        _callback_handler_decorator,
        _tds,
        _loop_decorator,
        _ValidatorStub,
        _make_compat_module_base,
    )
    _hikka_apply()

    from ..core.loader import ModuleConfig, ConfigValue
    from ..core.security import (
        OWNER, SUDO, SUPPORT, GROUP_OWNER, GROUP_ADMIN,
        GROUP_ADMIN_ANY, GROUP_MEMBER, PM, EVERYONE, BITMAP,
    )
    from .. import utils as kitsune_utils

    CompatModule = _make_compat_module_base()

    loader_shim = types.ModuleType("heroku.loader")
    loader_shim.Module           = CompatModule
    loader_shim.command          = _command_decorator
    loader_shim.watcher          = _watcher_decorator
    loader_shim.inline_handler   = _inline_handler_decorator
    loader_shim.callback_handler = _callback_handler_decorator
    loader_shim.tds              = _tds
    loader_shim.translatable_docstring = _tds
    loader_shim.loop             = _loop_decorator
    loader_shim.ModuleConfig     = ModuleConfig
    loader_shim.ConfigValue      = ConfigValue
    loader_shim.validators       = _ValidatorStub
    loader_shim.owner            = OWNER
    loader_shim.group_owner      = GROUP_OWNER
    loader_shim.group_admin      = GROUP_ADMIN
    loader_shim.group_member     = GROUP_MEMBER
    loader_shim.pm               = PM
    loader_shim.unrestricted     = EVERYONE
    loader_shim.inline_everyone  = EVERYONE

    security_shim = types.ModuleType("heroku.security")
    security_shim.OWNER           = OWNER
    security_shim.SUDO            = SUDO
    security_shim.SUPPORT         = SUPPORT
    security_shim.GROUP_OWNER     = GROUP_OWNER
    security_shim.GROUP_ADMIN     = GROUP_ADMIN
    security_shim.GROUP_ADMIN_ANY = GROUP_ADMIN_ANY
    security_shim.GROUP_MEMBER    = GROUP_MEMBER
    security_shim.PM              = PM
    security_shim.EVERYONE        = EVERYONE
    security_shim.BITMAP          = BITMAP
    security_shim.sudo            = SUDO
    security_shim.support         = SUPPORT

    # --- fallback for is_serializable (in case of outdated kitsune.utils) ---
    def _is_serializable_fallback(value: typing.Any) -> bool:
        import json
        try:
            json.dumps(value)
            return True
        except (TypeError, ValueError):
            return False

    def _safe_bind(shim: types.ModuleType, attr: str, source: typing.Any, fallback: typing.Any = None) -> None:
        val = getattr(source, attr, None)
        if val is None:
            if fallback is not None:
                setattr(shim, attr, fallback)
                logger.warning("heroku_compat: kitsune.utils.%s not found — using built-in fallback", attr)
            else:
                logger.warning("heroku_compat: kitsune.utils.%s not found — skipping (heroku modules may break)", attr)
            return
        setattr(shim, attr, val)

    utils_shim = types.ModuleType("heroku.utils")
    _safe_bind(utils_shim, "escape_html",     kitsune_utils)
    _safe_bind(utils_shim, "chunks",          kitsune_utils)
    _safe_bind(utils_shim, "run_sync",        kitsune_utils)
    _safe_bind(utils_shim, "find_caller",     kitsune_utils)
    _safe_bind(utils_shim, "is_serializable", kitsune_utils, _is_serializable_fallback)
    _safe_bind(utils_shim, "get_args",        kitsune_utils)
    _safe_bind(utils_shim, "get_args_raw",    kitsune_utils)
    _safe_bind(utils_shim, "get_args_html",   kitsune_utils)
    _safe_bind(utils_shim, "answer",          kitsune_utils)
    _safe_bind(utils_shim, "answer_file",     kitsune_utils)

    heroku_shim = types.ModuleType("heroku")
    heroku_shim.loader   = loader_shim
    heroku_shim.security = security_shim
    heroku_shim.utils    = utils_shim

    sys.modules["heroku"]          = heroku_shim
    sys.modules["heroku.loader"]   = loader_shim
    sys.modules["heroku.security"] = security_shim
    sys.modules["heroku.utils"]    = utils_shim

    try:
        import telethon
        sys.modules.setdefault("herokutl",                 telethon)
        sys.modules.setdefault("herokutl.tl",              telethon.tl)
        sys.modules.setdefault("herokutl.tl.types",        telethon.tl.types)
        sys.modules.setdefault("herokutl.tl.functions",    telethon.tl.functions)
        sys.modules.setdefault("herokutl.extensions",      telethon.extensions)
        sys.modules.setdefault("herokutl.extensions.html", telethon.extensions.html)
        sys.modules.setdefault("herokutl.tl.tlobject",     telethon.tl.tlobject)
        sys.modules.setdefault("herokutl.events",          telethon.events)
    except ImportError:
        logger.debug("heroku_compat: telethon not available")

    _SHIM_APPLIED = True
    logger.debug("heroku_compat: shims applied")
