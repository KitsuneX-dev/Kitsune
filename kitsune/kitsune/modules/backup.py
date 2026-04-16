from __future__ import annotations

import asyncio
import io
import json
import logging
import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from .. import crypto
from ..hydro_media import send_file as hydro_send_file, download_media as hydro_download
from ..utils import auto_delete, ProgressMessage

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.backup"

_INTERVAL_OPTIONS = [2, 4, 6, 8, 12, 24, 48]

class BackupModule(KitsuneModule):
    name        = "backup"
    description = "Резервное копирование базы данных"
    author      = "Yushi"

    strings_ru = {
        "creating":       "⏳ Создаю резервную копию базы данных...",
        "done":           "✅ Резервная копия отправлена (зашифрована 🔐).",
        "done_auto":      "🗂 Авто-бэкап выполнен (зашифрован 🔐).",
        "no_backup":      "❌ Нет данных для резервирования.",
        "restoring":      "⏳ Восстанавливаю базу данных из резервной копии...",
        "restored":       "✅ База данных восстановлена. Перезапустите бота.",
        "bad_file":       "❌ Неверный формат файла резервной копии.",
        "decrypt_fail":   "❌ Не удалось расшифровать бэкап. Проверь ключ (~/.kitsune/kitsune.key).",
        "no_dest":        "⚠️ Нет группы для бэкапа. Создаю...",
        "group_created":  "✅ Группа <b>KitsuneBackup</b> создана.",
        "setup_interval": (
            "🗂 <b>Авто-бэкап Kitsune</b>\n\n"
            "Выбери интервал резервного копирования.\n"
            "Бэкапы будут отправляться сюда."
        ),
        "interval_set":   "✅ Авто-бэкап каждые <b>{h} ч</b>. Следующий через {h} ч.",
        "interval_off":   "🔕 Авто-бэкап отключён.",
                "mods_creating":  "⏳ Создаю резервную копию модулей...",
        "mods_done":      "✅ Бэкап модулей отправлен.",
        "mods_no_mods":   "❌ Нет установленных пользовательских модулей.",
        "mods_restoring": "⏳ Восстанавливаю модули...",
        "mods_restored":  "✅ Модули восстановлены: {count} шт.",
        "mods_bad_file":  "❌ Неверный формат файла бэкапа модулей.",
        "backup_caption": "🦊 <b>Kitsune Backup</b>\n🔐 Зашифрован\n🕐 {ts}\n🔁 Интервал: каждые {h} ч",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._auto_task: asyncio.Task | None = None

    async def on_load(self) -> None:
        interval_h = self.db.get(_DB_OWNER, "interval_h", None)
        if interval_h:
            self._start_auto(int(interval_h))

    async def on_unload(self) -> None:
        self._stop_auto()

    @command("backupdb", required=OWNER)
    async def backupdb_cmd(self, event) -> None:
        async with ProgressMessage(event, "🗂 Создаю резервную копию...", total=3) as prog:
            await prog.update(1)
            dest = await self._ensure_backup_dest()
            await prog.update(2)
            await self._send_backup(dest)
            await prog.done(self.strings("done"))
        done_msg = await event.get_reply_message()
        await auto_delete(done_msg)

    @command("restoredb", required=OWNER)
    async def restoredb_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if not reply or not reply.file:
            m = await event.reply(
                "❌ Ответь на сообщение с файлом резервной копии.",
                parse_mode="html",
            )
            await auto_delete(m)
            return

        async with ProgressMessage(event, "⏳ Восстанавливаю из резервной копии...", total=3) as prog:
            try:
                await prog.update(1)
                raw = await hydro_download(self.client, reply)

                if crypto.is_encrypted(raw):
                    try:
                        raw = crypto.decrypt(raw)
                    except Exception:
                        await prog.done(self.strings("decrypt_fail"))
                        return

                payload = json.loads(raw.decode())
                if not payload.get("kitsune_backup"):
                    await prog.done(self.strings("bad_file"))
                    return

                await prog.update(2)
                for owner, sub in payload["data"].items():
                    for key, value in sub.items():
                        await self.db.set(owner, key, value)
                await self.db.force_save()
                await prog.done(self.strings("restored"))
            except Exception as exc:
                await prog.done(f"❌ Ошибка: <code>{exc}</code>")

    @command("backupmods", required=OWNER)
    async def backupmods_cmd(self, event) -> None:
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return
        user_mods = {
            name: mod for name, mod in loader.modules.items()
            if not getattr(mod, "_is_builtin", True)
        }
        if not user_mods:
            await event.reply(self.strings("mods_no_mods"), parse_mode="html")
            return
        async with ProgressMessage(event, self.strings("mods_creating"), total=3) as prog:
            await prog.update(1)
            dest = await self._ensure_backup_dest()
            await prog.update(2)
            payload = {
                "kitsune_mods_backup": True,
                "timestamp": int(time.time()),
                "urls": self.db.get("kitsune.loader", "user_modules", []),
                "names": list(user_mods.keys()),
            }
            import io as _io
            buf = _io.BytesIO(json.dumps(payload, ensure_ascii=False).encode())
            buf.name = f"kitsune_mods_{int(time.time())}.json"
            buf.seek(0)
            await hydro_send_file(
                self.client, dest, buf,
                caption=f"📦 <b>Kitsune Mods Backup</b>\n🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}\n📁 Модулей: {len(user_mods)}",
                parse_mode="html",
            )
            await prog.done(self.strings("mods_done"))

    @command("restoremods", required=OWNER)
    async def restoremods_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if not reply or not reply.file:
            await event.reply("❌ Ответь на файл бэкапа модулей.", parse_mode="html")
            return
        async with ProgressMessage(event, self.strings("mods_restoring"), total=3) as prog:
            try:
                await prog.update(1)
                raw = await hydro_download(self.client, reply)
                payload = json.loads(raw.decode())
                if not payload.get("kitsune_mods_backup"):
                    await prog.done(self.strings("mods_bad_file"))
                    return
                await prog.update(2)
                urls = payload.get("urls", [])
                loader = getattr(self.client, "_kitsune_loader", None)
                count = 0
                for url in urls:
                    try:
                        await loader.load_from_url(url)
                        count += 1
                    except Exception as exc:
                        logger.warning("restoremods: failed %s — %s", url, exc)
                await prog.done(self.strings("mods_restored").format(count=count))
            except Exception as exc:
                await prog.done(f"❌ Ошибка: <code>{exc}</code>")

    async def _initial_backup_after_setup(self) -> None:
        try:
            await asyncio.sleep(2)
            dest = await self._ensure_backup_dest()
            await self._send_backup(dest, auto=False)
            logger.info("Backup: initial backup created after interval setup")
        except Exception:
            logger.exception("Backup: initial backup after setup failed")

    def _start_auto(self, interval_h: int) -> None:
        self._stop_auto()
        self._auto_task = asyncio.ensure_future(self._auto_loop(interval_h))
        logger.info("Backup: auto-backup started, interval=%dh", interval_h)

    def _stop_auto(self) -> None:
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        self._auto_task = None

    async def _auto_loop(self, interval_h: int) -> None:
        while True:
            await asyncio.sleep(interval_h * 3600)
            try:
                dest = await self._ensure_backup_dest()
                await self._send_backup(dest, auto=True)
                logger.info("Backup: auto-backup sent")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Backup: auto-backup failed")

    async def show_interval_setup(self, bot, owner_id: int) -> None:
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons = []
            row = []
            for h in _INTERVAL_OPTIONS:
                row.append(InlineKeyboardButton(
                    text=f"{h}ч",
                    callback_data=f"backup_interval:{h}",
                ))
                if len(row) == 4:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([InlineKeyboardButton(
                text="❌ Отключить",
                callback_data="backup_interval:0",
            )])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await bot.send_message(
                chat_id=owner_id,
                text=self.strings("setup_interval"),
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Backup: failed to send interval setup")

    async def handle_interval_callback(self, call) -> None:
        try:
            h = int(call.data.split(":")[1])
        except (IndexError, ValueError):
            return

        if h == 0:
            self._stop_auto()
            await self.db.delete(_DB_OWNER, "interval_h")
            await call.answer()
            await call.message.edit_text(self.strings("interval_off"), parse_mode="HTML")
            return

        await self.db.set(_DB_OWNER, "interval_h", h)
        self._start_auto(h)
        await call.answer()
        await call.message.edit_text(
            self.strings("interval_set").format(h=h),
            parse_mode="HTML",
        )

        asyncio.ensure_future(self._initial_backup_after_setup())

    async def _ensure_backup_dest(self) -> int:
        chat_id = self.db.get(_DB_OWNER, "group_id", None)
        if chat_id:
            try:
                await self.client.get_entity(int(chat_id))
                return int(chat_id)
            except Exception:
                logger.warning("Backup: saved group_id %s is invalid, recreating", chat_id)
                await self.db.delete(_DB_OWNER, "group_id")

        from telethon.tl.functions.channels import CreateChannelRequest
        from telethon.tl.functions.channels import InviteToChannelRequest

        try:
            result = await self.client(CreateChannelRequest(
                title="KitsuneBackup",
                about="🦊 Kitsune Userbot — автоматические резервные копии базы данных",
                megagroup=True,
            ))
            gid = result.chats[0].id
        except Exception as exc:
            raise RuntimeError(f"Не удалось создать группу KitsuneBackup: {exc}") from exc

        try:
            bot_username = self.db.get("kitsune.notifier", "bot_username", None)
            if bot_username:
                bot_entity = await self.client.get_entity(f"@{bot_username}")
                await self.client(InviteToChannelRequest(
                    channel=gid,
                    users=[bot_entity],
                ))
        except Exception as exc:
            logger.debug("Backup: could not add bot to group — %s", exc)

        await self.db.set(_DB_OWNER, "group_id", gid)
        logger.info("Backup: created KitsuneBackup group id=%d", gid)

        with __import__("contextlib").suppress(Exception):
            await self.client.send_message(
                "me",
                "✅ Группа <b>KitsuneBackup</b> создана — сюда будут приходить бэкапы.",
                parse_mode="html",
            )

        return gid

    async def _send_backup(self, dest: int, *, auto: bool = False) -> None:
        raw = self.db._data
        if not raw:
            raise RuntimeError("no data")

        interval_h = self.db.get(_DB_OWNER, "interval_h", None)
        h_str      = f"{interval_h} ч" if interval_h else "вручную"

        payload = {
            "kitsune_backup": True,
            "timestamp":      int(time.time()),
            "data":           raw,
        }
        plain     = json.dumps(payload, indent=2, ensure_ascii=False).encode()
        encrypted = crypto.encrypt(plain)

        buf      = io.BytesIO(encrypted)
        buf.name = f"kitsune_backup_{int(time.time())}.kbak"
        buf.seek(0)

        caption = self.strings("backup_caption").format(
            ts=time.strftime("%Y-%m-%d %H:%M:%S"),
            h=h_str,
        )
        await hydro_send_file(self.client, dest, buf, caption=caption, parse_mode="html")
