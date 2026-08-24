from __future__ import annotations
import asyncio
import logging
import time

from ...core.loader import command
from ...core.security import OWNER
from .helpers import _DB_OWNER, _INTERVAL_OPTIONS

logger = logging.getLogger(__name__)

class SchedulerMixin:

    @command("setbackupinterval", required=OWNER)
    async def setbackupinterval_cmd(self, event) -> None:
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix     = dispatcher._prefix if dispatcher else "."
        raw        = event.message.text[len(prefix):].split(maxsplit=1)
        arg        = raw[1].strip().lower() if len(raw) > 1 else ""
        if not arg:
            current = self.db.get(_DB_OWNER, "interval_h", None)
            status  = f"каждые <b>{current} ч</b>" if current else "отключён"
            await event.reply(
                f"🗂 Авто-бэкап сейчас: {status}\n\n"
                + self.strings("interval_usage"),
                parse_mode="html",
            )
            return
        if arg in ("off", "0", "no", "disable", "выкл", "отключить"):
            if self._auto_task and not self._auto_task.done():
                self._auto_task.cancel()
            await self.db.delete(_DB_OWNER, "interval_h")
            await event.reply(self.strings("interval_off"), parse_mode="html")
            return
        try:
            h = int(arg)
        except ValueError:
            await event.reply(self.strings("interval_bad"), parse_mode="html")
            return
        if h not in _INTERVAL_OPTIONS:
            await event.reply(self.strings("interval_bad"), parse_mode="html")
            return
        await self.db.set(_DB_OWNER, "interval_h", h)
        await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
        self._start_auto(h)
        await event.reply(self.strings("interval_set").format(h=h), parse_mode="html")
    def _start_auto(self, interval_h) -> None:
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        self._auto_task = asyncio.ensure_future(self._auto_loop(interval_h))
    async def _auto_loop(self, interval_h) -> None:
        interval_sec = 60 if interval_h == "1m" else int(interval_h) * 3_600
        while True:
            last = self.db.get(_DB_OWNER, "last_backup", 0)
            wait = max(0, last + interval_sec - time.time())
            await asyncio.sleep(wait)
            try:
                dest = await self._get_dest()
                if not dest:
                    await asyncio.sleep(60)
                    continue
                ts  = self._ts()
                fts = self._fname_ts()
                db_data = self._db_bytes()
                await self._send_backup(
                    dest, db_data,
                    f"kitsune-db-{fts}.json",
                    self.strings("db_caption").format(ts=ts),
                    "db", ts,
                )
                mods_data, count, cfg_count = self._make_mods_zip()
                await self._send_backup(
                    dest, mods_data,
                    f"kitsune-mods-{fts}.zip",
                    self.strings("mods_caption").format(ts=ts, count=count, cfg=cfg_count),
                    "mods", ts, count,
                )
                full_data, count, _cfg = self._make_full_backup()
                await self._send_backup(
                    dest, full_data,
                    f"kitsune-{fts}.backup",
                    self.strings("all_caption").format(ts=ts, count=count),
                    "all", ts, count,
                )
                await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
                logger.debug("backup: авто-бэкап выполнен — db.json + mods.zip + .backup (%s)", fts)
            except Exception:
                logger.exception("backup: авто-бэкап упал")
                await asyncio.sleep(60)
    async def show_interval_setup(self, bot, owner_id: int) -> None:
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons, row = [], []
            for h in _INTERVAL_OPTIONS:
                label = f"{h}ч"
                row.append(InlineKeyboardButton(
                    text=label,
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
            await bot.send_message(
                chat_id=owner_id,
                text=self.strings("setup_interval"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML",
            )
        except Exception as _exc:
            _exc_str = str(_exc).lower()
            if (
                "Forbidden" in type(_exc).__name__
                or "forbidden" in _exc_str
                or "chat not found" in _exc_str
                or "bot was blocked" in _exc_str
                or "user is deactivated" in _exc_str
            ):
                logger.warning(
                    "Backup: бот не может начать диалог с owner_id=%s. "
                    "Напиши /start боту в Telegram. (%s)", owner_id, _exc,
                )
            else:
                logger.exception("Backup: failed to send interval setup")
    async def handle_interval_callback(self, call) -> None:
        await self.on_callback(call)
    async def on_callback(self, call) -> None:
        if not call.data.startswith("backup_interval:"):
            return
        raw_h = call.data.split(":")[1]
        h = raw_h if raw_h == "1m" else int(raw_h)
        if h == 0:
            if self._auto_task and not self._auto_task.done():
                self._auto_task.cancel()
            await self.db.delete(_DB_OWNER, "interval_h")
            await call.message.edit_text(self.strings("interval_off"), parse_mode="HTML")
            return
        if h == "1m":
            await self.db.set(_DB_OWNER, "interval_h", "1m")
            await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
            self._start_auto("1m")
            await call.message.edit_text("✅ Авто-бэкап каждые <b>1 мин</b> (тест).", parse_mode="HTML")
        else:
            await self.db.set(_DB_OWNER, "interval_h", h)
            await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
            self._start_auto(h)
            await call.message.edit_text(self.strings("interval_set").format(h=h), parse_mode="HTML")

__all__ = ["SchedulerMixin"]
