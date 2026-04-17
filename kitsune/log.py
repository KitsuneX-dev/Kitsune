from __future__ import annotations

import asyncio
import inspect
import io
import linecache
import logging
import os
import re
import sys
import traceback
import typing
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".kitsune" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "kitsune.log"

_orig_getlines = linecache.getlines

def _patched_getlines(filename: str, module_globals=None) -> list[str]:
    try:
        if filename.startswith("<") and filename.endswith(">"):
            module_name = filename[1:-1].split(maxsplit=1)[-1]
            if module_name.startswith("kitsune.modules") and module_name in sys.modules:
                src = sys.modules[module_name].__loader__.get_source()
                return [f"{line}\n" for line in src.splitlines()]
    except Exception:
        pass
    return _orig_getlines(filename, module_globals)

linecache.getlines = _patched_getlines

def _override_text(exc: Exception) -> str | None:
    try:
        from aiogram.exceptions import TelegramNetworkError
        if isinstance(exc, TelegramNetworkError):
            return "✈️ <b>Network error on the server side. Check your connection.</b>"
    except ImportError:
        pass
    return None

class KitsuneException:

    __slots__ = ("message", "full_stack", "sysinfo", "debug_url")

    def __init__(
        self,
        message: str,
        full_stack: str,
        sysinfo: tuple | None = None,
    ) -> None:
        self.message = message
        self.full_stack = full_stack
        self.sysinfo = sysinfo
        self.debug_url: str | None = None

    @classmethod
    def from_exc_info(
        cls,
        exc_type: type,
        exc_value: Exception,
        tb: traceback.TracebackType,
        stack: list[inspect.FrameInfo] | None = None,
        comment: typing.Any | None = None,
    ) -> "KitsuneException":
        from . import utils

        _line_re = re.compile(r'  File "(.*?)", line ([0-9]+), in (.+)')

        full_tb = traceback.format_exc().replace("Traceback (most recent call last):\n", "")

        def fmt_line(line: str) -> str:
            m = _line_re.search(line)
            if not m:
                return f"<code>{utils.escape_html(line)}</code>"
            f_, l_, n_ = m.groups()
            return (
                f"👉 <code>{utils.escape_html(f_)}:{l_}</code> <b>in</b>"
                f" <code>{utils.escape_html(n_)}</code>"
            )

        match = next(
            (
                _line_re.search(line).groups()
                for line in reversed(full_tb.splitlines())
                if _line_re.search(line)
            ),
            (None, None, None),
        )
        filename, lineno, name = match

        full_stack = "\n".join(fmt_line(line) for line in full_tb.splitlines())

        caller = utils.find_caller(stack or inspect.stack())
        caller_prefix = ""
        if caller and hasattr(caller, "__self__") and hasattr(caller, "__name__"):
            caller_prefix = (
                "🔮 <b>Cause: method </b><code>{}</code><b> of </b><code>{}</code>\n\n"
            ).format(
                utils.escape_html(caller.__name__),
                utils.escape_html(caller.__self__.__class__.__name__),
            )

        error_text = _override_text(exc_value) or (
            "{prefix}"
            "<b>🎯 Source:</b> <code>{file}:{line}</code><b> in </b><code>{name}</code>\n"
            "<b>❓ Error:</b> <code>{error}</code>{comment}"
        ).format(
            prefix=caller_prefix,
            file=utils.escape_html(str(filename)),
            line=lineno,
            name=utils.escape_html(str(name)),
            error=utils.escape_html(
                "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
            ),
            comment=(
                f"\n💭 <b>Message:</b> <code>{utils.escape_html(str(comment))}</code>"
                if comment
                else ""
            ),
        )

        return cls(message=error_text, full_stack=full_stack, sysinfo=(exc_type, exc_value, tb))

class TelegramChannelHandler(logging.Handler):

    def __init__(self, client: typing.Any, channel_id: int, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self._client = client
        self._channel_id = channel_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._task: asyncio.Task | None = None
        self._formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._worker())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self._formatter.format(record)
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            pass
        except Exception:
            pass

    async def _worker(self) -> None:
        import contextlib

        while True:
            await asyncio.sleep(5)
            lines: list[str] = []
            while not self._queue.empty():
                try:
                    lines.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if not lines:
                continue

            from . import utils

            combined = "\n".join(lines)

            if len(combined) > 3800:
                buf = io.BytesIO(combined.encode())
                buf.name = "kitsune-logs.txt"
                buf.seek(0)
                with contextlib.suppress(Exception):
                    await self._client.send_file(
                        self._channel_id,
                        buf,
                        caption="📋 <b>Kitsune Logs</b>",
                    )
            else:
                with contextlib.suppress(Exception):
                    await self._client.send_message(
                        self._channel_id,
                        f"<code>{utils.escape_html(combined)}</code>",
                        parse_mode="html",
                    )

class KitsuneLogsHandler(logging.Handler):

    def __init__(self, targets: list[logging.Handler], capacity: int = 7000) -> None:
        super().__init__(logging.NOTSET)
        self.targets = targets
        self.capacity = capacity

        self.buffer: list[logging.LogRecord] = []
        self.handledbuffer: list[logging.LogRecord] = []

        self._tg_queue: asyncio.Queue = asyncio.Queue()
        self._mods: dict[int, typing.Any] = {}
        self._task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()

        self.lvl: int = logging.NOTSET
        self.tg_level: int = logging.INFO
        self.force_send_all: bool = False
        self.ignore_common: bool = False
        self.web_debugger: typing.Any = None

    def install_tg_log(self, mod: typing.Any) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._mods[mod.tg_id] = mod
        self._task = asyncio.ensure_future(self._queue_worker())

    async def _queue_worker(self) -> None:
        while True:
            await asyncio.sleep(3)
            await self._flush()

    async def _flush(self) -> None:
        async with self._send_lock:
            items: list[tuple] = []
            while not self._tg_queue.empty():
                try:
                    items.append(self._tg_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if not items:
                return

            for client_id, mod in self._mods.items():
                text_chunks: list[str] = []
                exc_items: list[KitsuneException] = []

                for payload, caller in items:
                    if caller is not None and caller != client_id and not self.force_send_all:
                        continue
                    if isinstance(payload, KitsuneException):
                        exc_items.append(payload)
                    else:
                        text_chunks.append(payload)

                for exc in exc_items:
                    try:
                        await mod.inline.bot.send_message(
                            mod.logchat,
                            exc.message,
                            reply_markup=mod.inline.generate_markup(
                                [{"text": "🪐 Full traceback", "callback": self._show_full_trace, "args": (mod.inline.bot, exc), "disable_security": True}]
                            ),
                        )
                    except Exception:
                        pass

                from . import utils
                combined = utils.escape_html("".join(text_chunks))
                chunked = list(utils.chunks(combined, 4096))

                if len(chunked) > 5:
                    buf = io.BytesIO("".join(chunked).encode())
                    buf.name = "kitsune-logs.txt"
                    buf.seek(0)
                    try:
                        await mod.inline.bot.send_document(
                            mod.logchat, buf,
                            caption="<b>🧳 Logs are too large, sending as file</b>",
                        )
                    except Exception:
                        pass
                    continue

                for chunk in chunked:
                    if chunk:
                        try:
                            await mod.inline.bot.send_message(
                                mod.logchat,
                                f"<code>{chunk}</code>",
                                disable_notification=True,
                            )
                        except Exception:
                            pass

    async def _show_full_trace(self, call: typing.Any, bot: typing.Any, item: KitsuneException) -> None:
        from . import utils
        import telethon.extensions.html as tl_html
        chunks_text = item.message + "\n\n<b>🪐 Full traceback:</b>\n" + item.full_stack
        chunks = list(utils.smart_split(*tl_html.parse(chunks_text), 4096))
        await call.edit(chunks[0])
        for chunk in chunks[1:]:
            await bot.send_message(chat_id=call.chat_id, text=chunk)

    def dump(self) -> list[logging.LogRecord]:
        return self.handledbuffer + self.buffer

    def dumps(self, lvl: int = 0, client_id: int | None = None) -> list[str]:
        return [
            self.targets[0].format(r)
            for r in (self.buffer + self.handledbuffer)
            if r.levelno >= lvl and (not getattr(r, "kitsune_caller", None) or client_id == r.kitsune_caller)
        ]

    def emit(self, record: logging.LogRecord) -> None:
        caller: int | None = None
        try:
            caller = next(
                (
                    fi.frame.f_locals["_kitsune_client_id_logging_tag"]
                    for fi in inspect.stack()
                    if isinstance(
                        fi.frame.f_locals.get("_kitsune_client_id_logging_tag"), int
                    )
                ),
                None,
            )
        except Exception:
            pass

        record.kitsune_caller = caller

        if record.levelno >= self.tg_level:
            if record.exc_info:
                exc = KitsuneException.from_exc_info(
                    *record.exc_info,
                    stack=record.__dict__.get("stack"),
                    comment=record.getMessage(),
                )
                if not self.ignore_common or all(
                    kw not in exc.message
                    for kw in ["InputPeerEmpty()", "entities.html"]
                ):
                    try:
                        self._tg_queue.put_nowait((exc, caller))
                    except asyncio.QueueFull:
                        pass
            else:
                try:
                    self._tg_queue.put_nowait((_tg_formatter.format(record), caller))
                except asyncio.QueueFull:
                    pass

        total = len(self.buffer) + len(self.handledbuffer)
        if total >= self.capacity:
            if self.handledbuffer:
                del self.handledbuffer[0]
            elif self.buffer:
                del self.buffer[0]

        self.buffer.append(record)

        if record.levelno >= self.lvl >= 0:
            self.acquire()
            try:
                for rec in self.buffer:
                    for target in self.targets:
                        if rec.levelno >= target.level:
                            target.handle(rec)
                self.handledbuffer = (
                    self.handledbuffer[-(self.capacity - len(self.buffer)):] + self.buffer
                )
                self.buffer = []
            finally:
                self.release()

    def setLevel(self, level: int) -> None:
        self.lvl = level

_main_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_tg_formatter = logging.Formatter(
    fmt="[%(levelname)s] %(name)s: %(message)s\n",
)

class _NetworkNoiseFilter(logging.Filter):

    _SUPPRESS_FRAGMENTS = (
        "Failed to fetch updates",
        "Sleep for",
        "Server closed the connection",
        "Connection reset by peer",
        "ClientConnectorCertificateError",
        "ClientConnectorError",
        "SSLCertVerificationError",
        "CERTIFICATE_VERIFY_FAILED",
        "ssl:True",
        "ssl:default",
        "ConnectionError",
        "Cannot send requests while disconnected",
        "Cannot connect to host api.telegram.org",
        "Timeout ctx manager",
        "TimeoutError",
        "Error executing high-level request after reconnect",
        "Attempt",
        "Reconnecting",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if record.levelno in (logging.WARNING, logging.ERROR):
            if any(frag in msg for frag in self._SUPPRESS_FRAGMENTS):
                return False
        return True

rotating_handler = RotatingFileHandler(
    filename=str(LOG_FILE),
    mode="a",
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
    delay=False,
)
rotating_handler.setFormatter(_main_formatter)

_tg_channel_handler: TelegramChannelHandler | None = None

async def _get_aiogram_bot(client: typing.Any) -> typing.Any:
    """Ждёт запуска aiogram-бота и возвращает его (или None). Таймаут — 90 секунд."""
    for _ in range(180):
        try:
            loader = getattr(client, "_kitsune_loader", None)
            if loader:
                notifier = loader.modules.get("notifier")
                if notifier and notifier._runner and notifier._runner.bot:
                    return notifier._runner.bot
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return None


async def _ensure_bot_in_group(client: typing.Any, group_id: int) -> bool:
    """Ждёт bot_username до 90 секунд, затем добавляет бота в группу Kitsune-logs."""
    import contextlib

    log = logging.getLogger(__name__)

    # Ждём пока notifier запишет bot_username в БД
    bot_username: str | None = None
    for _ in range(90):
        try:
            db = getattr(client, "_kitsune_db", None)
            if db:
                bot_username = db.get("kitsune.notifier", "bot_username", None)
                if bot_username:
                    break
        except Exception:
            pass
        await asyncio.sleep(1)

    if not bot_username:
        log.warning("log: bot_username не найден за 90с — бот не добавлен в Kitsune-logs")
        return False

    try:
        from telethon.tl.functions.channels import InviteToChannelRequest
        from telethon.errors import UserAlreadyParticipantError

        bot_entity = await client.get_entity(f"@{bot_username}")
        try:
            await client(InviteToChannelRequest(channel=group_id, users=[bot_entity]))
            log.info("log: бот @%s добавлен в Kitsune-logs", bot_username)
        except UserAlreadyParticipantError:
            log.info("log: бот @%s уже в Kitsune-logs", bot_username)
        return True
    except Exception as exc:
        log.warning("log: не удалось добавить бота в группу — %s", exc)
        return False


def _to_bot_api_id(telethon_id: int) -> int:
    """Конвертирует Telethon channel/megagroup ID в Bot API формат (-100xxxxxxx)."""
    peer_id = abs(telethon_id)
    # Если уже в bot-api формате (>= 10^12) — возвращаем как есть с минусом
    if peer_id >= 1_000_000_000_000:
        return -peer_id
    return int(f"-100{peer_id}")


async def setup_tg_logging(client: typing.Any) -> None:
    global _tg_channel_handler

    try:
        from .utils import asset_channel

        # Создаём мегагруппу (или находим существующую)
        group_id, created = await asset_channel(
            client,
            title="Kitsune-logs",
            description="Kitsune Userbot — системные логи",
            archive=True,
            megagroup=True,
        )

        if not group_id:
            logging.getLogger(__name__).error("log: не удалось создать/найти группу Kitsune-logs")
            return

        # Настраиваем хендлер логов (через клиент пользователя — всегда работает)
        handler = TelegramChannelHandler(client, group_id, level=logging.WARNING)
        handler.setFormatter(_tg_formatter)
        handler.start()
        logging.getLogger().addHandler(handler)
        _tg_channel_handler = handler

        logging.getLogger(__name__).info("log: TG logging active (group_id=%d)", group_id)

        # Добавляем бота и отправляем баннер в фоне
        asyncio.ensure_future(_setup_bot_and_banner(client, group_id))

    except Exception:
        logging.getLogger(__name__).exception("log: failed to set up TG channel logging")


async def _setup_bot_and_banner(client: typing.Any, group_id: int) -> None:
    """Добавляет бота в группу и отправляет стартовый баннер от его имени."""
    # Шаг 1: ждём bot_username и добавляем бота в группу
    bot_added = await _ensure_bot_in_group(client, group_id)

    # Шаг 2: ждём пока aiogram бот поднимется
    bot = await _get_aiogram_bot(client)

    # Шаг 3: отправляем баннер
    await _send_startup_banner_via_bot(client, group_id, bot=bot, bot_added=bot_added)

async def _send_startup_banner_via_bot(client: typing.Any, group_id: int) -> None:
    """Отправляет стартовый баннер через бота (не от имени пользователя)."""
    import contextlib
    import os

    # Ждём запуска бота
    bot = await _get_aiogram_bot(client)

    try:
        from .version import __version_str__, branch

        commit_sha = "unknown"
        commit_url = ""
        with contextlib.suppress(Exception):
            import git
            repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            repo = git.Repo(path=repo_path)
            commit_sha = repo.head.commit.hexsha[:7]
            commit_url = f"https://github.com/KitsuneX-dev/Kitsune/commit/{repo.head.commit.hexsha}"

        update_status = "✅ Актуальная версия"
        with contextlib.suppress(Exception):
            import git
            repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            repo = git.Repo(path=repo_path)
            repo.remotes.origin.fetch()
            behind = list(repo.iter_commits(f"HEAD..origin/{branch}"))
            if behind:
                update_status = f"🆕 Доступно обновление ({len(behind)} коммитов)"

        cfg_web_port = 8080
        with contextlib.suppress(Exception):
            from .main import get_config_key
            cfg_web_port = int(get_config_key("web_port", 8080))

        sha_line = (
            f'<a href="{commit_url}">{commit_sha}</a>'
            if commit_url
            else f"<code>{commit_sha}</code>"
        )

        me = await client.get_me()
        text = (
            f"🌘 <b>Kitsune {__version_str__} запущен!</b>\n\n"
            f"👤 Аккаунт: <b>{me.first_name}</b> (id: <code>{me.id}</code>)\n"
            f"🌳 Commit: {sha_line}\n"
            f"✊ Обновление: {update_status}\n"
            f"🌐 Web: <code>http://127.0.0.1:{cfg_web_port}</code>"
        )

        gif_path = os.path.join(os.path.dirname(__file__), "..", "banner.gif")

        if bot:
            # Отправляем через бота (не от лица пользователя)
            if os.path.exists(gif_path):
                with contextlib.suppress(Exception):
                    from aiogram.types import FSInputFile
                    await bot.send_animation(group_id, FSInputFile(gif_path), caption=text)
                    return
            with contextlib.suppress(Exception):
                await bot.send_message(group_id, text, disable_web_page_preview=True)
                return

        # Фолбэк — отправляем через клиент пользователя
        if os.path.exists(gif_path):
            with contextlib.suppress(Exception):
                await client.send_file(group_id, gif_path, caption=text, parse_mode="html")
                return
        await client.send_message(group_id, text, parse_mode="html", link_preview=False)

    except Exception:
        logging.getLogger(__name__).exception("log: failed to send startup banner")


async def _send_startup_banner(client: typing.Any, channel_id: int) -> None:
    """Устаревший метод — перенаправляет на новый."""
    await _send_startup_banner_via_bot(client, channel_id)

def init() -> None:
    import sys
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(_main_formatter)

    root = logging.getLogger()
    root.handlers = []
    root.addHandler(KitsuneLogsHandler([console_handler, rotating_handler], capacity=7000))
    root.setLevel(logging.NOTSET)

    for noisy in ("telethon", "pyrogram", "matplotlib", "aiohttp", "aiogram", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _network_noise_filter = _NetworkNoiseFilter()
    # Глушим сетевой шум (особенно при переключении VPN/локации)
    for _noisy_logger in (
        "aiogram.dispatcher",
        "telethon.network.connection.connection",
        "telethon.network.mtprotosender",
        "telethon.client.updates",
        "telethon.client.users",
        "telethon.extensions.messagepacker",
    ):
        logging.getLogger(_noisy_logger).addFilter(_network_noise_filter)

    logging.captureWarnings(True)
