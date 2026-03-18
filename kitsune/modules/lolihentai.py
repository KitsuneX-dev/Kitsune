"""
LoliHentai — случайные loli фото.
Команды: .loli .lolic
"""

# Kitsune module

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
import os
import random
import datetime
from telethon import functions


class LoliHentaiModule(KitsuneModule):
    name        = "lolihentai"
    description = "Лучший друг в loli hentai"
    author      = "@mqone (порт для Kitsune)"
    version     = "1.5.3"

    _strings = {
        "loading": "⏳ Загружаю фото...",
        "error":   "Не удалось получить фото. Разблокируй @ferganteusbot",
        "search":  "🔴 Ищу фото...",
    }
    _strings_ru = _strings

    @command("loli", required=OWNER)
    async def loli_cmd(self, event) -> None:
        """.loli — случайное loli фото через @ferganteusbot"""
        await event.edit(self.strings("loading"))
        try:
            async with self.client.conversation("@ferganteusbot") as conv:
                await conv.send_message("/lh")
                otvet = await conv.get_response()
                if otvet.photo:
                    phota = await self.client.download_media(otvet.photo, "loli_hentai")
                    await self.client.send_message(
                        event.chat_id,
                        file=phota,
                        reply_to=event.message.reply_to_msg_id,
                    )
                    os.remove(phota)
                    await event.delete()
                else:
                    await event.edit(self.strings("error"))
        except Exception as e:
            await event.edit(f"❌ <code>{e}</code>", parse_mode="html")

    @command("lolic", required=OWNER)
    async def lolic_cmd(self, event) -> None:
        """.lolic — случайное loli из канала"""
        await event.edit(self.strings("search"), parse_mode="html")
        try:
            chat = "hdjrkdjrkdkd"
            result = await self.client(
                functions.messages.GetHistoryRequest(
                    peer=chat,
                    offset_id=0,
                    offset_date=datetime.datetime.now(),
                    add_offset=random.choice(range(1, 851, 2)),
                    limit=1,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
            if result.messages and result.messages[0].media:
                await self.client.send_file(
                    event.chat_id,
                    result.messages[0].media,
                    reply_to=event.message.reply_to_msg_id,
                )
                await event.delete()
            else:
                await event.edit("❌ Ничего не найдено", parse_mode="html")
        except Exception as e:
            await event.edit(f"❌ <code>{e}</code>", parse_mode="html")