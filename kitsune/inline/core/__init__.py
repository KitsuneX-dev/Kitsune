
from __future__ import annotations

import asyncio
import time
import typing

from ..bot_pm import BotPM
from ..events import FSMState
from ..form import Form
from ..gallery import Gallery, ListGalleryHelper
from ..list import InlineList
from ..query_gallery import QueryGallery
from ..types import InlineCall, InlineMessage
from .callbacks import _CallbacksMixin
from .common import (
    _INPUT_MARKER,
    _RAND_ALPHABET,
    _UNIT_TTL,
    AIOGRAM_AVAILABLE,
    logger,
    warn_no_aiogram_once,
)
from .dispatch import _DispatchMixin
from .markup import _InlineTarget, _MarkupMixin
from .sanitize import (
    _HTML_TAG_RE,
    _TG_ALLOWED_TAGS,
    _TG_EMOJI_ANY_CLOSE,
    _TG_EMOJI_ANY_OPEN,
    _TG_EMOJI_VALID,
    _TG_VOID_TAGS,
    _normalize_tg_emoji,
    _sanitize_tg_html,
    _strip_all_html,
    _strip_tg_emoji,
)

if AIOGRAM_AVAILABLE:
    from .common import (
        AiogramMessage,
        Bot,
        CallbackQuery,
        ChosenInlineResult,
        DefaultBotProperties,
        Dispatcher,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        InlineQuery,
        InlineQueryResultArticle,
        InlineQueryResultGif,
        InlineQueryResultVideo,
        InputTextMessageContent,
        ParseMode,
        Router,
    )

class InlineManager(
    _CallbacksMixin,
    _DispatchMixin,
    _MarkupMixin,
    Form,
    InlineList,
    Gallery,
    QueryGallery,
    BotPM,
):
    def __init__(self, client: typing.Any, db: typing.Any, token: str) -> None:
        self._client        = client
        self._db            = db
        self._token         = token
        self._bot:          typing.Any = None
        self._dp:           typing.Any = None
        self._router:       typing.Any = None
        self._callbacks:    dict[str, tuple] = {}
        self._callback_units: dict[str, str]  = {}
        self._error_events: dict[str, typing.Any] = {}
        self._units:        dict[str, dict]  = {}
        self._custom_map:   dict[str, dict]  = {}
        self._bot_username: str | None       = None
        self._bot_id:       int | None       = None
        self._inline_handlers: list[tuple[typing.Callable, bool]] = []
        self._started       = False
        self._query_galleries: dict[str, dict] = {}
        self._fsm            = FSMState()
        self._pm_handlers:   dict[int, tuple] = {}

    @property
    def bot(self) -> typing.Any:
        return self._bot

    @property
    def _me(self) -> int:
        return getattr(self._client, "tg_id", 0) or 0

    @staticmethod
    def _rand(size: int) -> str:
        import random
        return "".join(random.choice(_RAND_ALPHABET) for _ in range(size))

    async def start(self) -> None:
        if not AIOGRAM_AVAILABLE:
            warn_no_aiogram_once(
                "InlineManager.start()",
                "inline bot is not started, inline forms/galleries/lists "
                "and bot PM handlers are unavailable",
            )
            return
        if self._started:
            return
        try:
            from ...rkn_bypass import make_aiogram_bot
            self._bot = make_aiogram_bot(self._token, parse_mode="HTML")
        except Exception as _exc:
            logger.debug("InlineManager: make_aiogram_bot fallback (%s)", _exc)
            self._bot = Bot(
                token=self._token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        self._dp     = Dispatcher()
        self._router = Router()
        self._dp.include_router(self._router)
        self._router.callback_query.register(self._on_callback)
        self._router.inline_query.register(self._on_inline_query)
        self._router.chosen_inline_result.register(self._on_chosen_inline)
        self._router.message.register(self._on_message)
        self._started = True
        asyncio.ensure_future(self._dp.start_polling(self._bot, handle_signals=False))
        asyncio.ensure_future(self._cleaner())
        await asyncio.sleep(3)
        try:
            me = await self._bot.get_me()
            self._bot_username = me.username
            self._bot_id = me.id
        except Exception:
            pass
        logger.info("InlineManager: started")
    async def stop(self) -> None:
        if self._bot and self._started:
            await self._dp.stop_polling()
            await self._bot.session.close()
            self._started = False
    async def _cleaner(self) -> None:
        while True:
            await asyncio.sleep(300)
            now = time.time()
            for uid in list(self._units.keys()):
                if self._units[uid].get("ttl", now + 1) < now:
                    try:
                        await self._unload_unit(uid)
                    except Exception:
                        logger.debug("InlineManager._cleaner: unload failed", exc_info=True)
                        self._units.pop(uid, None)

__all__ = [
    "AIOGRAM_AVAILABLE",
    "InlineManager",
    "ListGalleryHelper",
    "logger",
    "_InlineTarget",
    "_normalize_tg_emoji",
    "_sanitize_tg_html",
    "_strip_all_html",
    "_strip_tg_emoji",
]
