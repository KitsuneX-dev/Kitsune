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


async def setup_tg_logging(client: typing.Any) -> None:
    global _tg_channel_handler

    try:
        from .utils import asset_channel

        channel_id, created = await asset_channel(
            client,
            title="Kitsune-logs",
            description="Kitsune Userbot — system logs",
            archive=True,
        )

        handler = TelegramChannelHandler(client, channel_id, level=logging.WARNING)
        handler.setFormatter(_tg_formatter)
        handler.start()

        logging.getLogger().addHandler(handler)
        _tg_channel_handler = handler

        await _send_startup_banner(client, channel_id)

        logging.getLogger(__name__).info("log: TG channel logging active (channel_id=%d)", channel_id)

    except Exception:
        logging.getLogger(__name__).exception("log: failed to set up TG channel logging")


async def _send_startup_banner(client: typing.Any, channel_id: int) -> None:
    import contextlib
    import os

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

        update_status = "✅ Up-to-date"
        with contextlib.suppress(Exception):
            import git
            repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            repo = git.Repo(path=repo_path)
            repo.remotes.origin.fetch()
            behind = list(repo.iter_commits(f"HEAD..origin/{branch}"))
            if behind:
                update_status = f"🆕 Update available ({len(behind)} commits)"

        cfg_web_port = 8080
        with contextlib.suppress(Exception):
            from .main import get_config_key
            cfg_web_port = int(get_config_key("web_port", 8080))

        sha_line = (
            f'<a href="{commit_url}">{commit_sha}</a>'
            if commit_url
            else f"<code>{commit_sha}</code>"
        )

        text = (
            f"🌘 <b>Kitsune {__version_str__} started!</b>\n\n"
            f"🌳 GitHub commit SHA: {sha_line}\n"
            f"✊ Update status: {update_status}\n"
            f"🌐 Web url: <code>http://127.0.0.1:{cfg_web_port}</code>"
        )

        gif_path = os.path.join(os.path.dirname(__file__), "..", "banner.gif")
        if os.path.exists(gif_path):
            with contextlib.suppress(Exception):
                await client.send_file(
                    channel_id,
                    gif_path,
                    caption=text,
                    parse_mode="html",
                )
                return

        await client.send_message(channel_id, text, parse_mode="html", link_preview=False)

    except Exception:
        logging.getLogger(__name__).exception("log: failed to send startup banner")