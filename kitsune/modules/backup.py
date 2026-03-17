"""
Kitsune built-in: Backup
Команды: .backup .restore
Сохраняет базу данных в файл и отправляет в Saved Messages.
"""

# © Yushi (@Mikasu32), 2024-2025
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import io
import json
import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER


class BackupModule(KitsuneModule):
    name        = "backup"
    description = "Резервное копирование базы данных"
    author      = "Yushi"

    strings_ru = {
        "creating":  "⏳ Создаю резервную копию...",
        "done":      "✅ Резервная копия создана и отправлена в Избранное.",
        "no_backup": "❌ Нет данных для резервирования.",
        "restoring": "⏳ Восстанавливаю из резервной копии...",
        "restored":  "✅ База данных восстановлена. Перезапустите бота.",
        "bad_file":  "❌ Неверный формат файла резервной копии.",
    }

    @command("backup", required=OWNER)
    async def backup_cmd(self, event) -> None:
        """.backup — создать резервную копию базы данных"""
        m = await event.reply(self.strings("creating"), parse_mode="html")

        raw = self.db._data
        if not raw:
            await m.edit(self.strings("no_backup"), parse_mode="html")
            return

        payload = {
            "kitsune_backup": True,
            "timestamp": int(time.time()),
            "data": raw,
        }
        buf = io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode())
        buf.name = f"kitsune_backup_{int(time.time())}.json"
        buf.seek(0)

        await self.client.send_file(
            "me",
            buf,
            caption=f"🦊 <b>Kitsune Backup</b>\n<code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            parse_mode="html",
        )
        await m.edit(self.strings("done"), parse_mode="html")

    @command("restore", required=OWNER)
    async def restore_cmd(self, event) -> None:
        """.restore — восстановить базу из прикреплённого файла"""
        reply = await event.message.get_reply_message()
        if not reply or not reply.file:
            await event.reply("❌ Ответь на сообщение с файлом резервной копии.", parse_mode="html")
            return

        m = await event.reply(self.strings("restoring"), parse_mode="html")
        try:
            raw = await reply.download_media(bytes)
            payload = json.loads(raw.decode())
            if not payload.get("kitsune_backup"):
                await m.edit(self.strings("bad_file"), parse_mode="html")
                return

            data: dict = payload["data"]
            for owner, sub in data.items():
                for key, value in sub.items():
                    await self.db.set(owner, key, value)

            await self.db.force_save()
            await m.edit(self.strings("restored"), parse_mode="html")
        except Exception as exc:
            await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
