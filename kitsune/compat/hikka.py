"""
Hikka → Kitsune compatibility layer.

If someone loads a Hikka module that imports from `hikka` or uses
`loader.Module` / `loader.command` etc., this shim redirects
those imports to Kitsune equivalents so the module works without
modification.

Usage: automatically applied by Loader when it detects Hikka-style modules.
"""

from __future__ import annotations

import sys
import types
import logging

logger = logging.getLogger(__name__)

_SHIM_APPLIED = False

def apply() -> None:
    """Install Hikka compatibility shims into sys.modules."""
    global _SHIM_APPLIED
    if _SHIM_APPLIED:
        return

    from ..core.loader import KitsuneModule, command, watcher
    from ..core.security import (
        OWNER, SUDO, SUPPORT, GROUP_OWNER, GROUP_ADMIN,
        GROUP_ADMIN_ANY, GROUP_MEMBER, PM, EVERYONE, BITMAP,
    )

    loader_shim = types.ModuleType("hikka.loader")
    loader_shim.Module    = KitsuneModule  # type: ignore[attr-defined]
    loader_shim.command   = command        # type: ignore[attr-defined]
    loader_shim.watcher   = watcher        # type: ignore[attr-defined]

    security_shim = types.ModuleType("hikka.security")
    security_shim.OWNER             = OWNER        # type: ignore[attr-defined]
    security_shim.SUDO              = SUDO         # type: ignore[attr-defined]
    security_shim.SUPPORT           = SUPPORT      # type: ignore[attr-defined]
    security_shim.GROUP_OWNER       = GROUP_OWNER  # type: ignore[attr-defined]
    security_shim.GROUP_ADMIN       = GROUP_ADMIN  # type: ignore[attr-defined]
    security_shim.GROUP_ADMIN_ANY   = GROUP_ADMIN_ANY  # type: ignore[attr-defined]
    security_shim.GROUP_MEMBER      = GROUP_MEMBER # type: ignore[attr-defined]
    security_shim.PM                = PM           # type: ignore[attr-defined]
    security_shim.EVERYONE          = EVERYONE     # type: ignore[attr-defined]
    security_shim.BITMAP            = BITMAP       # type: ignore[attr-defined]

    from .. import utils as kitsune_utils
    utils_shim = types.ModuleType("hikka.utils")
    utils_shim.escape_html   = kitsune_utils.escape_html   # type: ignore[attr-defined]
    utils_shim.chunks        = kitsune_utils.chunks        # type: ignore[attr-defined]
    utils_shim.run_sync      = kitsune_utils.run_sync      # type: ignore[attr-defined]
    utils_shim.find_caller   = kitsune_utils.find_caller   # type: ignore[attr-defined]
    utils_shim.is_serializable = kitsune_utils.is_serializable  # type: ignore[attr-defined]

    hikka_shim = types.ModuleType("hikka")
    hikka_shim.loader   = loader_shim    # type: ignore[attr-defined]
    hikka_shim.security = security_shim  # type: ignore[attr-defined]
    hikka_shim.utils    = utils_shim     # type: ignore[attr-defined]

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
