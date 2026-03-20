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
from ..utils import auto_delete, ProgressMessage

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
        async with ProgressMessage(event, "🗂 Создаю резервную копию...", total=3) as prog:
            await prog.update(1)
            dest = await self._ensure_backup_dest()
            await prog.update(2)
            await self._send_backup(dest)
            await prog.done("✅ Резервная копия отправлена.")
        # Авто-удаление финального сообщения если настроено
        done_msg = await event.get_reply_message()
        await auto_delete(done_msg)

    @command("restore", required=OWNER)
    async def restore_cmd(self, event) -> None:
        """.restore — восстановить базу из прикреплённого файла"""
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
                raw     = await reply.download_media(bytes)
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
        Если группа ещё не создана — создаёт её, добавляет бота и сохраняет id в БД.
        Если сохранённый id больше не валиден — пересоздаёт.
        """
        chat_id = self.db.get(_DB_OWNER, "group_id", None)
        if chat_id:
            # Проверяем что группа ещё существует
            try:
                await self.client.get_entity(int(chat_id))
                return int(chat_id)
            except Exception:
                logger.warning("Backup: saved group_id %s is invalid, recreating", chat_id)
                await self.db.delete(_DB_OWNER, "group_id")

        from telethon.tl.functions.messages import CreateChatRequest
        from telethon.tl.functions.messages import MigrateChatRequest
        from telethon.tl.functions.messages import EditChatAboutRequest

        # Узнаём username бота чтобы добавить его в группу
        notifier = None
        loader = getattr(self.client, "_kitsune_loader", None)
        if loader:
            notifier = loader.modules.get("notifier")

        bot_username = None
        if notifier:
            bot_username = self.db.get("kitsune.notifier", "bot_username", None)

        # Создаём обычный чат
        try:
            users_to_add = [bot_username] if bot_username else []
            result = await self.client(
                CreateChatRequest(
                    users=users_to_add,
                    title="KitsuneBackup",
                )
            )
            gid = result.chats[0].id
        except Exception as exc:
            logger.error("Backup: failed to create chat: %s", exc)
            # Если не получилось с ботом — пробуем без него
            try:
                result = await self.client(
                    CreateChatRequest(users=[], title="KitsuneBackup")
                )
                gid = result.chats[0].id
            except Exception as exc2:
                raise RuntimeError(f"Не удалось создать группу KitsuneBackup: {exc2}") from exc2

        # Мигрируем в супергруппу для надёжности
        try:
            await self.client(MigrateChatRequest(chat_id=gid))
            async for dialog in self.client.iter_dialogs():
                if dialog.title == "KitsuneBackup" and dialog.is_channel:
                    gid = dialog.id
                    break
        except Exception:
            pass

        # Описание группы
        try:
            await self.client(EditChatAboutRequest(
                peer=gid,
                about="🦊 Kitsune Userbot — автоматические резервные копии базы данных",
            ))
        except Exception:
            pass

        await self.db.set(_DB_OWNER, "group_id", gid)
        logger.info("Backup: created KitsuneBackup group id=%d", gid)

        # Уведомляем пользователя в Saved Messages
        with __import__("contextlib").suppress(Exception):
            await self.client.send_message(
                "me",
                "✅ Группа <b>KitsuneBackup</b> создана — сюда будут приходить бэкапы.",
                parse_mode="html",
            )

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
