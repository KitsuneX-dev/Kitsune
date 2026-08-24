from __future__ import annotations
import asyncio
import logging
import time

from .helpers import _DB_OWNER

logger = logging.getLogger(__name__)

class CallbackMixin:

    async def _restore_callbacks_from_db(self) -> None:
        inline = None
        for _ in range(90):
            inline = self._inline()
            if inline is not None and getattr(inline, "_started", False):
                break
            await asyncio.sleep(1)
        else:
            logger.debug("backup: inline manager not ready — callback restore skipped")
            return
        if inline is None:
            return
        saved = self.db.get(_DB_OWNER, "restore_callbacks", {})
        if not isinstance(saved, dict) or not saved:
            return
        now = int(time.time())
        cleaned: dict = {}
        restored = 0
        for cb_id, info in saved.items():
            try:
                if not isinstance(info, dict):
                    continue
                chat_id = int(info.get("chat_id", 0))
                msg_id  = int(info.get("msg_id", 0))
                kind    = str(info.get("kind", ""))
                created = int(info.get("created_at", now))
                if kind not in ("db", "mods", "all") or not chat_id or not msg_id:
                    continue
                if now - created > 30 * 24 * 3600:
                    continue
                inline._callbacks[cb_id] = (
                    self._cb_restore,
                    (chat_id, msg_id, kind),
                    self.client.tg_id,
                    False,
                    {},
                )
                cleaned[cb_id] = {
                    "chat_id": chat_id,
                    "msg_id": msg_id,
                    "kind": kind,
                    "created_at": created,
                }
                restored += 1
            except Exception:
                continue
        if restored:
            logger.info("backup: restored %d inline callback(s) from DB", restored)
        if len(cleaned) != len(saved):
            try:
                self.db.set_sync(_DB_OWNER, "restore_callbacks", cleaned)
            except Exception as _exc:
                logger.debug("backup: cannot prune callbacks: %s", _exc)
    def _persist_callback(
        self, cb_id: str, chat_id: int, msg_id: int, kind: str,
    ) -> None:
        try:
            saved = self.db.get(_DB_OWNER, "restore_callbacks", {})
            if not isinstance(saved, dict):
                saved = {}
            if len(saved) >= 50:
                items = sorted(
                    saved.items(),
                    key=lambda kv: (
                        kv[1].get("created_at", 0) if isinstance(kv[1], dict) else 0
                    ),
                )
                saved = dict(items[-49:])
            saved[cb_id] = {
                "chat_id": int(chat_id),
                "msg_id": int(msg_id),
                "kind": kind,
                "created_at": int(time.time()),
            }
            self.db.set_sync(_DB_OWNER, "restore_callbacks", saved)
        except Exception as exc:
            logger.debug("backup: cannot persist callback %s: %s", cb_id, exc)
    def _forget_callback(self, cb_id: str) -> None:
        try:
            saved = self.db.get(_DB_OWNER, "restore_callbacks", {})
            if isinstance(saved, dict) and cb_id in saved:
                saved.pop(cb_id, None)
                self.db.set_sync(_DB_OWNER, "restore_callbacks", saved)
        except Exception:
            pass
    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)
    def _register_restore_cb(self, chat_id: int, msg_id: int, kind: str) -> str:
        inline = self._inline()
        import uuid as _uuid
        cb_id = str(_uuid.uuid4())[:12]
        inline._callbacks[cb_id] = (
            self._cb_restore,
            (int(chat_id), int(msg_id), kind),
            self.client.tg_id,
            False,
            {},
        )
        return cb_id
    def _build_restore_markup(self, cb_id: str):
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=self.strings("restore_btn"),
                callback_data=cb_id,
            ),
        ]])

__all__ = ["CallbackMixin"]
