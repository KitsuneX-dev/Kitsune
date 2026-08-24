from __future__ import annotations
import asyncio
import logging
import random
import time
import typing
from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER
from .. import validators

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.api_limiter"

_TL_GROUPS: tuple[str, ...] = (
    "account",
    "auth",
    "bots",
    "channels",
    "chatlists",
    "contacts",
    "folders",
    "fragment",
    "help",
    "langpack",
    "messages",
    "payments",
    "phone",
    "photos",
    "premium",
    "smsjobs",
    "stats",
    "stickers",
    "stories",
    "updates",
    "upload",
    "users",
)

def _build_constructors() -> dict[str, int]:
    try:
        from telethon.tl import functions
        from telethon.tl.tlobject import TLRequest
    except Exception:
        logger.warning("APILimiter: telethon TL functions unavailable")
        return {}
    result: dict[str, int] = {}
    for group_name in _TL_GROUPS:
        group = getattr(functions, group_name, None)
        if group is None:
            continue
        for attr in dir(group):
            method = getattr(group, attr, None)
            if not isinstance(method, type):
                continue
            try:
                if not issubclass(method, TLRequest):
                    continue
            except TypeError:
                continue
            constructor_id = getattr(method, "CONSTRUCTOR_ID", None)
            if constructor_id is None:
                continue
            result[method.__name__.rsplit("Request", 1)[0].lower()] = constructor_id
    return result
CONSTRUCTORS: dict[str, int] = _build_constructors()

_FORBIDDABLE_METHODS: list[str] = [
    "getUserPhotos",
    "sendReaction",
    "joinChannel",
    "importChatInvite",
    "exportChatInvite",
    "leaveChannel",
    "deleteChannel",
    "setPrivacy",
    "updateProfile",
    "updateUsername",
    "changePhone",
    "resetPassword",
    "deleteAccount",
    "editBanned",
    "editAdmin",
    "deleteHistory",
    "addChatUser",
    "inviteToChannel",
    "unblock",
    "block",
]

_DEFAULT_FORBIDDEN: list[str] = [
    "joinChannel",
    "importChatInvite",
    "changePhone",
    "resetPassword",
    "deleteAccount",
]

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

_MONITORED_MODULES: frozenset[str] = frozenset({
    "messages",
    "account",
    "channels",
    "contacts",
    "photos",
    "stickers",
})

class APILimiterModule(KitsuneModule):
    name        = "APILimiter"
    description = "Защита Telegram API от превышения лимитов"
    author      = "@Mikasu32"
    version     = "1.3.0"
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
                "enabled",
                default=True,
                doc="Включить защиту Telethon API",
            ),
            ConfigValue(
                "time_sample",
                default=15,
                doc="[Telethon] Окно мониторинга запросов (секунд)",
            ),
            ConfigValue(
                "threshold",
                default=80,
                doc="[Telethon] Максимум запросов за time_sample до срабатывания защиты",
            ),
            ConfigValue(
                "local_floodwait",
                default=30,
                doc="[Telethon] Время паузы при превышении порога (секунд)",
            ),
            ConfigValue(
                "flood_sleep_threshold",
                default=60,
                doc="[Telethon] Авто-ожидание FloodWait до этого значения секунд (0 = не ждать)",
            ),
            ConfigValue(
                "hydro_enabled",
                default=True,
                doc="Включить rate limiter для Hydrogram",
            ),
            ConfigValue(
                "hydro_max_requests",
                default=20,
                doc="[Hydrogram] Максимум исходящих запросов за hydro_window секунд",
            ),
            ConfigValue(
                "hydro_window",
                default=60,
                doc="[Hydrogram] Окно мониторинга Hydrogram запросов (секунд)",
            ),
            ConfigValue(
                "forbidden_methods",
                default=list(_DEFAULT_FORBIDDEN),
                doc=(
                    "[Telethon] TL-методы, запрещённые внешним модулям. "
                    "Ядро и встроенные модули не ограничиваются"
                ),
                validator=validators.MultiChoice(_FORBIDDABLE_METHODS),
                on_change=lambda: self._apply_forbidden_methods(),
            ),
        )
    async def on_load(self) -> None:
        self._apply_forbidden_methods()
        await asyncio.sleep(5)
        await self._install()
        self._apply_hydro_limits()
        self._apply_telethon_flood_threshold()
    def _apply_forbidden_methods(self) -> None:
        forbid = getattr(self.client, "forbid_constructors", None)
        if not callable(forbid):
            logger.debug(
                "APILimiter: клиент не поддерживает forbid_constructors — "
                "защита от чужих TL-вызовов недоступна"
            )
            return
        names = self.config["forbidden_methods"] or []
        if isinstance(names, str):
            names = [names]
        ids: list[int] = []
        unknown: list[str] = []
        for name in names:
            constructor_id = CONSTRUCTORS.get(str(name).lower())
            if constructor_id is None:
                unknown.append(str(name))
                continue
            ids.append(constructor_id)
        forbid(ids)
        if unknown:
            logger.warning("APILimiter: неизвестные TL-методы в конфиге: %s", ", ".join(unknown))
        logger.info("APILimiter: запрещено внешним модулям %d TL-методов", len(ids))
    @command("api_forbidden", required=OWNER)
    async def forbidden_cmd(self, event) -> None:
        names = self.config["forbidden_methods"] or []
        applied = len(getattr(self.client, "forbidden_constructors", []) or [])
        listing = "\n".join(f"• <code>{n}</code>" for n in names) or "<i>пусто</i>"
        await event.message.edit(
            "🛡 <b>Запрещённые внешним модулям TL-методы</b>\n"
            f"{listing}\n\n"
            f"Активных конструкторов: <b>{applied}</b>\n"
            f"Известно методов в карте: <b>{len(CONSTRUCTORS)}</b>\n\n"
            "Менять список: <code>.cfg APILimiter</code> → <code>forbidden_methods</code>",
            parse_mode="html",
        )
    def _apply_hydro_limits(self) -> None:
        try:
            bridge = getattr(self.client, "_kitsune_hydro_bridge", None)
            if bridge is None:
                loader = getattr(self.client, "_kitsune_loader", None)
                if loader:
                    from ..core.hydro_bridge import HydrogramBridge
                    for obj in vars(self.client).values():
                        if isinstance(obj, HydrogramBridge):
                            bridge = obj
                            break
            if bridge:
                bridge._RL_MAX    = int(self.config["hydro_max_requests"])
                bridge._RL_WINDOW = float(self.config["hydro_window"])
                bridge._rl_enabled = bool(self.config["hydro_enabled"])
                logger.info(
                    "APILimiter: Hydrogram limits applied — max=%d per %.0fs, enabled=%s",
                    bridge._RL_MAX, bridge._RL_WINDOW, bridge._rl_enabled,
                )
        except Exception as exc:
            logger.warning("APILimiter: could not apply Hydrogram limits — %s", exc)
    def _apply_telethon_flood_threshold(self) -> None:
        try:
            threshold = int(self.config["flood_sleep_threshold"])
            self.client.flood_sleep_threshold = threshold
            logger.info("APILimiter: Telethon flood_sleep_threshold set to %ds", threshold)
        except Exception as exc:
            logger.warning("APILimiter: could not apply flood_sleep_threshold — %s", exc)
    async def on_unload(self) -> None:
        self._uninstall()
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
                if req_name not in _SYSTEM_REQUESTS:
                    req_module = getattr(type(request), "__module__", "") or ""
                    if any(f".{mod}." in req_module for mod in _MONITORED_MODULES):
                        now = time.perf_counter()
                        limiter._ratelimiter.append((req_name, now))
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
                            await asyncio.sleep(pause)
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
    @command("suspend_api_protect", required=OWNER)
    async def suspend_cmd(self, event) -> None:
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
        current = self.config["enabled"]
        self.config["enabled"] = not current
        await self.db.set(_DB_OWNER, "enabled", not current)
        state = "включена ✅" if not current else "выключена ❌"
        await event.message.edit(
            f"🛡 Защита API <b>{state}</b>.",
            parse_mode="html",
        )
