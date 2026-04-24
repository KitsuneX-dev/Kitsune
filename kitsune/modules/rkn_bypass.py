from __future__ import annotations

import asyncio
import logging

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.rkn"
_DEFAULT_CHECK_INTERVAL = 600   # 10 минут


class RKNBypassModule(KitsuneModule):

    name        = "RKNBypass"
    description = "Обход блокировок РКН (MTProto прокси)"
    author      = "@Mikasu32"
    version     = "2.0"
    _builtin    = True

    config = ModuleConfig(
        ConfigValue(
            key="check_interval",
            default=_DEFAULT_CHECK_INTERVAL,
            doc=(
                "Интервал проверки прокси в секундах. "
                "Дефолт — 600 (10 мин). Минимум — 60."
            ),
        ),
        ConfigValue(
            key="auto_switch",
            default=True,
            doc=(
                "Автоматически переключаться на другой прокси, "
                "если текущий перестал работать."
            ),
        ),
        ConfigValue(
            key="notify_on_switch",
            default=True,
            doc="Отправлять уведомление в Избранное при смене прокси.",
        ),
    )

    strings_ru = {
        # ── статус соединения ──────────────────────────────────────────────
        "checking":     "🔍 Проверяю подключение к Telegram...",
        "ok":           "✅ Прямое подключение работает нормально.",
        "blocked":      (
            "🚫 Прямое подключение к Telegram заблокировано.\n\n"
            "🔍 Ищу рабочий MTProto прокси..."
        ),
        # ── прокси найден ─────────────────────────────────────────────────
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
        # ── управление ────────────────────────────────────────────────────
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
        # ── поиск прокси ──────────────────────────────────────────────────
        "findproxy_start": (
            "🔎 Ищу рабочие MTProto прокси в сети...\n"
            "<i>Это может занять несколько секунд.</i>"
        ),
        "findproxy_testing": "🧪 Проверяю {count} прокси из веб-источников...",
        # ── мониторинг ────────────────────────────────────────────────────
        "monitor_started":  "✅ Мониторинг прокси запущен (интервал: {interval} сек).",
        "monitor_stopped":  "🛑 Мониторинг прокси остановлен.",
        "monitor_ok":       "✅ Прокси <code>{host}:{port}</code> — работает.",
        "monitor_fail":     (
            "⚠️ Прокси <code>{host}:{port}</code> недоступен!\n"
            "🔄 Автопереключение {status}."
        ),
        "auto_switched":    (
            "🔄 <b>Автопереключение прокси</b>\n\n"
            "❌ Старый: <code>{old_host}:{old_port}</code>\n"
            "✅ Новый: <code>{new_host}:{new_port}</code>\n\n"
            "<i>Перезапусти Kitsune для применения: <code>.restart</code></i>"
        ),
        "auto_switch_fail": (
            "❌ Автопереключение не удалось — рабочий прокси не найден.\n"
            "Попробуй <code>.findproxy</code> для поиска нового."
        ),
    }

    # ════════════════════════════════════════════════════════════════════════
    # Инициализация и жизненный цикл
    # ════════════════════════════════════════════════════════════════════════

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._monitor_task: asyncio.Task | None = None

    async def on_load(self) -> None:
        """Запускаем мониторинг, если он был включён ранее."""
        if self.db.get(_DB_OWNER, "monitor_enabled", False):
            self._start_monitor()

    async def on_unload(self) -> None:
        self._stop_monitor()

    # ════════════════════════════════════════════════════════════════════════
    # Вспомогательные методы
    # ════════════════════════════════════════════════════════════════════════

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

    def _current_proxy(self) -> dict | None:
        """Возвращает текущий прокси из config.toml или None."""
        cfg = self._load_config()
        proxy = cfg.get("proxy")
        if proxy and proxy.get("host"):
            return proxy
        return None

    def _get_interval(self) -> int:
        """Берёт интервал из ModuleConfig, минимум 60 секунд."""
        try:
            return max(60, int(self.config["check_interval"]))
        except Exception:
            return _DEFAULT_CHECK_INTERVAL

    # ════════════════════════════════════════════════════════════════════════
    # Мониторинг (фоновая задача)
    # ════════════════════════════════════════════════════════════════════════

    def _start_monitor(self) -> None:
        self._stop_monitor()
        self._monitor_task = asyncio.ensure_future(self._monitor_loop())
        logger.info("RKNBypass: мониторинг запущен")

    def _stop_monitor(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = None

    async def _monitor_loop(self) -> None:
        """Периодически проверяет текущий прокси и переключает при падении."""
        from ..rkn_bypass import test_connection, find_working_proxy, find_proxy_from_web

        while True:
            interval = self._get_interval()
            await asyncio.sleep(interval)

            try:
                proxy = self._current_proxy()

                if proxy is None:
                    # Прокси не настроен — проверяем прямое соединение
                    ok = await test_connection("api.telegram.org", 443, timeout=5.0)
                    if not ok:
                        logger.warning("RKNBypass [monitor]: прямое соединение недоступно")
                    continue

                host = proxy["host"]
                port = proxy["port"]
                ok = await test_connection(host, port, timeout=5.0)

                if ok:
                    logger.debug("RKNBypass [monitor]: прокси %s:%d — OK", host, port)
                    continue

                # ── прокси упал ─────────────────────────────────────────────
                logger.warning("RKNBypass [monitor]: прокси %s:%d недоступен!", host, port)

                auto_switch = bool(self.config.get("auto_switch", True)) \
                    if hasattr(self.config, "get") else True
                try:
                    auto_switch = bool(self.config["auto_switch"])
                except Exception:
                    auto_switch = True

                if not auto_switch:
                    await self._notify(
                        self.strings("monitor_fail").format(
                            host=host, port=port, status="отключено"
                        )
                    )
                    continue

                # Пробуем найти замену
                web_proxies = await find_proxy_from_web()
                new_proxy = await find_working_proxy(extra_proxies=web_proxies)

                if new_proxy:
                    new_host, new_port, new_secret = new_proxy
                    # Сохраняем новый прокси в config.toml
                    cfg = self._load_config()
                    cfg["proxy"] = {
                        "type": "MTPROTO",
                        "host": new_host,
                        "port": new_port,
                        "secret": new_secret,
                    }
                    self._save_config(cfg)
                    logger.info(
                        "RKNBypass [monitor]: переключился на %s:%d", new_host, new_port
                    )

                    try:
                        notify = bool(self.config["notify_on_switch"])
                    except Exception:
                        notify = True

                    if notify:
                        await self._notify(
                            self.strings("auto_switched").format(
                                old_host=host,
                                old_port=port,
                                new_host=new_host,
                                new_port=new_port,
                            )
                        )
                else:
                    await self._notify(self.strings("auto_switch_fail"))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("RKNBypass [monitor]: ошибка — %s", exc)

    async def _notify(self, text: str) -> None:
        """Отправляет сообщение в Избранное (Saved Messages)."""
        try:
            await self.client.send_message("me", text, parse_mode="html")
        except Exception as exc:
            logger.warning("RKNBypass: не удалось отправить уведомление — %s", exc)

    # ════════════════════════════════════════════════════════════════════════
    # Команды
    # ════════════════════════════════════════════════════════════════════════

    @command("rkn", required=OWNER)
    async def rkn_cmd(self, event) -> None:
        """Проверяет соединение и ищет прокси из встроенного списка."""
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

    @command("findproxy", required=OWNER)
    async def findproxy_cmd(self, event) -> None:
        """Активно ищет рабочие прокси в интернете (каналы + API)."""
        await event.message.edit(self.strings("findproxy_start"), parse_mode="html")

        from ..rkn_bypass import find_proxy_from_web, find_working_proxy

        web_proxies = await find_proxy_from_web()

        if not web_proxies:
            await event.message.edit(self.strings("proxy_none"), parse_mode="html")
            return

        await event.message.edit(
            self.strings("findproxy_testing").format(count=len(web_proxies)),
            parse_mode="html",
        )

        proxy = await find_working_proxy(extra_proxies=web_proxies)

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
        args = self.get_args(event).split()
        if len(args) < 3:
            await event.message.edit(self.strings("set_usage"), parse_mode="html")
            return

        host, port_s, secret = args[0], args[1], args[2]
        try:
            port = int(port_s)
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
        cfg = self._load_config()
        cfg.pop("proxy", None)
        self._save_config(cfg)
        await event.message.edit(self.strings("proxy_clear"), parse_mode="html")

    @command("proxyinfo", required=OWNER)
    async def proxyinfo_cmd(self, event) -> None:
        proxy = self._current_proxy()
        if not proxy:
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
        await event.message.edit("🔍 Проверяю...", parse_mode="html")

        from ..rkn_bypass import test_connection
        results = []
        for host in ["api.telegram.org", "149.154.167.51", "149.154.175.100"]:
            ok = await test_connection(host, 443, timeout=3.0)
            icon = "✅" if ok else "❌"
            results.append(f"{icon} <code>{host}:443</code>")

        proxy = self._current_proxy()
        if proxy:
            ph, pp = proxy.get("host", ""), proxy.get("port", 443)
            ok = await test_connection(ph, pp, timeout=3.0)
            icon = "✅" if ok else "❌"
            results.append(f"{icon} <code>{ph}:{pp}</code> <i>(текущий прокси)</i>")

        await event.message.edit(
            "🌐 <b>Проверка соединения:</b>\n\n" + "\n".join(results),
            parse_mode="html",
        )

    @command("proxymon", required=OWNER)
    async def proxymon_cmd(self, event) -> None:
        """
        .proxymon on  — запустить мониторинг
        .proxymon off — остановить мониторинг
        """
        arg = self.get_args(event).strip().lower()

        if arg == "off":
            self._stop_monitor()
            await self.db.set(_DB_OWNER, "monitor_enabled", False)
            await event.message.edit(self.strings("monitor_stopped"), parse_mode="html")
            return

        self._start_monitor()
        await self.db.set(_DB_OWNER, "monitor_enabled", True)
        interval = self._get_interval()
        await event.message.edit(
            self.strings("monitor_started").format(interval=interval),
            parse_mode="html",
        )
