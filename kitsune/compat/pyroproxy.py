"""
Hydrogram ↔ Pyrogram proxy.

Some third-party modules import from `pyrogram` directly.
If Hydrogram is installed, redirect those imports to Hydrogram
since its API is compatible.
"""

# © Yushi (@Mikasu32), 2024-2025
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import sys
import logging

logger = logging.getLogger(__name__)


def apply() -> None:
    """If hydrogram is present but pyrogram is not, alias pyrogram → hydrogram."""
    if "pyrogram" in sys.modules:
        return   # pyrogram already available, nothing to do

    try:
        import hydrogram as _hydro
        sys.modules["pyrogram"] = _hydro
        # Sub-modules commonly used
        for sub in ("types", "filters", "handlers", "errors", "raw", "enums"):
            full = f"hydrogram.{sub}"
            alias = f"pyrogram.{sub}"
            try:
                __import__(full)
                sys.modules.setdefault(alias, sys.modules[full])
            except ImportError:
                pass
        logger.debug("compat.pyroproxy: pyrogram → hydrogram alias installed")
    except ImportError:
        logger.debug("compat.pyroproxy: neither pyrogram nor hydrogram available")
