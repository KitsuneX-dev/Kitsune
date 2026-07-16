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
    name        = "ProxyCtl"
    description = "Управление MTPROTO/SOCKS5 прокси (Telethon + aiogram)"
    author      = "Kitsune Team"
    version     = "1.3.0"
    icon        = "🛰"
    category    = "system"
    @command("setproxy", required=OWNER)
    async def setproxy_cmd(self, event) -> None:
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
    @command("setsocks", required=OWNER)
    async def setsocks_cmd(self, event) -> None:
        args = (self.get_args(event) or "").split()
        if len(args) < 2:
            await event.reply(
                "❌ Использование:\n"
                "<code>.setsocks &lt;host&gt; &lt;port&gt; [user] [pass]</code>\n\n"
                "Пример без авторизации (типичный порт SOCKS5 — 1080):\n"
                "<code>.setsocks germany.tgproxy11.online 1080</code>\n\n"
                "Пример с авторизацией:\n"
                "<code>.setsocks germany.tgproxy11.online 1080 myuser mypass</code>\n\n"
                "<i>Используется aiogram-ботом (notifier + inline) для api.telegram.org. "
                "Секрет MTPROTO здесь НЕ нужен — это обычный SOCKS5.</i>\n\n"
                "🔎 Проверить после настройки: <code>.testsocks</code>",
                parse_mode="html",
            )
            return
        host, port = args[0], args[1]
        try:
            port = int(port)
            if not (0 < port < 65536):
                raise ValueError
        except ValueError:
            await event.reply(
                "❌ Порт должен быть числом 1–65535. "
                "Для SOCKS5 типично <code>1080</code>.",
                parse_mode="html",
            )
            return
        if port not in (1080, 1081, 1082, 1085, 9050, 9150) and (port >= 10000 or port == 443):
            logger.warning(
                "ProxyCtl: подозрительный порт SOCKS5 (%d) — возможно это MTPROTO",
                port,
            )
        user = args[2] if len(args) > 2 else None
        pwd  = args[3] if len(args) > 3 else None
        if (user and not pwd) or (pwd and not user):
            await event.reply(
                "⚠️ Для SOCKS5 авторизации нужны <b>ОБА</b> аргумента — user и pass.\n"
                "Если прокси без авторизации — не указывай ни одного.",
                parse_mode="html",
            )
            return
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
        warn = ""
        if port not in (1080, 1081, 1082, 1085, 9050, 9150) and (port >= 10000 or port == 443):
            warn = (
                "\n⚠️ <b>Внимание:</b> порт <code>{p}</code> нетипичен для SOCKS5 "
                "(обычно <code>1080</code>). Если это MTPROTO-порт — используй "
                "<code>.setproxy</code>, а не <code>.setsocks</code>.\n"
            ).format(p=port)
        await event.reply(
            "✅ <b>SOCKS5-прокси сохранён в config.toml:</b>\n"
            f"• host: <code>{_esc(host)}</code>\n"
            f"• port: <code>{port}</code>\n"
            f"• auth: <code>{_esc(auth_str)}</code>\n"
            f"{warn}\n"
            "🔎 Проверь сейчас: <code>.testsocks</code>\n"
            "🔁 После этого перезапусти Kitsune, чтобы aiogram подхватил прокси.\n"
            "ℹ️ Если ещё не установлен — запусти:\n"
            "<code>pip install 'aiohttp-socks&gt;=0.9.0'</code>",
            parse_mode="html",
        )
    @command("delsocks", required=OWNER)
    async def delsocks_cmd(self, event) -> None:
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
    @command("testsocks", required=OWNER)
    async def testsocks_cmd(self, event) -> None:
        m = await event.reply("⏳ Проверяю SOCKS5 → api.telegram.org…", parse_mode="html")
        try:
            from ..rkn_bypass import ensure_aiohttp_socks
            if not ensure_aiohttp_socks():
                await m.edit(
                    "❌ <b>aiohttp-socks не установлен</b>\n\n"
                    "Установи вручную:\n"
                    "<code>pip install 'aiohttp-socks&gt;=0.9.0'</code>\n\n"
                    "Без него aiogram не умеет ходить через SOCKS5.",
                    parse_mode="html",
                )
                return
        except Exception:
            pass
        try:
            from ..rkn_bypass import test_socks_proxy
            ok, msg = await test_socks_proxy(timeout=15.0)
        except Exception as exc:
            await m.edit(f"❌ Ошибка проверки: <code>{_esc(exc)}</code>", parse_mode="html")
            return
        if ok:
            await m.edit(
                "✅ <b>SOCKS5 работает</b>\n"
                f"<code>{_esc(msg)}</code>\n\n"
                "aiogram-бот (notifier + inline) пойдёт через этот прокси.",
                parse_mode="html",
            )
            return
        hint = ""
        msg_l = (msg or "").lower()
        if "timeout" in msg_l:
            hint = (
                "\n\n💡 <b>Подсказка:</b> SOCKS5 не отвечает за 15с.\n"
                "• Проверь, что порт правильный — <b>обычно 1080</b>.\n"
                "• Если порт типа <code>10001</code>/<code>443</code> — это, скорее всего, "
                "<b>MTPROTO</b>-порт, его нужно ставить через <code>.setproxy</code>, "
                "а не <code>.setsocks</code>.\n"
                "• Попробуй другой прокси командой <code>.setsocks</code>."
            )
        elif "could not connect to proxy" in msg_l or "refused" in msg_l:
            hint = (
                "\n\n💡 <b>Подсказка:</b> прокси не принимает входящие подключения.\n"
                "• Возможно, у домена устаревшая DNS-запись — попробуй IP вместо домена.\n"
                "• Возможно, прокси умер — возьми другой."
            )
        elif "auth" in msg_l or "method" in msg_l:
            hint = (
                "\n\n💡 <b>Подсказка:</b> прокси требует авторизацию или версию SOCKS4.\n"
                "Попробуй: <code>.setsocks host port user pass</code>"
            )
        await m.edit(
            "❌ <b>SOCKS5 НЕ работает</b>\n"
            f"<code>{_esc(msg)}</code>"
            f"{hint}\n\n"
            "Проверь host/port командой <code>.proxyinfo</code> "
            "и переставь через <code>.setsocks</code>.",
            parse_mode="html",
        )
    @command("proxyinfo", required=OWNER, aliases=["proxystatus"])
    async def proxyinfo_cmd(self, event) -> None:
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
            port_v = sx.get("port")
            lines.append(f"   • port: <code>{port_v}</code>")
            if sx.get("username"):
                lines.append(f"   • user: <code>{_esc(sx.get('username'))}</code>")
            try:
                p = int(port_v)
                if p not in (1080, 1081, 1082, 1085, 9050, 9150) and (p >= 10000 or p == 443):
                    lines.append(
                        "   • ⚠️ <i>порт нетипичен для SOCKS5 — "
                        "возможно, это MTPROTO-порт</i>"
                    )
            except (TypeError, ValueError):
                pass
        else:
            lines.append("   • <i>не задан</i>")
        lines.append("")
        try:
            import aiohttp_socks              
            lines.append("<b>3) Зависимости</b>")
            lines.append("   • aiohttp-socks: <code>OK</code>")
        except ImportError:
            lines.append("<b>3) Зависимости</b>")
            lines.append(
                "   • aiohttp-socks: <code>НЕ установлен</code> — "
                "<i>установи: <code>pip install 'aiohttp-socks&gt;=0.9.0'</code></i>"
            )
        await event.reply("\n".join(lines), parse_mode="html")
