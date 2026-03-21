
from __future__ import annotations

import sys
import logging

logger = logging.getLogger(__name__)

def apply() -> None:
    if "pyrogram" in sys.modules:
        return

    try:
        import hydrogram as _hydro
        sys.modules["pyrogram"] = _hydro
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
