from __future__ import annotations

import asyncio
import logging
import time
import typing
from collections import defaultdict

logger = logging.getLogger(__name__)

class _HydroMessageAdapter:

    def __init__(self, hydro_msg, telethon_client) -> None:
        self._msg = hydro_msg
        self._client = telethon_client

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

    async def edit(self, text: str, **kwargs) -> typing.Any:
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

    def __init__(self, hydro_msg, telethon_client) -> None:
        self.message = _HydroMessageAdapter(hydro_msg, telethon_client)
        self._client = telethon_client
        self.chat_id = self.message.chat_id

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(self.message, name)

class HydrogramBridge:

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

    # ── Rate limiter ──────────────────────────────────────────────────────────
    # Значения по умолчанию — переопределяются через APILimiter конфиг
    _RL_MAX      = 20
    _RL_WINDOW   = 60.0
    _rl_enabled  = True   # управляется через APILimiter.config["hydro_enabled"]
    _rl_times: list = []

    def _rate_limit_ok(self) -> bool:
        """Возвращает True если запрос разрешён, False если надо притормозить."""
        if not self._rl_enabled:
            return True
        now = time.monotonic()
        self._rl_times = [t for t in self._rl_times if now - t < self._RL_WINDOW]
        if len(self._rl_times) >= self._RL_MAX:
            logger.warning(
                "HydrogramBridge: rate limit reached (%d/%d in %.0fs) — dropping event",
                len(self._rl_times), self._RL_MAX, self._RL_WINDOW,
            )
            return False
        self._rl_times.append(now)
        return True

    def attach(self) -> None:
        try:
            from hydrogram import filters
            from hydrogram.handlers import MessageHandler

            async def _on_message(client, message) -> None:
                if not self._rate_limit_ok():
                    return
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

            # Собственные исходящие сообщения уже обрабатывает Telethon через
            # _on_out_message — пропускаем их здесь, чтобы не было дублей.
            if is_own:
                return

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
    bridge = HydrogramBridge(hydro_client, telethon_client, dispatcher, db)
    bridge.attach()
    return bridge
