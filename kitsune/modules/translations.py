from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER  = "kitsune.core"
_LANG_DIR  = Path(__file__).parent.parent / "langpacks"

SUPPORTED_LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "de": "🇩🇪 Deutsch",
}


class TranslationsModule(KitsuneModule):
    """Управление языком интерфейса."""

    name        = "translations"
    description = "Язык интерфейса"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    strings_ru = {
        "lang_set":          "✅ Язык изменён на <b>{lang}</b>.",
        "lang_unknown":      "❌ Язык <code>{lang}</code> не найден.\nДоступные: {avail}",
        "lang_usage":        "Использование: <code>.setlang ru</code>",
        "pack_saved":        "✅ Языковой пакет загружен и применён.",
        "pack_failed":       "❌ Не удалось загрузить языковой пакет. Проверь ссылку.",
        "pack_usage":        "Использование: <code>.dllangpack https://...</code>",
        "cur_lang":          "🌐 Текущий язык: <b>{lang}</b>\n\nДоступные встроенные языки:\n{avail}",
    }

    # ─── helpers ──────────────────────────────────────────────────────────

    def _available(self) -> str:
        lines = []
        for code, label in SUPPORTED_LANGUAGES.items():
            lines.append(f"  <code>{code}</code> — {label}")
        # also list custom packs from langpacks dir
        for p in sorted(_LANG_DIR.glob("*.yml")):
            if p.stem not in SUPPORTED_LANGUAGES:
                lines.append(f"  <code>{p.stem}</code> — custom")
        return "\n".join(lines)

    # ─── команды ──────────────────────────────────────────────────────────

    @command("setlang", required=OWNER)
    async def setlang_cmd(self, event) -> None:
        """.setlang [код] — установить язык интерфейса."""
        lang = self.get_args(event).strip().lower()

        if not lang:
            cur = self.db.get(_DB_OWNER, "lang", "ru")
            await event.message.edit(
                self.strings("cur_lang").format(lang=cur, avail=self._available()),
                parse_mode="html",
            )
            return

        lang_path = _LANG_DIR / f"{lang}.yml"
        if lang not in SUPPORTED_LANGUAGES and not lang_path.exists():
            await event.message.edit(
                self.strings("lang_unknown").format(
                    lang=lang, avail=self._available()
                ),
                parse_mode="html",
            )
            return

        await self.db.set(_DB_OWNER, "lang", lang)
        await event.message.edit(
            self.strings("lang_set").format(lang=SUPPORTED_LANGUAGES.get(lang, lang)),
            parse_mode="html",
        )

    @command("dllangpack", required=OWNER)
    async def dllangpack_cmd(self, event) -> None:
        """.dllangpack <url> — загрузить языковой пакет из URL."""
        url = self.get_args(event).strip()

        if not url or not url.startswith("http"):
            await event.message.edit(self.strings("pack_usage"), parse_mode="html")
            return

        await event.message.edit("⏳ Загружаю языковой пакет...", parse_mode="html")

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    content = await resp.text()

            # determine filename from url
            filename = url.rstrip("/").split("/")[-1]
            if not filename.endswith(".yml"):
                filename += ".yml"

            dest = _LANG_DIR / filename
            dest.write_text(content, encoding="utf-8")

            # auto-set the lang to the downloaded pack name
            lang_code = dest.stem
            await self.db.set(_DB_OWNER, "lang", lang_code)

            await event.message.edit(self.strings("pack_saved"), parse_mode="html")
        except Exception as exc:
            logger.exception("dllangpack failed")
            await event.message.edit(self.strings("pack_failed"), parse_mode="html")
