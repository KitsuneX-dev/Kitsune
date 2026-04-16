from __future__ import annotations

import asyncio
import logging
import os
import signal

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html, auto_delete, truncate

logger = logging.getLogger(__name__)

_TIMEOUT      = 30
_MAX_OUTPUT   = 3500
_HEADER_SHELL = "🖥 <b>Terminal</b>"
_HEADER_SUDO  = "🔐 <b>Terminal (sudo)</b>"

class TerminalModule(KitsuneModule):
    name        = "terminal"
    description = "Shell command execution"
    author      = "Yushi"
    version     = "1.0"
    icon        = "🖥"
    category    = "system"

    strings_ru = {
        "no_cmd":    "❌ Укажи команду: <code>.term ls -la</code>",
        "running":   "⏳ Выполняю...",
        "timeout":   "⏱ <b>Таймаут</b> ({t}с)\n\n<b>Вывод:</b>\n<code>{out}</code>",
        "killed":    "🛑 <b>Процесс завершён</b>\n\n<b>Вывод:</b>\n<code>{out}</code>",
        "result":    "🖥 <b>$</b> <code>{cmd}</code>\n\n<code>{out}</code>",
        "result_rc": "🖥 <b>$</b> <code>{cmd}</code> → <b>rc={rc}</b>\n\n<code>{out}</code>",
        "empty_out": "<i>нет вывода</i>",
        "no_pid":    "❌ Нет активного процесса.",
        "killed_ok": "🛑 Процесс (PID {pid}) завершён.",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current_proc: asyncio.subprocess.Process | None = None
        self._current_pid: int | None = None

    @command("term", required=OWNER, aliases=["sh", "shell"])
    async def term_cmd(self, event) -> None:
        args = self.get_args(event)
        if not args:
            await event.edit(self.strings("no_cmd"), parse_mode="html")
            return

        await event.edit(self.strings("running"), parse_mode="html")
        await self._run(event, args, use_sudo=False)

    @command("sterms", required=OWNER)
    async def sudo_term_cmd(self, event) -> None:
        args = self.get_args(event)
        if not args:
            await event.edit(self.strings("no_cmd"), parse_mode="html")
            return

        await event.edit(self.strings("running"), parse_mode="html")
        await self._run(event, args, use_sudo=True)

    @command("termkill", required=OWNER)
    async def termkill_cmd(self, event) -> None:
        if self._current_proc is None or self._current_pid is None:
            await event.edit(self.strings("no_pid"), parse_mode="html")
            return

        pid = self._current_pid
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            try:
                self._current_proc.kill()
            except Exception:
                pass

        await event.edit(self.strings("killed_ok").format(pid=pid), parse_mode="html")
        self._current_proc = None
        self._current_pid = None
        await auto_delete(event)

    async def _run(self, event, cmd: str, *, use_sudo: bool) -> None:
        if use_sudo and not cmd.startswith("sudo "):
            cmd = f"sudo {cmd}"

        env = {**os.environ, "TERM": "xterm-256color"}

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
                env=env,
                preexec_fn=os.setsid,
            )
        except Exception as exc:
            await event.edit(
                f"❌ <b>Failed to start process:</b>\n<code>{escape_html(str(exc))}</code>",
                parse_mode="html",
            )
            return

        self._current_proc = proc
        self._current_pid = proc.pid

        stdout_chunks: list[bytes] = []
        timed_out = False

        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=_TIMEOUT
            )
            stdout_chunks = [stdout_bytes]
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                stdout_chunks = [stdout_bytes]
            except Exception:
                stdout_chunks = []
        finally:
            self._current_proc = None
            self._current_pid = None

        raw_out = b"".join(stdout_chunks).decode(errors="replace").strip()
        out = escape_html(raw_out) if raw_out else self.strings("empty_out")
        out = truncate(out, _MAX_OUTPUT)

        rc = proc.returncode

        if timed_out:
            text = self.strings("timeout").format(t=_TIMEOUT, out=out)
        elif rc != 0:
            text = self.strings("result_rc").format(
                cmd=escape_html(cmd), rc=rc, out=out
            )
        else:
            text = self.strings("result").format(cmd=escape_html(cmd), out=out)

        await event.edit(text, parse_mode="html")
        await auto_delete(event)
