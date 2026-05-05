from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

logger = logging.getLogger(__name__)


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_cfg() -> dict:
    from ..main import _load_raw_config
    return _load_raw_config() or {}


def _save_cfg(cfg: dict) -> None:
    from ..main import _save_config
    _save_config(cfg)


class ProxyCtl(KitsuneModule):
    """
    Управление прокси из чата:

      • .setproxy <host> <port> <secret>  — задать MTPROTO-прокси (Telethon)
      • .delproxy                          — удалить MTPROTO-прокси
      • .setsocks <host> <port> [user] [pass]
                                           — задать SOCKS5 (aiogram, notifier-бот)
      • .delsocks                          — удалить SOCKS5
      • .proxyinfo                         — показать оба прокси

    Зачем два прокси:
      Telethon умеет MTPROTO напрямую (для основного юзер-клиента).
      aiogram (notifier-бот, update_checker) MTPROTO НЕ поддерживает —
      ему нужен HTTP/SOCKS5 для api.telegram.org. Поэтому конфиг хранит
      их в разных секциях: [proxy] для MTPROTO и [proxy_socks] для SOCKS5.
    """

    name        = "ProxyCtl"
    description = "Управление MTPROTO/SOCKS5 прокси (Telethon + aiogram)"
    author      = "Kitsune Team"
    version     = "1.0"
    icon        = "🛰"
    category    = "system"

    # ── MTPROTO (Telethon) ────────────────────────────────────────────

    @command("setproxy", required=OWNER)
    async def setproxy_cmd(self, event) -> None:
        """.setproxy <host> <port> <secret> — задать MTPROTO-прокси (Telethon)."""
        args = (self.get_args(event) or "").split()
        if len(args) < 3:
            await event.reply(
                "❌ Использование:\n"
                "<code>.setproxy &lt;host&gt; &lt;port&gt; &lt;secret&gt;</code>\n\n"
                "Пример:\n"
                "<code>.setproxy germany.tgproxy11.online 443 "
                "eed28a6a29973dc4b3ca4d87955796b30f6765726d616e792e746770726f787931312e6f6e6c696e65</code>",
                parse_mode="html",
            )
            return

        host, port, secret = args[0], args[1], args[2]
        try:
            port = int(port)
        except ValueError:
            await event.reply("❌ Порт должен быть числом.", parse_mode="html")
            return

        from ..rkn_bypass import normalize_secret
        secret_n = normalize_secret(secret)

        cfg = _load_cfg()
        cfg["proxy"] = {
            "type":   "MTPROTO",
            "host":   host,
            "port":   port,
            "secret": secret_n,
        }
        _save_cfg(cfg)

        await event.reply(
            "✅ <b>MTPROTO-прокси сохранён в config.toml:</b>\n"
            f"• host: <code>{_esc(host)}</code>\n"
            f"• port: <code>{port}</code>\n"
            f"• secret: <code>{_esc(secret_n[:24])}…</code>\n\n"
            "🔁 Перезапусти Kitsune, чтобы применилось.",
            parse_mode="html",
        )

    @command("delproxy", required=OWNER)
    async def delproxy_cmd(self, event) -> None:
        """.delproxy — удалить MTPROTO-прокси."""
        cfg = _load_cfg()
        if "proxy" in cfg:
            cfg.pop("proxy", None)
            _save_cfg(cfg)
            await event.reply(
                "✅ MTPROTO-прокси удалён. 🔁 Перезапусти Kitsune.",
                parse_mode="html",
            )
        else:
            await event.reply("ℹ️ MTPROTO-прокси не был задан.", parse_mode="html")

    # ── SOCKS5 (aiogram / notifier-бот) ───────────────────────────────

    @command("setsocks", required=OWNER)
    async def setsocks_cmd(self, event) -> None:
        """.setsocks <host> <port> [user] [pass] — задать SOCKS5 для aiogram."""
        args = (self.get_args(event) or "").split()
        if len(args) < 2:
            await event.reply(
                "❌ Использование:\n"
                "<code>.setsocks &lt;host&gt; &lt;port&gt; [user] [pass]</code>\n\n"
                "Пример без авторизации:\n"
                "<code>.setsocks germany.tgproxy11.online 443</code>\n\n"
                "Пример с авторизацией:\n"
                "<code>.setsocks germany.tgproxy11.online 1080 myuser mypass</code>\n\n"
                "<i>Используется aiogram-ботом (notifier) для api.telegram.org. "
                "Секрет MTPROTO здесь НЕ нужен.</i>",
                parse_mode="html",
            )
            return

        host, port = args[0], args[1]
        try:
            port = int(port)
        except ValueError:
            await event.reply("❌ Порт должен быть числом.", parse_mode="html")
            return

        user = args[2] if len(args) > 2 else None
        pwd  = args[3] if len(args) > 3 else None

        cfg = _load_cfg()
        block = {
            "type": "SOCKS5",
            "host": host,
            "port": port,
        }
        if user and pwd:
            block["username"] = user
            block["password"] = pwd
        cfg["proxy_socks"] = block
        _save_cfg(cfg)

        auth_str = f"{user}:***@" if user else "(без авторизации)"
        await event.reply(
            "✅ <b>SOCKS5-прокси сохранён в config.toml:</b>\n"
            f"• host: <code>{_esc(host)}</code>\n"
            f"• port: <code>{port}</code>\n"
            f"• auth: <code>{_esc(auth_str)}</code>\n\n"
            "🔁 Перезапусти Kitsune, чтобы aiogram подхватил прокси.\n"
            "ℹ️ Если ещё не установлен — запусти:\n"
            "<code>pip install 'aiohttp-socks&gt;=0.9.0'</code>",
            parse_mode="html",
        )

    @command("delsocks", required=OWNER)
    async def delsocks_cmd(self, event) -> None:
        """.delsocks — удалить SOCKS5-прокси для aiogram."""
        cfg = _load_cfg()
        if "proxy_socks" in cfg:
            cfg.pop("proxy_socks", None)
            _save_cfg(cfg)
            await event.reply(
                "✅ SOCKS5-прокси удалён. 🔁 Перезапусти Kitsune.",
                parse_mode="html",
            )
        else:
            await event.reply("ℹ️ SOCKS5-прокси не был задан.", parse_mode="html")

    # ── Информация ────────────────────────────────────────────────────

    @command("proxyinfo", required=OWNER, aliases=["proxystatus"])
    async def proxyinfo_cmd(self, event) -> None:
        """.proxyinfo — показать оба прокси."""
        cfg = _load_cfg()
        mt = cfg.get("proxy") or {}
        sx = cfg.get("proxy_socks") or {}

        lines = ["🛰 <b>Состояние прокси</b>\n"]

        lines.append("<b>1) MTPROTO (Telethon)</b>")
        if mt.get("host"):
            lines.append(f"   • host: <code>{_esc(mt.get('host'))}</code>")
            lines.append(f"   • port: <code>{mt.get('port')}</code>")
            sec = str(mt.get("secret") or "")
            lines.append(f"   • secret: <code>{_esc(sec[:24])}…</code>" if sec else "   • secret: —")
        else:
            lines.append("   • <i>не задан</i>")

        lines.append("")
        lines.append("<b>2) SOCKS5 (aiogram / notifier)</b>")
        if sx.get("host"):
            lines.append(f"   • host: <code>{_esc(sx.get('host'))}</code>")
            lines.append(f"   • port: <code>{sx.get('port')}</code>")
            if sx.get("username"):
                lines.append(f"   • user: <code>{_esc(sx.get('username'))}</code>")
        else:
            lines.append("   • <i>не задан</i>")

        await event.reply("\n".join(lines), parse_mode="html")
