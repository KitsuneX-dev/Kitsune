from __future__ import annotations

import sys
import types
import logging

logger = logging.getLogger(__name__)

_SHIM_APPLIED = False

def apply() -> None:
    global _SHIM_APPLIED
    if _SHIM_APPLIED:
        return

    from ..core.loader import KitsuneModule, command, watcher
    from ..core.security import (
        OWNER, SUDO, SUPPORT, GROUP_OWNER, GROUP_ADMIN,
        GROUP_ADMIN_ANY, GROUP_MEMBER, PM, EVERYONE, BITMAP,
    )

    loader_shim = types.ModuleType("hikka.loader")
    loader_shim.Module  = KitsuneModule
    loader_shim.command = command
    loader_shim.watcher = watcher

    security_shim = types.ModuleType("hikka.security")
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

    from .. import utils as kitsune_utils
    utils_shim = types.ModuleType("hikka.utils")
    utils_shim.escape_html    = kitsune_utils.escape_html
    utils_shim.chunks         = kitsune_utils.chunks
    utils_shim.run_sync       = kitsune_utils.run_sync
    utils_shim.find_caller    = kitsune_utils.find_caller
    utils_shim.is_serializable = kitsune_utils.is_serializable
    utils_shim.get_args       = kitsune_utils.get_args
    utils_shim.get_args_raw   = kitsune_utils.get_args_raw
    utils_shim.answer         = kitsune_utils.answer

    hikka_shim = types.ModuleType("hikka")
    hikka_shim.loader   = loader_shim
    hikka_shim.security = security_shim
    hikka_shim.utils    = utils_shim

    sys.modules["hikka"]          = hikka_shim
    sys.modules["hikka.loader"]   = loader_shim
    sys.modules["hikka.security"] = security_shim
    sys.modules["hikka.utils"]    = utils_shim

    try:
        import telethon
        sys.modules.setdefault("hikkatl", telethon)
    except ImportError:
        pass

    try:
        import hydrogram
        sys.modules.setdefault("hikkapyro", hydrogram)
    except ImportError:
        try:
            import pyrogram
            sys.modules.setdefault("hikkapyro", pyrogram)
        except ImportError:
            pass

    _SHIM_APPLIED = True
    logger.debug("compat: Hikka shims installed")
