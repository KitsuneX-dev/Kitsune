from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER


class WarpModule(KitsuneModule):
    name        = "warp"
    description = "Cloudflare WARP — работа без VPN/прокси"
    author      = "Yushi"
    version     = "1.0"

    strings_ru = {
        "not_installed": (
            "❌ <b>Cloudflare WARP не установлен.</b>\n\n"
            "Установи командой:\n"
            "<code>.warp install</code>"
        ),
        "installing": "⏳ Устанавливаю Cloudflare WARP...",
        "install_ok": "✅ <b>WARP установлен!</b> Теперь запусти <code>.warp on</code>",
        "install_fail": "❌ Ошибка установки:\n<code>{err}</code>",
        "connecting": "⏳ Подключаюсь к WARP...",
        "disconnecting": "⏳ Отключаюсь от WARP...",
        "connected": (
            "🌐 <b>WARP подключён!</b>\n\n"
            "🔒 Статус: <code>{status}</code>\n"
            "📡 IP: <code>{ip}</code>"
        ),
        "disconnected": "🔴 <b>WARP отключён.</b>",
        "status_header": "🌐 <b>WARP статус:</b>\n\n<code>{output}</code>",
        "already_on":  "ℹ️ WARP уже подключён.",
        "already_off": "ℹ️ WARP уже отключён.",
        "error": "❌ Ошибка:\n<code>{err}</code>",
        "usage": (
            "❓ <b>Использование:</b>\n\n"
            "  <code>.warp on</code>      — подключить\n"
            "  <code>.warp off</code>     — отключить\n"
            "  <code>.warp status</code>  — статус\n"
            "  <code>.warp install</code> — установить WARP\n"
            "  <code>.warp ip</code>      — показать IP"
        ),
    }

    def _warp_bin(self) -> str | None:
        return shutil.which("warp-cli") or shutil.which("warp")

    def _is_termux(self) -> bool:
        return (
            "com.termux" in os.environ.get("PREFIX", "")
            or os.path.isdir("/data/data/com.termux")
        )

    async def _run(self, *args: str, timeout: int = 30) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 1, "", "timeout"
        return proc.returncode, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()

    async def _get_ip(self) -> str:
        for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
            try:
                import aiohttp
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        return (await r.text()).strip()
            except Exception:
                continue
        return "—"

    async def _warp_status(self) -> str:
        bin_ = self._warp_bin()
        if not bin_:
            return "not_installed"
        rc, out, _ = await self._run(bin_, "status")
        return out.lower() if rc == 0 else "error"

    @command("warp", required=OWNER)
    async def warp_cmd(self, event) -> None:
        arg = self.get_args(event).strip().lower()
        m = await event.reply("⏳", parse_mode="html")

        if not arg or arg == "help":
            await m.edit(self.strings("usage"), parse_mode="html")
            return

        if arg == "install":
            await m.edit(self.strings("installing"), parse_mode="html")
            err = await self._install_warp()
            if err:
                await m.edit(self.strings("install_fail").format(err=err), parse_mode="html")
            else:
                await m.edit(self.strings("install_ok"), parse_mode="html")
            return

        bin_ = self._warp_bin()
        if not bin_:
            await m.edit(self.strings("not_installed"), parse_mode="html")
            return

        if arg == "status":
            rc, out, err = await self._run(bin_, "status")
            text = out or err or "нет данных"
            await m.edit(self.strings("status_header").format(output=text), parse_mode="html")
            return

        if arg == "ip":
            ip = await self._get_ip()
            await m.edit(f"📡 <b>Текущий IP:</b> <code>{ip}</code>", parse_mode="html")
            return

        if arg == "on":
            status = await self._warp_status()
            if "connected" in status:
                await m.edit(self.strings("already_on"), parse_mode="html")
                return
            await m.edit(self.strings("connecting"), parse_mode="html")
            rc, out, err = await self._run(bin_, "connect")
            if rc != 0:
                await m.edit(self.strings("error").format(err=err or out), parse_mode="html")
                return
            await asyncio.sleep(3)
            ip = await self._get_ip()
            new_status = await self._warp_status()
            await m.edit(
                self.strings("connected").format(status=new_status or "connected", ip=ip),
                parse_mode="html",
            )
            return

        if arg == "off":
            status = await self._warp_status()
            if "disconnected" in status:
                await m.edit(self.strings("already_off"), parse_mode="html")
                return
            await m.edit(self.strings("disconnecting"), parse_mode="html")
            rc, out, err = await self._run(bin_, "disconnect")
            if rc != 0:
                await m.edit(self.strings("error").format(err=err or out), parse_mode="html")
                return
            await m.edit(self.strings("disconnected"), parse_mode="html")
            return

        await m.edit(self.strings("usage"), parse_mode="html")

    async def _install_warp(self) -> str | None:
        if self._is_termux():
            return await self._install_termux()
        return await self._install_linux()

    async def _install_termux(self) -> str | None:
        rc, _, err = await self._run(
            "pkg", "install", "-y", "cloudflare-warp",
            timeout=120,
        )
        if rc == 0:
            return None
        rc2, _, err2 = await self._run(
            "bash", "-c",
            "curl -fsSL https://pkg.cloudflareclient.com/cloudflare-warp-ascii.gpg | gpg --dearmor -o /data/data/com.termux/files/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg 2>&1 && echo 'deb [arch=aarch64 signed-by=/data/data/com.termux/files/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ bookworm main' > /data/data/com.termux/files/usr/etc/apt/sources.list.d/cloudflare-client.list && pkg update -y && pkg install -y cloudflare-warp 2>&1",
            timeout=180,
        )
        return None if rc2 == 0 else (err2 or err)[:500]

    async def _install_linux(self) -> str | None:
        script = (
            "curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | "
            "sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg && "
            "echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] "
            "https://pkg.cloudflareclient.com/ bookworm main' | "
            "sudo tee /etc/apt/sources.list.d/cloudflare-client.list && "
            "sudo apt-get update -qq && "
            "sudo apt-get install -y cloudflare-warp"
        )
        rc, _, err = await self._run("bash", "-c", script, timeout=180)
        if rc == 0:
            await self._run("warp-cli", "register", timeout=30)
            return None
        return err[:500]
