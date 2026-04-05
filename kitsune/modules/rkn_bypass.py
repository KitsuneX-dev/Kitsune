from __future__ import annotations

import asyncio
import logging

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.rkn"


class RKNBypassModule(KitsuneModule):
    """Обход блокировок РКН для Telegram без VPN."""

    name        = "RKNBypass"
    description = "Обход блокировок РКН (MTProto прокси)"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    strings_ru = {
        "checking":     "🔍 Проверяю подключение к Telegram...",
        "ok":           "✅ Прямое подключение работает нормально.",
        "blocked":      (
            "🚫 Прямое подключение к Telegram заблокировано.\n\n"
            "🔍 Ищу рабочий MTProto прокси..."
        ),
        "proxy_found":  (
            "✅ Найден рабочий прокси!\n\n"
            "🌐 <code>{host}:{port}</code>\n\n"
            "Добавь в <code>config.toml</code>:\n"
            "<pre>[proxy]\n"
            "type = \"MTPROTO\"\n"
            "host = \"{host}\"\n"
            "port = {port}\n"
            "secret = \"{secret}\"</pre>\n\n"
            "Или используй <code>.setproxy {host} {port} {secret}</code>"
        ),
        "proxy_none":   (
            "❌ Рабочий MTProto прокси не найден.\n\n"
            "Попробуй вручную найти прокси в <a href=\"https://t.me/proxyme\">@proxyme</a> "
            "или <a href=\"https://t.me/MTProxyT\">@MTProxyT</a>\n\n"
            "Затем: <code>.setproxy host port secret</code>"
        ),
        "proxy_set":    (
            "✅ Прокси сохранён в <code>config.toml</code>.\n"
            "Перезапусти Kitsune: <code>.restart</code>"
        ),
        "proxy_clear":  "✅ Прокси удалён. Перезапусти: <code>.restart</code>",
        "current":      (
            "🌐 <b>Текущий прокси:</b>\n\n"
            "Тип: <code>{type}</code>\n"
            "Хост: <code>{host}:{port}</code>\n"
            "Секрет: <code>{secret}</code>"
        ),
        "no_proxy":     "ℹ️ Прокси не настроен — используется прямое подключение.",
        "set_usage":    "Использование: <code>.setproxy host port secret</code>",
        "ssl_enabled":  "✅ Обход SSL РКН-фильтрации для Bot API — <b>уже включён по умолчанию</b>.",
    }

    # ─── helpers ──────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        from pathlib import Path
        try:
            import toml
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            if cfg_path.exists():
                return toml.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_config(self, data: dict) -> None:
        from pathlib import Path
        try:
            import toml
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            cfg_path.write_text(toml.dumps(data), encoding="utf-8")
        except Exception as exc:
            logger.warning("RKNBypass: could not save config — %s", exc)

    # ─── команды ──────────────────────────────────────────────────────────

    @command("rkn", required=OWNER)
    async def rkn_cmd(self, event) -> None:
        """.rkn — проверить подключение и найти обходной прокси если нужно."""
        await event.message.edit(self.strings("checking"), parse_mode="html")

        from ..rkn_bypass import test_connection, find_working_proxy
        direct_ok = await test_connection("api.telegram.org", 443, timeout=5.0)

        if direct_ok:
            await event.message.edit(self.strings("ok"), parse_mode="html")
            return

        await event.message.edit(self.strings("blocked"), parse_mode="html")
        await asyncio.sleep(1)

        proxy = await find_working_proxy()
        if not proxy:
            await event.message.edit(self.strings("proxy_none"), parse_mode="html")
            return

        host, port, secret = proxy
        await event.message.edit(
            self.strings("proxy_found").format(host=host, port=port, secret=secret),
            parse_mode="html",
            link_preview=False,
        )

    @command("setproxy", required=OWNER)
    async def setproxy_cmd(self, event) -> None:
        """.setproxy host port secret — установить MTProto прокси."""
        args = self.get_args(event).split()
        if len(args) < 3:
            await event.message.edit(self.strings("set_usage"), parse_mode="html")
            return

        host, port, secret = args[0], args[1], args[2]
        try:
            port = int(port)
        except ValueError:
            await event.message.edit("❌ Port должен быть числом.", parse_mode="html")
            return

        cfg = self._load_config()
        cfg["proxy"] = {
            "type": "MTPROTO",
            "host": host,
            "port": port,
            "secret": secret,
        }
        self._save_config(cfg)
        await event.message.edit(self.strings("proxy_set"), parse_mode="html")

    @command("clearproxy", required=OWNER)
    async def clearproxy_cmd(self, event) -> None:
        """.clearproxy — убрать прокси (прямое подключение)."""
        cfg = self._load_config()
        cfg.pop("proxy", None)
        self._save_config(cfg)
        await event.message.edit(self.strings("proxy_clear"), parse_mode="html")

    @command("proxyinfo", required=OWNER)
    async def proxyinfo_cmd(self, event) -> None:
        """.proxyinfo — показать текущий прокси."""
        cfg = self._load_config()
        proxy = cfg.get("proxy")
        if not proxy or not proxy.get("host"):
            await event.message.edit(self.strings("no_proxy"), parse_mode="html")
            return

        await event.message.edit(
            self.strings("current").format(
                type=proxy.get("type", "MTPROTO"),
                host=proxy.get("host", "?"),
                port=proxy.get("port", "?"),
                secret=proxy.get("secret", "?"),
            ),
            parse_mode="html",
        )

    @command("checkcon", required=OWNER)
    async def checkcon_cmd(self, event) -> None:
        """.checkcon — проверить прямое соединение с Telegram."""
        await event.message.edit("🔍 Проверяю...", parse_mode="html")

        from ..rkn_bypass import test_connection
        results = []
        for host in ["api.telegram.org", "149.154.167.51", "149.154.175.100"]:
            ok = await test_connection(host, 443, timeout=3.0)
            icon = "✅" if ok else "❌"
            results.append(f"{icon} <code>{host}:443</code>")

        await event.message.edit(
            "🌐 <b>Проверка соединения:</b>\n\n" + "\n".join(results),
            parse_mode="html",
        )
