"""
Kitsune built-in: Backup
Команды: .backup .restore
Авто-бэкап по расписанию — отправляет в группу KitsuneBackup или через бота.
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import io
import json
import logging
import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.backup"

# Варианты интервала авто-бэкапа (часы)
_INTERVAL_OPTIONS = [2, 4, 6, 8, 12, 24, 48]


class BackupModule(KitsuneModule):
    name        = "backup"
    description = "Резервное копирование базы данных"
    author      = "Yushi"

    strings_ru = {
        "creating":       "⏳ Создаю резервную копию...",
        "done":           "✅ Резервная копия отправлена.",
        "done_auto":      "🗂 Авто-бэкап выполнен.",
        "no_backup":      "❌ Нет данных для резервирования.",
        "restoring":      "⏳ Восстанавливаю из резервной копии...",
        "restored":       "✅ База данных восстановлена. Перезапустите бота.",
        "bad_file":       "❌ Неверный формат файла резервной копии.",
        "no_dest":        "⚠️ Нет группы для бэкапа. Создаю...",
        "group_created":  "✅ Группа <b>KitsuneBackup</b> создана.",
        "setup_interval": (
            "🗂 <b>Авто-бэкап Kitsune</b>\n\n"
            "Выбери интервал резервного копирования.\n"
            "Бэкапы будут отправляться сюда."
        ),
        "interval_set":   "✅ Авто-бэкап каждые <b>{h} ч</b>. Следующий через {h} ч.",
        "interval_off":   "🔕 Авто-бэкап отключён.",
        "backup_caption": "🦊 <b>Kitsune Backup</b>\n🕐 {ts}\n🔁 Интервал: каждые {h} ч",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._auto_task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_load(self) -> None:
        interval_h = self.db.get(_DB_OWNER, "interval_h", None)
        if interval_h:
            self._start_auto(int(interval_h))

    async def on_unload(self) -> None:
        self._stop_auto()

    # ── Commands ──────────────────────────────────────────────────────────────

    @command("backup", required=OWNER)
    async def backup_cmd(self, event) -> None:
        """.backup — создать резервную копию вручную"""
        m = await event.reply(self.strings("creating"), parse_mode="html")
        dest = await self._ensure_backup_dest()
        await self._send_backup(dest)
        await m.edit(self.strings("done"), parse_mode="html")

    @command("restore", required=OWNER)
    async def restore_cmd(self, event) -> None:
        """.restore — восстановить базу из прикреплённого файла"""
        reply = await event.message.get_reply_message()
        if not reply or not reply.file:
            await event.reply(
                "❌ Ответь на сообщение с файлом резервной копии.",
                parse_mode="html",
            )
            return

        m = await event.reply(self.strings("restoring"), parse_mode="html")
        try:
            raw     = await reply.download_media(bytes)
            payload = json.loads(raw.decode())
            if not payload.get("kitsune_backup"):
                await m.edit(self.strings("bad_file"), parse_mode="html")
                return
            for owner, sub in payload["data"].items():
                for key, value in sub.items():
                    await self.db.set(owner, key, value)
            await self.db.force_save()
            await m.edit(self.strings("restored"), parse_mode="html")
        except Exception as exc:
            await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

    # ── Auto-backup loop ──────────────────────────────────────────────────────

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

    # ── Public: called by notifier after first bot setup ──────────────────────

    async def show_interval_setup(self, bot, owner_id: int) -> None:
        """
        Вызывается из NotifierModule после первого запуска бота.
        Отправляет кнопки выбора интервала прямо в бота.
        """
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
        """Обработка нажатия кнопки выбора интервала."""
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

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _ensure_backup_dest(self) -> int:
        """
        Возвращает chat_id группы KitsuneBackup.
        Если группа ещё не создана — создаёт её и сохраняет id в БД.
        """
        chat_id = self.db.get(_DB_OWNER, "group_id", None)
        if chat_id:
            return int(chat_id)

        # Создаём группу
        result = await self.client(
            __import__(
                "telethon.tl.functions.messages",
                fromlist=["CreateChatRequest"],
            ).CreateChatRequest(
                users=[],
                title="KitsuneBackup",
            )
        )
        gid = result.chats[0].id
        # Делаем супергруппу чтобы можно было назначить описание
        try:
            from telethon.tl.functions.messages import MigrateToChannelRequest
            migrated = await self.client(MigrateToChannelRequest(channel=gid))
            gid = migrated.updates[0].channel_id
        except Exception:
            pass

        await self.db.set(_DB_OWNER, "group_id", gid)
        logger.info("Backup: created KitsuneBackup group id=%d", gid)
        return gid

    async def _send_backup(self, dest: int, *, auto: bool = False) -> None:
        """Сформировать JSON и отправить в чат dest."""
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
        buf      = io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode())
        buf.name = f"kitsune_backup_{int(time.time())}.json"
        buf.seek(0)

        caption = self.strings("backup_caption").format(
            ts=time.strftime("%Y-%m-%d %H:%M:%S"),
            h=h_str,
        )
        await self.client.send_file(dest, buf, caption=caption, parse_mode="html")
