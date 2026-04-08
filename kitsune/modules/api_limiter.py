from __future__ import annotations

import asyncio
import logging
import random
import time
import typing

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.api_limiter"

# Системные запросы Telethon (фоновая синхронизация, keep-alive, апдейты)
# Они выполняются автоматически и НЕ должны учитываться в лимите.
_SYSTEM_REQUESTS: frozenset[str] = frozenset({
    "GetChannelDifferenceRequest",
    "GetDifferenceRequest",
    "GetUpdatesRequest",
    "GetStateRequest",
    "PingRequest",
    "PingDelayDisconnectRequest",
    "GetConfigRequest",
    "GetNearestDcRequest",
    "InvokeWithLayerRequest",
    "InvokeWithoutUpdatesRequest",
    "InitConnectionRequest",
    "GetCdnFileRequest",
    "SaveFilePart",
    "SaveBigFilePart",
    "GetFileRequest",
    "UploadFileRequest",
    "GetAuthorizationFormRequest",
    "GetFutureSaltsRequest",
    "DestroySessionRequest",
    "DestroyAuthKeyRequest",
})

# Только эти группы реально могут вызвать флудвейт от действий пользователя
_MONITORED_MODULES: frozenset[str] = frozenset({
    "messages",
    "account",
    "channels",
    "contacts",
    "photos",
    "stickers",
})


class APILimiterModule(KitsuneModule):
    """Защита от спама в Telegram API — предотвращает флудвейты."""

    name        = "APILimiter"
    description = "Защита Telegram API от превышения лимитов"
    author      = "@Mikasu32"
    version     = "1.1"
    _builtin    = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ratelimiter: list[tuple[str, float]] = []
        self._suspend_until: float = 0.0
        self._lock = False
        self._installed = False
        self._old_call: typing.Any = None

        self.config = ModuleConfig(
            ConfigValue(
                "time_sample",
                default=15,
                doc="Окно мониторинга запросов (секунд)",
            ),
            ConfigValue(
                "threshold",
                default=80,
                doc="Максимум пользовательских запросов за time_sample до срабатывания защиты",
            ),
            ConfigValue(
                "local_floodwait",
                default=30,
                doc="Время паузы при превышении порога (секунд)",
            ),
            ConfigValue(
                "enabled",
                default=True,
                doc="Включить защиту API",
            ),
        )

    async def on_load(self) -> None:
        await asyncio.sleep(5)
        await self._install()

    async def on_unload(self) -> None:
        self._uninstall()

    # ─── install / uninstall ──────────────────────────────────────────────

    async def _install(self) -> None:
        if self._installed:
            return
        if hasattr(self.client, "_kitsune_api_limiter_installed"):
            return

        old_call = self.client._call
        limiter = self

        async def _patched_call(sender, request, ordered=False, flood_sleep_threshold=None):
            await asyncio.sleep(random.randint(1, 5) / 100)

            if limiter.config["enabled"] and time.perf_counter() > limiter._suspend_until:
                req_name = type(request).__name__

                # Пропускаем системные запросы — они не являются признаком спама
                if req_name not in _SYSTEM_REQUESTS:
                    req_module = getattr(type(request), "__module__", "") or ""
                    # Учитываем только запросы из мониторируемых групп API
                    if any(f".{mod}." in req_module for mod in _MONITORED_MODULES):
                        now = time.perf_counter()
                        limiter._ratelimiter.append((req_name, now))

                        # Удаляем устаревшие записи
                        window = float(limiter.config["time_sample"])
                        limiter._ratelimiter = [
                            (n, t) for n, t in limiter._ratelimiter
                            if now - t < window
                        ]

                        if len(limiter._ratelimiter) > int(limiter.config["threshold"]) and not limiter._lock:
                            limiter._lock = True
                            pause = int(limiter.config["local_floodwait"])
                            logger.warning(
                                "APILimiter: %d user requests in %ss — pausing for %ds",
                                len(limiter._ratelimiter), window, pause,
                            )
                            # Уведомляем через бота
                            try:
                                loader = getattr(limiter.client, "_kitsune_loader", None)
                                notifier = loader.modules.get("notifier") if loader else None
                                if notifier and getattr(notifier, "_bot", None):
                                    owner_id = notifier.db.get("kitsune.notifier", "owner_id", None)
                                    if owner_id:
                                        top = limiter._ratelimiter[-10:]
                                        top_str = "\n".join(f"• <code>{n}</code>" for n, _ in top)
                                        await notifier._bot.send_message(
                                            int(owner_id),
                                            f"⚠️ <b>APILimiter</b>: превышен порог запросов!\n"
                                            f"Пауза на <b>{pause} с</b>\n\n"
                                            f"Топ запросов:\n{top_str}",
                                            parse_mode="HTML",
                                        )
                            except Exception:
                                pass

                            time.sleep(pause)
                            limiter._lock = False

            return await old_call(sender, request, ordered, flood_sleep_threshold)

        self.client._call = _patched_call
        self.client._kitsune_api_limiter_installed = True
        self._old_call = old_call
        self._installed = True
        logger.info("APILimiter: installed (system requests excluded)")

    def _uninstall(self) -> None:
        if not self._installed:
            return
        if self._old_call:
            self.client._call = self._old_call
        if hasattr(self.client, "_kitsune_api_limiter_installed"):
            del self.client._kitsune_api_limiter_installed
        self._installed = False
        logger.info("APILimiter: uninstalled")

    # ─── команды ──────────────────────────────────────────────────────────

    @command("suspend_api_protect", required=OWNER)
    async def suspend_cmd(self, event) -> None:
        """.suspend_api_protect <секунды> — временно отключить защиту API."""
        arg = self.get_args(event).strip()
        if not arg.isdigit():
            await event.message.edit(
                "❌ Укажи количество секунд: <code>.suspend_api_protect 60</code>",
                parse_mode="html",
            )
            return

        secs = int(arg)
        self._suspend_until = time.perf_counter() + secs
        await event.message.edit(
            f"⏸ Защита API приостановлена на <b>{secs} с</b>.",
            parse_mode="html",
        )

    @command("api_fw_protection", required=OWNER)
    async def toggle_cmd(self, event) -> None:
        """.api_fw_protection — включить/выключить защиту API."""
        current = self.config["enabled"]
        self.config["enabled"] = not current
        await self.db.set(_DB_OWNER, "enabled", not current)

        state = "включена ✅" if not current else "выключена ❌"
        await event.message.edit(
            f"🛡 Защита API <b>{state}</b>.",
            parse_mode="html",
        )
