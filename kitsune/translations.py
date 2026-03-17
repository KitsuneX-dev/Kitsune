"""
Kitsune Translations

Supports YAML langpacks (same format as Hikka) plus runtime language switching.
"""

# © Yushi (@Mikasu32), 2024-2025
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import logging
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

_LANGPACKS_DIR = Path(__file__).parent / "langpacks"
_FALLBACK_LANG = "en"


class Translator:
    """
    Loads YAML langpacks and resolves translation keys.

    Priority: user_lang → fallback (en) → raw key
    """

    def __init__(self, db: typing.Any = None) -> None:
        self._db = db
        self._packs: dict[str, dict] = {}
        self._lang: str = "ru"
        self._load_all()

    def _load_all(self) -> None:
        try:
            from ruamel.yaml import YAML
            yaml = YAML()
            for path in _LANGPACKS_DIR.glob("*.yml"):
                lang = path.stem
                try:
                    self._packs[lang] = dict(yaml.load(path.read_text(encoding="utf-8")) or {})
                except Exception:
                    logger.exception("Translations: failed to load %s", path.name)
        except ImportError:
            logger.warning("Translations: ruamel.yaml not installed, translations disabled")

    def set_language(self, lang: str) -> None:
        self._lang = lang

    def translate(self, key: str, **kwargs: object) -> str:
        pack = self._packs.get(self._lang, {})
        text = pack.get(key) or self._packs.get(_FALLBACK_LANG, {}).get(key) or key
        try:
            return str(text).format(**kwargs) if kwargs else str(text)
        except (KeyError, IndexError):
            return str(text)

    # Shortcut
    def __call__(self, key: str, **kwargs: object) -> str:
        return self.translate(key, **kwargs)
