"""
kitsune.compat — слой совместимости с другими UserBot-фреймворками.

Экспортирует:
  apply_all()  — устанавливает шимы для всех поддерживаемых фреймворков
                 (Hikka, Heroku, FTG).  Вызывается при старте Kitsune.

Отдельные модули:
  hikka         — шимы для Hikka и hikkatl
  heroku        — шимы для Heroku/FTG и herokutl
  module_adapter— детектор и адаптер чужих модулей при загрузке
  pyroproxy     — прокси-слой для Pyrogram/Hydrogram
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_all() -> None:
    """
    Устанавливает шимы всех поддерживаемых сторонних фреймворков.
    Безопасно вызывать многократно (идемпотентно).
    """
    from .hikka import apply as _hikka
    from .heroku import apply as _heroku

    _hikka()
    _heroku()

    logger.debug("compat: all shims applied")
