from __future__ import annotations
import contextlib
import io
import logging
import typing
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..version import __version_str__
from .. import utils
from ..utils.git import get_current_commit

logger = logging.getLogger(__name__)

_REPO_URL = "https://github.com/KitsuneX-dev/Kitsune"

_LEVELS: list[tuple[str, int]] = [
    ("☢️ Critical", logging.CRITICAL),
    ("🚫 Error", logging.ERROR),
    ("⚠️ Warning", logging.WARNING),
    ("ℹ️ Info", logging.INFO),
    ("🐞 Debug", logging.DEBUG),
    ("🧑‍💻 All", 0),
]


class LogsModule(KitsuneModule):
    name        = "logs"
    description = "Просмотр логов бота из чата"
    author      = "Yushi"
    version     = "1.0.0"
    icon        = "🌙"
    category    = "system"
    strings_ru = {
        "choose_level":  "💁‍♂️ <b>Выбери уровень логов</b>",
        "set_level":     "🚫 <b>Укажи уровень логов числом или названием.</b>\n\nНапример: <code>.logs 30</code> или <code>.logs warning</code>",
        "bad_level":     "❌ <b>Неизвестный уровень логов:</b> <code>{level}</code>",
        "no_logs":       "🤷‍♀️ <b>Логов уровня</b> <code>{level}</code> <b>нет.</b>",
        "confidential":  "⚠️ <b>Уровень логов</b> <code>{level}</code> <b>может содержать личные данные, будь осторожен.</b>",
        "confidential_text": "⚠️ <b>Уровень логов</b> <code>{level}</code> <b>может содержать личные данные, будь осторожен.</b>\n\nНапиши <code>.logs {level} force</code>, чтобы отправить, игнорируя предупреждение.",
        "caption":       "🌙 <b>Логи Kitsune уровня</b> <code>{level}</code>\n\n⚪️ <b>Версия: {version}</b>{commit}",
        "send_anyway":   "📤 Всё равно отправить",
        "cancel":        "🚫 Отмена",
        "sending":       "⏳ <b>Собираю логи...</b>",
    }
    strings_en = {
        "choose_level":  "💁‍♂️ <b>Choose log level</b>",
        "set_level":     "🚫 <b>Specify log level as a number or a name.</b>\n\nFor example: <code>.logs 30</code> or <code>.logs warning</code>",
        "bad_level":     "❌ <b>Unknown log level:</b> <code>{level}</code>",
        "no_logs":       "🤷‍♀️ <b>You have no logs with verbosity</b> <code>{level}</code><b>.</b>",
        "confidential":  "⚠️ <b>Log level</b> <code>{level}</code> <b>may reveal your confidential info, be careful.</b>",
        "confidential_text": "⚠️ <b>Log level</b> <code>{level}</code> <b>may reveal your confidential info, be careful.</b>\n\nType <code>.logs {level} force</code> to send anyway.",
        "caption":       "🌙 <b>Kitsune logs with verbosity</b> <code>{level}</code>\n\n⚪️ <b>Version: {version}</b>{commit}",
        "send_anyway":   "📤 Send anyway",
        "cancel":        "🚫 Cancel",
        "sending":       "⏳ <b>Collecting logs...</b>",
    }

    @command("logs", required=OWNER, ru_doc="[уровень] — прислать логи бота файлом", en_doc="[level] — send bot logs as a file")
    async def logs_cmd(self, event) -> None:
        args = self.get_args(event).split()
        force = any(a.lower() in ("force", "force_insecure") for a in args)
        raw = next((a for a in args if a.lower() not in ("force", "force_insecure")), None)
        if raw is None:
            await self._offer_levels(event)
            return
        level = self._parse_level(raw)
        if level is None:
            await utils.answer(event.message, self.strings("bad_level").format(level=utils.escape_html(raw)))
            return
        await self._deliver(event, level, force)

    def _inline(self) -> typing.Any:
        return self.inline or getattr(self.client, "_kitsune_inline", None)

    @staticmethod
    def _parse_level(raw: str) -> int | None:
        try:
            return int(raw)
        except ValueError:
            pass
        candidate = getattr(logging, raw.upper(), None)
        if isinstance(candidate, int):
            return candidate
        if raw.lower() == "all":
            return 0
        return None

    @staticmethod
    def _level_name(level: int) -> str:
        return logging.getLevelName(level) if level in logging._levelToName else str(level)

    async def _offer_levels(self, event) -> None:
        inline = self._inline()
        if inline is None:
            await utils.answer(event.message, self.strings("set_level"))
            return
        markup = utils.chunks(
            [
                {"text": title, "callback": self._cb_level, "args": (level, False)}
                for title, level in _LEVELS
            ],
            2,
        )
        markup.append([{"text": self.strings("cancel"), "action": "close"}])
        try:
            sent = await inline.form(self.strings("choose_level"), event.message, markup)
        except Exception:
            logger.debug("logs: inline form failed", exc_info=True)
            sent = False
        if not sent:
            await utils.answer(event.message, self.strings("set_level"))

    async def _cb_level(self, call, level: int, force: bool) -> None:
        await self._deliver(call, level, force)

    async def _deliver(self, origin, level: int, force: bool) -> None:
        named = self._level_name(level)
        if level < logging.WARNING and not force:
            await self._warn_confidential(origin, level)
            return
        text = self._collect(level)
        if not text.strip():
            await self._respond(origin, self.strings("no_logs").format(level=named))
            return
        buf = io.BytesIO(self._censor(text).encode("utf-8"))
        buf.name = "kitsune-logs.txt"
        commit = get_current_commit()
        caption = self.strings("caption").format(
            level=named,
            version=__version_str__,
            commit=f' <a href="{_REPO_URL}/commit/{commit}">@{commit}</a>' if commit else "",
        )
        chat_id, reply_to = self._destination(origin)
        if chat_id is None:
            await self._respond(origin, self.strings("no_logs").format(level=named))
            return
        await self.client.send_file(chat_id, buf, caption=caption, reply_to=reply_to)
        if not self._is_event(origin):
            with contextlib.suppress(Exception):
                await origin.answer("✅")

    async def _warn_confidential(self, origin, level: int) -> None:
        named = self._level_name(level)
        inline = self._inline()
        markup = [
            [
                {"text": self.strings("send_anyway"), "callback": self._cb_level, "args": (level, True)},
                {"text": self.strings("cancel"), "action": "close"},
            ]
        ]
        text = self.strings("confidential").format(level=named)
        if not self._is_event(origin):
            if inline is not None:
                with contextlib.suppress(Exception):
                    await inline.edit(origin, text, reply_markup=markup)
                    return
            with contextlib.suppress(Exception):
                await origin.edit(text)
            return
        if inline is not None:
            try:
                if await inline.form(text, origin.message, markup):
                    return
            except Exception:
                logger.debug("logs: confidential form failed", exc_info=True)
        await utils.answer(origin.message, self.strings("confidential_text").format(level=named))

    async def _respond(self, origin, text: str) -> None:
        if self._is_event(origin):
            await utils.answer(origin.message, text)
            return
        inline = self._inline()
        if inline is not None:
            with contextlib.suppress(Exception):
                await inline.edit(origin, text)
                return
        with contextlib.suppress(Exception):
            await origin.edit(text)

    @staticmethod
    def _is_event(origin) -> bool:
        return getattr(origin, "message", None) is not None

    def _destination(self, origin) -> tuple[typing.Any, typing.Any]:
        if self._is_event(origin):
            message = origin.message
            return (
                getattr(message, "chat_id", None) or getattr(message, "peer_id", None),
                getattr(message, "reply_to_msg_id", None),
            )
        return getattr(origin, "chat_id", None) or None, None

    def _collect(self, level: int) -> str:
        parts: list[str] = []
        for handler in logging.getLogger().handlers:
            if not hasattr(handler, "dumps"):
                continue
            try:
                lines = handler.dumps(level, client_id=None)
            except TypeError:
                try:
                    lines = handler.dumps(level)
                except Exception:
                    continue
            except Exception:
                continue
            if lines:
                parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def _censor(self, text: str) -> str:
        phone = getattr(getattr(self.client, "tg_me", None), "phone", None)
        if phone:
            text = text.replace(str(phone), "<phone>")
        token = None
        with contextlib.suppress(Exception):
            token = self.db.get("kitsune.notifier", "bot_token", None)
        if token and isinstance(token, str) and ":" in token:
            text = text.replace(token, f"{token.split(':')[0]}:{'*' * 26}")
        elif token and isinstance(token, str):
            text = text.replace(token, "*" * 26)
        for session in self._session_strings():
            if session and len(session) > 16:
                text = text.replace(session, "StringSession(**************************)")
        return text

    def _session_strings(self) -> list[str]:
        found: list[str] = []
        session = getattr(self.client, "session", None)
        if session is None:
            return found
        with contextlib.suppress(Exception):
            from telethon.sessions import StringSession

            saved = StringSession.save(session)
            if isinstance(saved, str):
                found.append(saved)
        for attr in ("auth_key",):
            key = getattr(session, attr, None)
            data = getattr(key, "key", None)
            if isinstance(data, bytes):
                with contextlib.suppress(Exception):
                    found.append(data.hex())
        return found
