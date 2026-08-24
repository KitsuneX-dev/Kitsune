from __future__ import annotations
import asyncio
import datetime
import io
import json
import logging
import zipfile

from ...core.loader import command
from ...core.security import OWNER
from ...hydro_media import send_file as hydro_send_file
from ...utils import ProgressMessage
from .helpers import (
    _DB_LOADER,
    _DB_OWNER,
    _ensure_kitsune_folder,
    _extract_msg_ids,
    _to_bot_chat_id,
    _user_modules_dir,
)

logger = logging.getLogger(__name__)

class ArchiveMixin:

    def _ts(self) -> str:
        return datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
    def _fname_ts(self) -> str:
        return datetime.datetime.now().strftime("%d-%m-%Y-%H-%M")
    def _db_bytes(self) -> bytes:
        if hasattr(self.db, "export_data"):
            data = self.db.export_data()
        else:
            data = {k: dict(v) for k, v in self.db._data.items()}
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    def _collect_module_files(self) -> list[tuple[str, bytes]]:
        files: list[tuple[str, bytes]] = []
        user_modules_dir = _user_modules_dir()
        if not user_modules_dir.exists():
            return files
        for f in sorted(user_modules_dir.glob("*.py")):
            try:
                files.append((f.name, f.read_bytes()))
            except Exception as e:
                logger.warning("backup: не удалось прочитать %s: %s", f, e)
        return files

    def _collect_module_configs(self) -> dict:
        configs: dict = {}
        try:
            data = self.db._data if hasattr(self.db, "_data") else {}
            for owner, keys in data.items():
                if owner.startswith("kitsune.config.") and isinstance(keys, dict) and keys:
                    configs[owner] = dict(keys)
        except Exception as exc:
            logger.warning("backup: не удалось собрать конфиги модулей: %s", exc)
        return configs
    def _make_mods_zip(self) -> tuple[bytes, int, int]:
        module_files = self._collect_module_files()
        url_map: dict = self.db.get(_DB_LOADER, "user_modules", {})
        configs: dict = self._collect_module_configs()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in module_files:
                zf.writestr(f"mods/{fname}", content)
            zf.writestr(
                "urls.json",
                json.dumps(url_map, ensure_ascii=False, indent=2),
            )


            zf.writestr(
                "configs.json",
                json.dumps(configs, ensure_ascii=False, indent=2),
            )
        return buf.getvalue(), len(module_files), len(configs)
    def _make_full_backup(self) -> tuple[bytes, int, int]:
        db_bytes                      = self._db_bytes()
        mods_zip, mod_count, cfg_count = self._make_mods_zip()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("db.json",  db_bytes)
            zf.writestr("mods.zip", mods_zip)
        return archive.getvalue(), mod_count, cfg_count
    async def _search_existing_backup(self) -> int | None:
        found_id: int | None = None
        try:
            async for dialog in self.client.iter_dialogs(limit=500):
                if (dialog.title or "").strip() == "KitsuneBackup":
                    entity = dialog.entity
                    cid = getattr(entity, "id", None)
                    if cid:
                        if getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False):
                            found_id = int(f"-100{cid}")
                        else:
                            found_id = -cid
                        logger.info("backup: нашли существующий KitsuneBackup id=%s", found_id)
                        break
        except Exception as e:
            logger.warning("backup: ошибка поиска KitsuneBackup в диалогах: %s", e)
        return found_id
    async def _get_dest(self, event=None) -> int | None:
        chat_id = self.db.get(_DB_OWNER, "group_id", None)
        if chat_id:
            try:
                entity = await asyncio.wait_for(
                    self.client.get_entity(int(chat_id)), timeout=20
                )
                normalized = _to_bot_chat_id(int(chat_id))
                if normalized is not None and normalized != int(chat_id):
                    try:
                        await self.db.set(_DB_OWNER, "group_id", int(normalized))
                        logger.debug(
                            "backup: group_id мигрирован %s → %s",
                            chat_id, normalized,
                        )
                    except Exception:
                        pass
                final_id = int(normalized) if normalized is not None else int(chat_id)
                await self._ensure_bot_in_channel(final_id)
                return final_id
            except Exception:
                logger.debug("backup: сохранённый group_id %s недоступен — ищем заново", chat_id)
        logger.info("backup: group_id не сохранён — сначала ищем существующий KitsuneBackup в диалогах")
        found_id = await self._search_existing_backup()
        if found_id:
            await self.db.set(_DB_OWNER, "group_id", found_id)
            await self._ensure_bot_in_channel(found_id)
            try:
                await _ensure_kitsune_folder(self.client, found_id)
            except Exception as e:
                logger.debug("backup: не удалось добавить найденный KitsuneBackup в папку Kitsune: %s", e)
            return found_id
        if event:
            await event.reply(self.strings("no_dest"), parse_mode="html")
        new_id: int | None = None
        try:
            from telethon.tl.functions.channels import CreateChannelRequest
            result = await self.client(CreateChannelRequest(
                title="KitsuneBackup",
                about="🦊 Kitsune Userbot — резервные копии",
                megagroup=False,
            ))
            entity = result.chats[0]
            new_id = int(f"-100{entity.id}")
            await self.db.set(_DB_OWNER, "group_id", new_id)
            if event:
                await event.reply(self.strings("group_created"), parse_mode="html")
            logger.info("backup: создана группа KitsuneBackup id=%s", new_id)
        except Exception as exc:
            logger.error("backup: не удалось создать KitsuneBackup: %s", exc)
            return None
        if new_id:
            await self._ensure_bot_in_channel(new_id)
            try:
                from ...assets import ensure_channel_photo, BACKUP_AVATAR
                await ensure_channel_photo(self.client, self.db, new_id, BACKUP_AVATAR)
            except Exception as e:
                logger.debug("backup: аватарка не установлена: %s", e)
            try:
                await _ensure_kitsune_folder(self.client, new_id)
            except Exception as e:
                logger.debug("backup: не удалось добавить в папку Kitsune: %s", e)
        return new_id
    async def _ensure_bot_in_channel(self, channel_id: int) -> None:
        inline = self._inline()
        if not inline or not getattr(inline, "_bot", None):
            return
        try:
            from telethon.tl.functions.channels import InviteToChannelRequest, EditAdminRequest
            from telethon.tl.types import ChatAdminRights
            bot_me = await inline._bot.get_me()
            bot_username = bot_me.username
            entity = await self.client.get_entity(channel_id)
            try:
                await self.client(InviteToChannelRequest(channel=entity, users=[bot_username]))
            except Exception:
                pass
            await self.client(EditAdminRequest(
                channel=entity,
                user_id=bot_username,
                admin_rights=ChatAdminRights(
                    post_messages=True,
                    edit_messages=True,
                    delete_messages=True,
                ),
                rank="",
            ))
            logger.debug("backup: бот @%s добавлен в KitsuneBackup как админ", bot_username)
        except Exception as exc:
            logger.warning("backup: не удалось добавить бота в KitsuneBackup: %s", exc)
    @staticmethod
    def _strip_tokens(db_data: dict) -> None:
        for ns in ("kitsune.inline", "hikka.inline", "heroku.inline"):
            try:
                db_data.get(ns, {}).pop("bot_token", None)
            except Exception:
                pass
    async def _send_with_button_via_bot(
        self,
        dest: int,
        data: bytes,
        fname: str,
        caption: str,
        kind: str,
        ts: str,
        count: int = 0,
    ) -> bool:
        inline = self._inline()
        if not inline or not getattr(inline, "_bot", None):
            logger.warning("backup: inline-бот недоступен — кнопка не будет добавлена")
            return False
        bot = inline._bot
        try:
            from aiogram.types import BufferedInputFile
        except Exception as exc:
            logger.warning("backup: aiogram недоступен (%s)", exc)
            return False
        cb_id = self._register_restore_cb(0, 0, kind)
        markup = self._build_restore_markup(cb_id)
        bot_dest = _to_bot_chat_id(dest)
        if bot_dest is None:
            logger.warning("backup: невалидный dest=%s — кнопка не будет добавлена", dest)
            inline._callbacks.pop(cb_id, None)
            self._forget_callback(cb_id)
            return False
        try:
            input_file = BufferedInputFile(data, filename=fname)
            sent = await bot.send_document(
                chat_id=bot_dest,
                document=input_file,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception as exc:
            logger.warning(
                "backup: bot.send_document(chat=%s, normalized=%s) упал: %s — пробую fallback",
                dest, bot_dest, exc,
            )
            inline._callbacks.pop(cb_id, None)
            self._forget_callback(cb_id)
            return False
        try:
            sent_chat_id = _to_bot_chat_id(sent.chat.id) or sent.chat.id
            sent_msg_id  = sent.message_id
            inline._callbacks[cb_id] = (
                self._cb_restore,
                (int(sent_chat_id), int(sent_msg_id), kind),
                self.client.tg_id,
                False,
                {},
            )
            self._persist_callback(
                cb_id, int(sent_chat_id), int(sent_msg_id), kind,
            )
            logger.debug(
                "backup: бот отправил %s (chat=%s msg=%s) с кнопкой «Восстановить»",
                kind, sent_chat_id, sent_msg_id,
            )
        except Exception as exc:
            logger.warning("backup: не смог достать sent.chat/message_id: %s", exc)
            inline._callbacks.pop(cb_id, None)
            self._forget_callback(cb_id)
            return False
        return True
    async def _attach_button_to_userbot_msg(
        self,
        sent_msg,
        kind: str,
    ) -> bool:
        inline = self._inline()
        if not inline or not getattr(inline, "_bot", None):
            return False
        chat_id, msg_id = _extract_msg_ids(sent_msg)
        if not chat_id or not msg_id:
            logger.warning("backup: не смог извлечь chat/msg id — кнопка не будет добавлена")
            return False
        bot_chat_id = _to_bot_chat_id(chat_id)
        if bot_chat_id is None:
            logger.warning("backup: chat_id=%s не нормализуется — кнопка пропущена", chat_id)
            return False
        cb_id  = self._register_restore_cb(int(bot_chat_id), int(msg_id), kind)
        markup = self._build_restore_markup(cb_id)
        try:
            await inline._bot.edit_message_reply_markup(
                chat_id=int(bot_chat_id),
                message_id=int(msg_id),
                reply_markup=markup,
            )
            self._persist_callback(
                cb_id, int(bot_chat_id), int(msg_id), kind,
            )
            logger.info(
                "backup: кнопка «Восстановить» прикреплена к %s/%s (kind=%s)",
                bot_chat_id, msg_id, kind,
            )
            return True
        except Exception as exc:
            logger.warning(
                "backup: edit_message_reply_markup(chat=%s raw=%s msg=%s) упал: %s",
                bot_chat_id, chat_id, msg_id, exc,
            )
            inline._callbacks.pop(cb_id, None)
            self._forget_callback(cb_id)
            return False
    async def _send_backup(
        self,
        dest: int | None,
        data: bytes,
        fname: str,
        caption: str,
        kind: str,
        ts: str,
        count: int = 0,
    ) -> None:
        if not dest:
            logger.warning("backup: нет KitsuneBackup — отправка пропущена")
            return
        if await self._send_with_button_via_bot(
            dest, data, fname, caption, kind, ts, count,
        ):
            return
        sent = None
        try:
            buf = io.BytesIO(data)
            buf.name = fname
            sent = await hydro_send_file(
                self.client, dest, buf, caption=caption, parse_mode="html",
            )
        except Exception:
            logger.exception("backup: send to KitsuneBackup failed")
            return
        if sent is not None:
            attached = await self._attach_button_to_userbot_msg(sent, kind)
            if not attached:
                logger.warning(
                    "backup: %s отправлен без кнопки — проверь права бота "
                    "в KitsuneBackup (нужен admin + edit_messages)",
                    kind,
                )
    @command("backupdb", required=OWNER)
    async def backupdb_cmd(self, event) -> None:
        async with ProgressMessage(event, self.strings("creating")) as prog:
            data    = self._db_bytes()
            dest    = await self._get_dest(event)
            ts      = self._ts()
            fname   = f"kitsune-db-{self._fname_ts()}.json"
            caption = self.strings("db_caption").format(ts=ts)
            await self._send_backup(dest, data, fname, caption, "db", ts)
            await prog.done(self.strings("done"))
    @command("backupmods", required=OWNER)
    async def backupmods_cmd(self, event) -> None:
        async with ProgressMessage(event, self.strings("mods_creating"), total=3) as prog:
            mods_zip, count, cfg_count = self._make_mods_zip()
            if count == 0:
                await prog.done(self.strings("mods_no_mods"))
                return
            dest    = await self._get_dest(event)
            ts      = self._ts()
            fname   = f"kitsune-mods-{self._fname_ts()}.zip"
            caption = self.strings("mods_caption").format(ts=ts, count=count, cfg=cfg_count)
            await self._send_backup(dest, mods_zip, fname, caption, "mods", ts, count)
            await prog.done(self.strings("mods_done").format(count=count, cfg=cfg_count))
    @command("backupall", required=OWNER)
    async def backupall_cmd(self, event) -> None:
        async with ProgressMessage(event, self.strings("all_creating"), total=4) as prog:
            archive_bytes, count, cfg_count = self._make_full_backup()
            dest    = await self._get_dest(event)
            ts      = self._ts()
            fname   = f"kitsune-{self._fname_ts()}.backup"
            caption = self.strings("all_caption").format(ts=ts, count=count)
            await self._send_backup(dest, archive_bytes, fname, caption, "all", ts, count)
            await prog.done(self.strings("all_done"))

__all__ = ["ArchiveMixin"]
