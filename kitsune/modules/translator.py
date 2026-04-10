from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

class TranslatorModule(KitsuneModule):

    name        = "translator"
    description = "Перевод текста"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "default_lang",
                default="ru",
                doc="Язык перевода по умолчанию (ru, en, de, ...)",
            ),
            ConfigValue(
                "only_text",
                default=False,
                doc="Показывать только переведённый текст (без оригинала)",
            ),
        )

    strings_ru = {
        "no_text":     "❌ Нет текста для перевода. Ответь на сообщение или введи текст.",
        "translating": "⏳ Перевожу...",
        "result":      "🌐 <b>Перевод</b> (<code>{lang}</code>):\n\n{text}",
        "error":       "❌ Ошибка перевода. Попробуй позже.",
        "usage":       "Использование: <code>.tr [язык] [текст]</code>\nПример: <code>.tr en Привет мир</code>",
    }

    @staticmethod
    def _parse_args(raw: str) -> tuple[str | None, str | None]:
        if not raw:
            return None, None

        parts = raw.split(maxsplit=1)
        first = parts[0]

        if len(first) <= 5 and first.isalpha():
            lang = first.lower()
            text = parts[1] if len(parts) > 1 else None
            return lang, text

        return None, raw

    @command("tr", required=OWNER)
    async def tr_cmd(self, event) -> None:
        raw = self.get_args(event).strip()
        lang, text = self._parse_args(raw)

        if lang is None:
            lang = self.config["default_lang"]

        entities = []
        if not text:
            reply = await event.message.get_reply_message()
            if not reply:
                await event.message.edit(self.strings("no_text"), parse_mode="html")
                return
            text = reply.raw_text or ""
            entities = reply.entities or []

        if not text:
            await event.message.edit(self.strings("no_text"), parse_mode="html")
            return

        await event.message.edit(self.strings("translating"), parse_mode="html")

        try:
            translated = await self.client.translate(
                event.message.peer_id,
                event.message,
                lang,
                raw_text=text,
                entities=entities,
            )

            if self.config["only_text"]:
                await event.message.edit(translated, parse_mode="html")
            else:
                await event.message.edit(
                    self.strings("result").format(lang=lang, text=translated),
                    parse_mode="html",
                )

        except Exception as exc:
            logger.exception("Translator: translation failed")
            await event.message.edit(self.strings("error"), parse_mode="html")
