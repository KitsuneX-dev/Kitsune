from __future__ import annotations
import asyncio
import io
import sys
import traceback
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..utils import escape_html, truncate
from ..utils.proc import run_cmd


_SH_TIMEOUT = 30

class EvalModule(KitsuneModule):
    name        = "eval"
    description = "Python eval/exec и терминал"
    version     = "1.3.0"
    author      = "Yushi"
    @command("e", required=OWNER)
    async def eval_cmd(self, event) -> None:
        code = event.message.text.split(maxsplit=1)
        if len(code) < 2:
            await event.reply("❌ Укажи выражение.", parse_mode="html")
            return
        expr = code[1].strip()
        if expr.startswith("r.text"):
            from .info import InfoModule
            info_mod = InfoModule.__new__(InfoModule)
            info_mod.client = self.client
            info_mod.db     = self.db
            await info_mod.emoji_cmd(event)
            return
        result, err = await self._eval(expr, event)
        if err:
            out = f"❌ <b>Ошибка:</b>\n<code>{escape_html(err)}</code>"
        else:
            out = (
                f"<b>📥 Вход:</b> <code>{escape_html(truncate(expr, 256))}</code>\n"
                f"<b>📤 Выход:</b> <code>{escape_html(truncate(str(result), 3000))}</code>"
            )
        await event.reply(out, parse_mode="html")
    @command("ex", required=OWNER)
    async def exec_cmd(self, event) -> None:
        parts = event.message.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.reply("❌ Укажи код.", parse_mode="html")
            return
        code = parts[1].strip()
        stdout, err = await self._exec(code, event)
        if err:
            out = f"❌ <b>Ошибка:</b>\n<code>{escape_html(err)}</code>"
        elif stdout:
            out = f"<b>📤 Вывод:</b>\n<code>{escape_html(truncate(stdout, 3000))}</code>"
        else:
            out = "✅ Выполнено (нет вывода)."
        await event.reply(out, parse_mode="html")
    @command("sh", required=OWNER)
    async def shell_cmd(self, event) -> None:
        parts = event.message.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.reply("❌ Укажи команду.", parse_mode="html")
            return
        cmd = parts[1].strip()
        m = await event.reply(f"⏳ <code>{escape_html(cmd)}</code>", parse_mode="html")
        try:


            rc, stdout, stderr = await run_cmd(
                cmd,
                timeout=_SH_TIMEOUT,
                shell=True,
            )
            if rc == -9 and not stdout:
                output = f"⏰ Timeout ({_SH_TIMEOUT}s)"
            else:
                output = (stdout + stderr).decode(errors="replace").strip()
            out = (
                f"<b>$</b> <code>{escape_html(cmd)}</code>\n"
                f"<code>{escape_html(truncate(output, 3000))}</code>"
            )
        except Exception as exc:
            out = f"❌ <code>{escape_html(str(exc))}</code>"
        await m.edit(out, parse_mode="html")
    async def _eval(self, expr: str, event) -> tuple[object, str]:
        try:
            from meval import meval
            result = await meval(expr, globals(), event=event, client=self.client, db=self.db)
            return result, ""
        except Exception:
            return None, traceback.format_exc()
    async def _exec(self, code: str, event) -> tuple[str, str]:
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            exec_globals = {
                "event":  event,
                "client": self.client,
                "db":     self.db,
                "asyncio": asyncio,
            }
            exec_code = f"async def _kitsune_exec():\n" + "\n".join(
                f"    {line}" for line in code.splitlines()
            )
            local_ns: dict = {}
            exec(compile(exec_code, "<exec>", "exec"), exec_globals, local_ns)
            await local_ns["_kitsune_exec"]()
            return buf.getvalue(), ""
        except Exception:
            return buf.getvalue(), traceback.format_exc()
        finally:
            sys.stdout = old_stdout
