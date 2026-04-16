from __future__ import annotations

import asyncio
import time

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

_DB_OWNER = "kitsune.health"
_DEFAULT_INTERVAL  = 5 * 60
_DEFAULT_RAM_LIMIT = 85
_DEFAULT_CPU_LIMIT = 90

class HealthModule(KitsuneModule):
    name        = "health"
    description = "Мониторинг ресурсов системы"
    author      = "Yushi"

    strings_ru = {
        "status": (
            "💻 <b>Состояние системы</b>\n\n"
            "🧠 RAM: <code>{ram_used} / {ram_total} МБ</code> ({ram_pct:.1f}%)\n"
            "⚙️ CPU: <code>{cpu:.1f}%</code>\n"
            "💾 Диск: <code>{disk_used} / {disk_total} ГБ</code> ({disk_pct:.1f}%)\n"
            "⏱ Uptime: <code>{uptime}</code>\n"
        ),
        "alert_ram": "⚠️ <b>RAM Alert:</b> использование {pct:.1f}% (порог {limit}%)",
        "alert_cpu": "⚠️ <b>CPU Alert:</b> использование {pct:.1f}% (порог {limit}%)",
        "monitor_on":  "✅ Мониторинг запущен (интервал {interval} мин.)",
        "monitor_off": "🛑 Мониторинг остановлен",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._monitor_task: asyncio.Task | None = None
        self._start_time = time.time()

    async def on_load(self) -> None:
        if self.db.get(_DB_OWNER, "monitor_enabled", False):
            self._start_monitor()

    async def on_unload(self) -> None:
        self._stop_monitor()

    @command("health", required=OWNER)
    async def health_cmd(self, event) -> None:
        await event.reply(self._build_status(), parse_mode="html")

    @command("monitor", required=OWNER)
    async def monitor_cmd(self, event) -> None:
        parts = event.message.text.split()
        action = parts[1].lower() if len(parts) > 1 else "on"

        if action == "off":
            self._stop_monitor()
            await self.db.set(_DB_OWNER, "monitor_enabled", False)
            await event.reply(self.strings("monitor_off"), parse_mode="html")
            return

        interval_min = int(parts[2]) if len(parts) > 2 else 5
        interval_sec = max(60, interval_min * 60)
        await self.db.set(_DB_OWNER, "monitor_interval", interval_sec)
        await self.db.set(_DB_OWNER, "monitor_enabled", True)
        self._start_monitor(interval_sec)
        await event.reply(
            self.strings("monitor_on").format(interval=interval_min),
            parse_mode="html",
        )

    def _build_status(self) -> str:
        try:
            mem = psutil.virtual_memory()
            ram_used  = mem.used  // 1024 // 1024
            ram_total = mem.total // 1024 // 1024
            ram_pct   = mem.percent
        except Exception:
            ram_used = ram_total = 0
            ram_pct = 0.0

        try:
            cpu = psutil.cpu_percent(interval=0.3)
        except Exception:
            cpu = 0.0

        try:
            disk = psutil.disk_usage("/") if _PSUTIL else None
            disk_used  = disk.used  // 1024 // 1024 // 1024
            disk_total = disk.total // 1024 // 1024 // 1024
            disk_pct   = disk.percent
        except Exception:
            disk_used = disk_total = 0
            disk_pct = 0.0

        uptime_sec = int(time.time() - self._start_time)
        h, rem = divmod(uptime_sec, 3600)
        m, s   = divmod(rem, 60)

        return self.strings("status").format(
            ram_used=ram_used,
            ram_total=ram_total,
            ram_pct=ram_pct,
            cpu=cpu,
            disk_used=disk_used,
            disk_total=disk_total,
            disk_pct=disk_pct,
            uptime=f"{h:02d}:{m:02d}:{s:02d}",
        )

    def _start_monitor(self, interval: int | None = None) -> None:
        self._stop_monitor()
        if interval is None:
            interval = self.db.get(_DB_OWNER, "monitor_interval", _DEFAULT_INTERVAL)
        self._monitor_task = asyncio.ensure_future(self._monitor_loop(interval))

    def _stop_monitor(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = None

    async def _monitor_loop(self, interval: int) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self._check_thresholds()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _check_thresholds(self) -> None:
        ram_limit = self.db.get(_DB_OWNER, "ram_limit", _DEFAULT_RAM_LIMIT)
        cpu_limit = self.db.get(_DB_OWNER, "cpu_limit", _DEFAULT_CPU_LIMIT)

        try:
            if not _PSUTIL:
                return
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=1)
        except Exception:
            return

        logchat = self.db.get("kitsune.core", "logchat", None)
        if not logchat:
            return

        if mem.percent >= ram_limit:
            await self.client.send_message(
                logchat,
                self.strings("alert_ram").format(pct=mem.percent, limit=ram_limit),
                parse_mode="html",
            )

        if cpu >= cpu_limit:
            await self.client.send_message(
                logchat,
                self.strings("alert_cpu").format(pct=cpu, limit=cpu_limit),
                parse_mode="html",
            )
