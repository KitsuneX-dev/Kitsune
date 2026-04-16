from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def apply_all() -> None:
    from .hikka import apply as _hikka
    from .heroku import apply as _heroku

    _hikka()
    _heroku()

    logger.debug("compat: all shims applied")
