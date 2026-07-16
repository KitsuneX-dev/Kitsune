from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html, auto_delete, truncate

logger = logging.getLogger(__name__)

_TIMEOUT = 120
_MAX_OUT = 3000
_MAX_ERR = 3000


def _venv_aware_env() -> dict[str, str]:
    """Собрать окружение для подпроцесса, осознающее venv бота."""
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "DEBIAN_FRONTEND": "noninteractive",
    }

    bin_dir = os.path.dirname(os.path.abspath(sys.executable))
    if bin_dir:
        old_path = env.get("PATH", "")
        parts = old_path.split(os.pathsep) if old_path else []
        if bin_dir not in parts:
            env["PATH"] = os.pathsep.join([bin_dir, *parts]) if parts else bin_dir

    venv_root = os.path.dirname(bin_dir)
    if venv_root and os.path.isfile(os.path.join(venv_root, "pyvenv.cfg")):
        env["VIRTUAL_ENV"] = venv_root
        env.pop("PYTHONHOME", None)

    return env


class TerminalModule(KitsuneModule):
    name        = "terminal"
    description = "Shell command execution"
    author      = "Yushi"
    version     = "1.4.0"
    icon        = "🖥"
    category    = "system"

    strings_ru = {
        "no_cmd":    "❌ Укажи команду: <code>.sh ls -la</code>",
        "running":   "⏳ Выполняю...",
        "timeout":   "⏱ <b>Таймаут</b> ({t}с)\n\n<blockquote expandable>{out}</blockquote>",
        "result":    "🖥 <b>$</b> <code>{cmd}</code>\n\n<blockquote expandable>{out}</blockquote>",
        "result_err":"🖥 <b>$</b> <code>{cmd}</code> → <b>rc={rc}</b>\n\n<blockquote expandable>{err}</blockquote>",
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
        env = _venv_aware_env()
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                env=env,
                preexec_fn=os.setsid,
            )
        except Exception as exc:
            await event.edit(
                f"❌ <b>Failed to start process:</b>\n<blockquote expandable>{escape_html(str(exc))}</blockquote>",
                parse_mode="html",
            )
            return

        self._current_proc = proc
        self._current_pid = proc.pid
        timed_out = False

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_TIMEOUT
            )
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
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
            except Exception:
                stdout_bytes, stderr_bytes = b"", b""
        finally:
            self._current_proc = None
            self._current_pid = None

        rc = proc.returncode
        stdout_raw = stdout_bytes.decode(errors="replace").strip()
        stderr_raw = stderr_bytes.decode(errors="replace").strip()

        if timed_out:
            out = escape_html(stdout_raw) if stdout_raw else self.strings("empty_out")
            out = truncate(out, _MAX_OUT)
            await event.edit(
                self.strings("timeout").format(t=_TIMEOUT, out=out),
                parse_mode="html",
            )
            await auto_delete(event)
            return

        if rc != 0:
            if stderr_raw:
                err_text = escape_html(stderr_raw)
            elif stdout_raw:
                lines = stdout_raw.splitlines()
                err_lines = [l for l in lines if l.strip()]
                err_text = escape_html("\n".join(err_lines[-30:]))
            else:
                err_text = self.strings("empty_out")
            err_text = truncate(err_text, _MAX_ERR)
            await event.edit(
                self.strings("result_err").format(
                    cmd=escape_html(cmd), rc=rc, err=err_text
                ),
                parse_mode="html",
            )
            await auto_delete(event)
            return

        out_raw = stdout_raw or ""
        out = escape_html(out_raw) if out_raw else self.strings("empty_out")
        out = truncate(out, _MAX_OUT)
        await event.edit(
            self.strings("result").format(cmd=escape_html(cmd), out=out),
            parse_mode="html",
        )
        await auto_delete(event)
