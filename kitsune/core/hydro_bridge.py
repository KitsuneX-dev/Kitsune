"""
HydrogramBridge — подключает Hydrogram к единому CommandDispatcher.

Вместо двух параллельных клиентов с разными системами обработки событий,
Hydrogram-события конвертируются в формат совместимый с dispatcher'ом
и передаются туда напрямую.
"""
from __future__ import annotations

import asyncio
import logging
import typing

logger = logging.getLogger(__name__)


class _HydroMessageAdapter:
    """
    Адаптер Hydrogram Message → интерфейс совместимый с Telethon.
    Dispatcher и модули используют: chat_id, sender_id, text, raw_text,
    reply_to_msg_id, out, edit(), reply(), respond(), delete().
    """

    def __init__(self, hydro_msg, telethon_client) -> None:
        self._msg = hydro_msg
        self._client = telethon_client

    # ── Базовые атрибуты ─────────────────────────────────────────────────────

    @property
    def chat_id(self) -> int:
        return getattr(self._msg.chat, "id", 0) or 0

    @property
    def sender_id(self) -> int | None:
        return getattr(getattr(self._msg, "from_user", None), "id", None)

    @property
    def text(self) -> str:
        return self._msg.text or ""

    @property
    def raw_text(self) -> str:
        return self._msg.text or ""

    @property
    def reply_to_msg_id(self) -> int | None:
        rp = getattr(self._msg, "reply_to_message", None)
        return rp.id if rp else None

    @property
    def out(self) -> bool:
        return bool(getattr(self._msg, "outgoing", False))

    @property
    def id(self) -> int:
        return self._msg.id

    @property
    def media(self) -> typing.Any:
        return getattr(self._msg, "media", None)

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(self._msg, name)

    # ── Методы отправки (через Telethon — от основного аккаунта) ─────────────

    async def edit(self, text: str, **kwargs) -> typing.Any:
        """Отправляет новое сообщение (Hydrogram-сообщения нельзя редактировать через Telethon)."""
        parse_mode = kwargs.pop("parse_mode", "html")
        return await self._client.send_message(self.chat_id, text, parse_mode=parse_mode, **kwargs)

    async def reply(self, text: str, **kwargs) -> typing.Any:
        parse_mode = kwargs.pop("parse_mode", "html")
        return await self._client.send_message(
            self.chat_id, text,
            reply_to=self._msg.id,
            parse_mode=parse_mode,
            **kwargs,
        )

    async def respond(self, text: str, **kwargs) -> typing.Any:
        parse_mode = kwargs.pop("parse_mode", "html")
        return await self._client.send_message(self.chat_id, text, parse_mode=parse_mode, **kwargs)

    async def delete(self) -> None:
        try:
            await self._msg.delete()
        except Exception:
            pass

    async def get_reply_message(self) -> typing.Any | None:
        rp = getattr(self._msg, "reply_to_message", None)
        return _HydroMessageAdapter(rp, self._client) if rp else None

    async def download_media(self, *args, **kwargs) -> bytes | None:
        try:
            import io
            buf = io.BytesIO()
            await self._msg.download(file_name=buf)
            buf.seek(0)
            return buf.read()
        except Exception:
            return None


class _HydroEventAdapter:
    """Адаптер Hydrogram event → Telethon NewMessage.Event."""

    def __init__(self, hydro_msg, telethon_client) -> None:
        self.message = _HydroMessageAdapter(hydro_msg, telethon_client)
        self._client = telethon_client
        self.chat_id = self.message.chat_id

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(self.message, name)


class HydrogramBridge:
    """
    Подключает Hydrogram к существующему CommandDispatcher.

    Регистрирует один обработчик на все входящие сообщения Hydrogram,
    конвертирует их в адаптеры и передаёт в dispatcher._handle_message.
    """

    def __init__(
        self,
        hydro_client,
        telethon_client,
        dispatcher: typing.Any,
        db: typing.Any,
    ) -> None:
        self._hydro = hydro_client
        self._tl = telethon_client
        self._dispatcher = dispatcher
        self._db = db

    def attach(self) -> None:
        """Регистрирует обработчик в Hydrogram."""
        try:
            from hydrogram import filters
            from hydrogram.handlers import MessageHandler

            async def _on_message(client, message) -> None:
                await self._handle(message)

            self._hydro.add_handler(MessageHandler(_on_message, filters.all))
            logger.info("HydrogramBridge: attached to hydrogram client")
        except Exception:
            logger.exception("HydrogramBridge: failed to attach handler")

    async def _handle(self, hydro_msg) -> None:
        try:
            sender_id = getattr(getattr(hydro_msg, "from_user", None), "id", None)
            if not sender_id:
                return

            me_id = self._tl.tg_id
            is_own = sender_id == me_id

            if not is_own:
                # Проверяем co-owner и sudo
                co_owners = self._db.get("kitsune.security", "co_owners", [])
                sec = getattr(self._tl, "_kitsune_security", None)
                sudo_users = sec.get_sudo_users() if sec else []
                if sender_id not in co_owners and sender_id not in sudo_users:
                    return

            is_co_owner = (not is_own) and (sender_id in self._db.get("kitsune.security", "co_owners", []))

            event = _HydroEventAdapter(hydro_msg, self._tl)
            await self._dispatcher._handle_message(
                event,
                is_own=is_own,
                is_co_owner=is_co_owner,
            )
        except Exception:
            logger.exception("HydrogramBridge: error handling message")


async def setup_hydrogram_bridge(
    hydro_client,
    telethon_client,
    dispatcher: typing.Any,
    db: typing.Any,
) -> HydrogramBridge:
    """Создаёт и подключает мост. Вызывается из main.py после старта клиентов."""
    bridge = HydrogramBridge(hydro_client, telethon_client, dispatcher, db)
    bridge.attach()
    return bridge
