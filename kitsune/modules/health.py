"""
Kitsune — Health module (Phase 3).

Команды:
    .health         — расширенный health-check всех подсистем:
                      SQLite alive? Redis alive? Telegram session active?
                      uptime, RAM, CPU, disk, circuit breakers, degradation.
    .monitor on|off [N] — фоновый мониторинг RAM/CPU с алертами в logchat.
    .breakers       — состояние всех CircuitBreaker'ов.
    .resetbreaker <name> — ручной сброс breaker'а в CLOSED.

Этот же модуль предоставляет helper'ы, используемые web/core.py для
публикации /health JSON endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import time
import typing

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..core.reliability import flags as _degradation_flags, global_registry as _cb_registry

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.health"

_DEFAULT_INTERVAL  = 5 * 60
_DEFAULT_RAM_LIMIT = 85
_DEFAULT_CPU_LIMIT = 90


# ---------------------------------------------------------------------------
# Health-probes — переиспользуются и веб-эндпоинтом
# ---------------------------------------------------------------------------

async def probe_sqlite(db: typing.Any) -> dict:
    """Проверить доступность SQLite-бэкенда.

    Делает SELECT 1 в executor — если бэкенд жив, отвечает мгновенно.
    Возвращает dict со статусом и временем отклика.
    """
    try:
        from ..database.manager import SQLiteBackend
    except Exception:
        return {"alive": False, "error": "SQLiteBackend import failed"}

    backend = getattr(db, "_backend", None)
    if backend is None:
        return {"alive": False, "error": "no backend"}
    if not isinstance(backend, SQLiteBackend):
        # SQLite используется как fallback — если активен Redis, возвращаем
        # «n/a» но без ошибки.
        return {"alive": False, "error": "not active (redis primary)", "active": False}

    t0 = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        def _ping() -> int:
            conn = backend._get_conn()  # idempotent, переиспользуется
            cur = conn.execute("SELECT 1")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _ping), timeout=5.0,
        )
        latency_ms = (time.monotonic() - t0) * 1000.0
        return {
            "alive": result == 1,
            "active": True,
            "latency_ms": round(latency_ms, 2),
        }
    except asyncio.TimeoutError:
        return {"alive": False, "active": True, "error": "timeout (>5s)"}
    except Exception as exc:
        return {"alive": False, "active": True, "error": f"{type(exc).__name__}: {exc}"}


async def probe_redis(db: typing.Any) -> dict:
    """Проверить доступность Redis-бэкенда.

    Если Redis не сконфигурирован — возвращаем active=False (это не ошибка).
    Если сконфигурирован, делаем PING.
    """
    try:
        from ..database.manager import RedisBackend
    except Exception:
        return {"alive": False, "configured": False}

    backend = getattr(db, "_backend", None)
    configured = isinstance(backend, RedisBackend)
    if not configured:
        return {"alive": False, "configured": False, "active": False}

    redis_client = getattr(backend, "_redis", None)
    if redis_client is None:
        return {"alive": False, "configured": True, "error": "no redis client"}

    t0 = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, redis_client.ping),
            timeout=5.0,
        )
        latency_ms = (time.monotonic() - t0) * 1000.0
        return {
            "alive": bool(result),
            "active": True,
            "configured": True,
            "latency_ms": round(latency_ms, 2),
        }
    except asyncio.TimeoutError:
        # отметим деградацию — потребители могут заметить и переключиться
        _degradation_flags.mark_redis_unavailable("PING timeout >5s")
        return {"alive": False, "active": True, "configured": True, "error": "timeout (>5s)"}
    except Exception as exc:
        _degradation_flags.mark_redis_unavailable(f"{type(exc).__name__}: {exc}")
        return {
            "alive": False,
            "active": True,
            "configured": True,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def probe_telegram(client: typing.Any) -> dict:
    """Проверить активность Telegram-сессии.

    Делаем GetState (быстрый низкоуровневый запрос) под защитой breaker'а
    «telegram_api», чтобы не нагружать Telegram при отвале.
    """
    if client is None:
        return {"alive": False, "error": "no client"}

    # Быстрая проверка connected без RPC
    try:
        connected = bool(client.is_connected())
    except Exception as exc:
        return {"alive": False, "error": f"is_connected: {exc}"}

    if not connected:
        return {"alive": False, "connected": False}

    # Если у клиента нет sender — линк ещё не поднят
    sender = getattr(client, "_sender", None)
    if sender is None:
        return {"alive": False, "connected": True, "error": "no sender"}

    t0 = time.monotonic()
    try:
        # Используем GetStateRequest как «ping» — он лёгкий
        from telethon.tl.functions.updates import GetStateRequest
        # Защищаем circuit breaker'ом
        from ..core.reliability import get_breaker, CircuitBreakerOpenError
        cb = get_breaker("telegram_api", failure_threshold=5, cooldown=60.0)

        async def _do() -> typing.Any:
            return await asyncio.wait_for(client(GetStateRequest()), timeout=10.0)

        try:
            await cb.call(_do)
        except CircuitBreakerOpenError:
            return {
                "alive": False,
                "connected": True,
                "error": "circuit breaker OPEN — paused",
                "breaker_state": cb.state,
            }

        latency_ms = (time.monotonic() - t0) * 1000.0
        # Авторизация
        authorized = False
        try:
            authorized = await client.is_user_authorized()
        except Exception:
            pass
        return {
            "alive": True,
            "connected": True,
            "authorized": authorized,
            "tg_id": getattr(client, "tg_id", 0),
            "latency_ms": round(latency_ms, 2),
        }
    except asyncio.TimeoutError:
        return {"alive": False, "connected": True, "error": "GetState timeout (>10s)"}
    except Exception as exc:
        return {
            "alive": False,
            "connected": True,
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_system() -> dict:
    """Снять снимок системных ресурсов (RAM/CPU/disk/uptime процесса)."""
    out: dict = {
        "psutil": _PSUTIL,
        "cpu_pct": 0.0,
        "ram_used_mb": 0,
        "ram_total_mb": 0,
        "ram_pct": 0.0,
        "disk_used_gb": 0.0,
        "disk_total_gb": 0.0,
        "disk_pct": 0.0,
        "process_rss_mb": 0,
    }
    if not _PSUTIL:
        return out
    try:
        mem = psutil.virtual_memory()
        out["ram_used_mb"] = int(mem.used // 1024 // 1024)
        out["ram_total_mb"] = int(mem.total // 1024 // 1024)
        out["ram_pct"] = round(float(mem.percent), 1)
    except Exception:
        pass
    try:
        # interval=0 — мгновенно (не блокирующий замер)
        out["cpu_pct"] = round(float(psutil.cpu_percent(interval=0.0)), 1)
    except Exception:
        pass
    try:
        disk = psutil.disk_usage("/")
        out["disk_used_gb"] = round(disk.used / 1024 ** 3, 2)
        out["disk_total_gb"] = round(disk.total / 1024 ** 3, 2)
        out["disk_pct"] = round(float(disk.percent), 1)
    except Exception:
        pass
    try:
        proc = psutil.Process()
        out["process_rss_mb"] = int(proc.memory_info().rss // 1024 // 1024)
    except Exception:
        pass
    return out


async def collect_health(client: typing.Any, db: typing.Any) -> dict:
    """Собрать полный health-snapshot. Используется и .health командой,
    и /health endpoint'ом."""
    # Системные ресурсы — синхронны и быстры
    system = collect_system()

    # Параллельно опросим все три бэкенда
    sqlite_t = asyncio.ensure_future(probe_sqlite(db))
    redis_t = asyncio.ensure_future(probe_redis(db))
    tg_t = asyncio.ensure_future(probe_telegram(client))
    results = await asyncio.gather(sqlite_t, redis_t, tg_t, return_exceptions=True)

    sqlite_r, redis_r, tg_r = (
        r if isinstance(r, dict) else {"alive": False, "error": str(r)}
        for r in results
    )

    # Hydrogram graceful-degradation статус
    try:
        from ..hydro_media import hydro_status as _hydro_status
        hydro_info = _hydro_status()
        hydro_info["present"] = bool(getattr(client, "hydrogram", None))
    except Exception:
        hydro_info = {"present": bool(getattr(client, "hydrogram", None))}

    # Uptime процесса
    start_time = None
    try:
        start_time = db.get("kitsune.ping", "start_time", None)
    except Exception:
        pass
    if start_time is None:
        try:
            import psutil as _ps  # noqa: F401
            start_time = psutil.Process().create_time() if _PSUTIL else time.time()
        except Exception:
            start_time = time.time()
    uptime_s = max(0, int(time.time() - float(start_time)))

    # Общий статус: ok если SQLite жив И (Redis не настроен ИЛИ Redis жив) И TG живой.
    redis_ok = (not redis_r.get("configured", False)) or redis_r.get("alive", False)
    overall_ok = bool(
        sqlite_r.get("alive", False) or sqlite_r.get("active", True) is False
    ) and redis_ok and tg_r.get("alive", False)

    return {
        "ok": bool(overall_ok),
        "uptime_s": uptime_s,
        "system": system,
        "sqlite": sqlite_r,
        "redis": redis_r,
        "telegram": tg_r,
        "hydrogram": hydro_info,
        "circuit_breakers": _cb_registry.to_list(),
        "degradation": _degradation_flags.to_dict(),
        "timestamp": int(time.time()),
    }


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

def _fmt_uptime(sec: int) -> str:
    sec = int(sec)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if d: parts.append(f"{d}д")
    if h: parts.append(f"{h:02d}ч")
    parts.append(f"{m:02d}м")
    parts.append(f"{s:02d}с")
    return " ".join(parts)


def _emoji_bool(ok: bool) -> str:
    return "✅" if ok else "❌"


def render_health_text(snapshot: dict) -> str:
    sys_ = snapshot["system"]
    sq   = snapshot["sqlite"]
    rd   = snapshot["redis"]
    tg   = snapshot["telegram"]
    deg  = snapshot["degradation"]
    cbs  = snapshot["circuit_breakers"]

    lines: list[str] = []
    lines.append(
        f"{'🟢' if snapshot['ok'] else '🔴'} <b>Kitsune Health</b>"
    )
    lines.append(f"⏱ Uptime: <code>{_fmt_uptime(snapshot['uptime_s'])}</code>")
    lines.append("")

    # Storage
    lines.append("<b>📦 Хранилище</b>")
    if sq.get("active", True):
        lat = sq.get("latency_ms")
        info = f" ({lat:.1f} мс)" if lat is not None and sq.get("alive") else ""
        err  = f" — {sq.get('error', '')}" if not sq.get("alive") else ""
        lines.append(f"  {_emoji_bool(sq.get('alive', False))} SQLite{info}{err}")
    else:
        lines.append("  ⚪ SQLite (неактивен — primary Redis)")
    if rd.get("configured", False):
        lat = rd.get("latency_ms")
        info = f" ({lat:.1f} мс)" if lat is not None and rd.get("alive") else ""
        err  = f" — {rd.get('error', '')}" if not rd.get("alive") else ""
        lines.append(f"  {_emoji_bool(rd.get('alive', False))} Redis{info}{err}")
    else:
        lines.append("  ⚪ Redis (не настроен)")

    # Telegram
    lines.append("")
    lines.append("<b>📡 Telegram</b>")
    lat = tg.get("latency_ms")
    info_parts: list[str] = []
    if lat is not None and tg.get("alive"):
        info_parts.append(f"{lat:.1f} мс")
    if tg.get("authorized") is True:
        info_parts.append("auth=ok")
    elif tg.get("authorized") is False:
        info_parts.append("auth=NO")
    info = f" ({', '.join(info_parts)})" if info_parts else ""
    err = f" — {tg.get('error', '')}" if not tg.get("alive") else ""
    lines.append(f"  {_emoji_bool(tg.get('alive', False))} Session{info}{err}")
    if tg.get("tg_id"):
        lines.append(f"  🆔 ID: <code>{tg['tg_id']}</code>")

    # Resources
    lines.append("")
    lines.append("<b>🖥 Ресурсы</b>")
    lines.append(f"  🧠 RAM: <code>{sys_['ram_used_mb']} / {sys_['ram_total_mb']} МБ</code> ({sys_['ram_pct']:.1f}%)")
    lines.append(f"  ⚙️ CPU: <code>{sys_['cpu_pct']:.1f}%</code>")
    lines.append(f"  💾 Disk: <code>{sys_['disk_used_gb']:.1f} / {sys_['disk_total_gb']:.1f} ГБ</code> ({sys_['disk_pct']:.1f}%)")
    if sys_.get("process_rss_mb"):
        lines.append(f"  📊 Process RSS: <code>{sys_['process_rss_mb']} МБ</code>")

    # Circuit breakers
    if cbs:
        lines.append("")
        lines.append("<b>🛡 Circuit Breakers</b>")
        for cb in cbs:
            ico = {"closed": "🟢", "half_open": "🟡", "open": "🔴"}.get(cb["state"], "⚪")
            tail = ""
            if cb["state"] == "open":
                tail = f" — пауза ещё <code>{cb['open_remaining_s']:.0f}с</code>"
            lines.append(
                f"  {ico} <code>{cb['name']}</code> [{cb['state']}] "
                f"fails={cb['consecutive_failures']}/{cb['failure_threshold']}{tail}"
            )

    # Degradation
    if deg.get("hydrogram_failed") or deg.get("assets_unavailable") \
            or deg.get("redis_unavailable") or deg.get("vpn_down"):
        lines.append("")
        lines.append("<b>⚠️ Деградация</b>")
        reasons = deg.get("reasons", {}) or {}
        if deg.get("hydrogram_failed"):
            lines.append(f"  • Hydrogram off → Telethon-only ({reasons.get('hydrogram', '—')})")
        if deg.get("assets_unavailable"):
            lines.append(f"  • Assets channel недоступен ({reasons.get('assets', '—')})")
        if deg.get("redis_unavailable"):
            lines.append(f"  • Redis off → SQLite fallback ({reasons.get('redis', '—')})")
        if deg.get("vpn_down"):
            lines.append(f"  • VPN/proxy down ({reasons.get('vpn', '—')})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class HealthModule(KitsuneModule):

    name        = "health"
    description = "Расширенный мониторинг и health-check всех подсистем"
    author      = "Yushi"
    version     = "3.0"
    icon        = "💗"
    category    = "system"

    strings_ru = {
        "alert_ram":   "⚠️ <b>RAM Alert:</b> использование {pct:.1f}% (порог {limit}%)",
        "alert_cpu":   "⚠️ <b>CPU Alert:</b> использование {pct:.1f}% (порог {limit}%)",
        "monitor_on":  "✅ Мониторинг запущен (интервал {interval} мин.)",
        "monitor_off": "🛑 Мониторинг остановлен",
        "no_breaker":  "❌ Circuit breaker <code>{name}</code> не найден",
        "breaker_reset": "✅ Circuit breaker <code>{name}</code> сброшен в CLOSED",
        "breakers_empty": "ℹ️ Зарегистрированных circuit breaker'ов нет",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._monitor_task: asyncio.Task | None = None
        self._start_time: float = time.time()

    async def on_load(self) -> None:
        # Сохраняем стартовое время в БД (если ping модуль ещё не успел)
        try:
            if not self.db.get("kitsune.ping", "start_time", None):
                await self.db.set("kitsune.ping", "start_time", self._start_time)
        except Exception:
            pass
        if self.db.get(_DB_OWNER, "monitor_enabled", False):
            self._start_monitor()

    async def on_unload(self) -> None:
        self._stop_monitor()

    # -------- .health -------------------------------------------------------

    @command("health", required=OWNER)
    async def health_cmd(self, event) -> None:
        msg = await event.reply("⏳ <i>Проверяю подсистемы...</i>", parse_mode="html")
        snapshot = await collect_health(self.client, self.db)
        try:
            await msg.edit(render_health_text(snapshot), parse_mode="html")
        except Exception:
            # Если edit упал (например, message_not_modified) — игнорируем
            await event.reply(render_health_text(snapshot), parse_mode="html")

    # -------- .monitor on/off ----------------------------------------------

    @command("monitor", required=OWNER)
    async def monitor_cmd(self, event) -> None:
        parts = (event.message.text or "").split()
        action = parts[1].lower() if len(parts) > 1 else "on"
        if action == "off":
            self._stop_monitor()
            await self.db.set(_DB_OWNER, "monitor_enabled", False)
            await event.reply(self.strings("monitor_off"), parse_mode="html")
            return
        try:
            interval_min = int(parts[2]) if len(parts) > 2 else 5
        except ValueError:
            interval_min = 5
        interval_sec = max(60, interval_min * 60)
        await self.db.set(_DB_OWNER, "monitor_interval", interval_sec)
        await self.db.set(_DB_OWNER, "monitor_enabled", True)
        self._start_monitor(interval_sec)
        await event.reply(
            self.strings("monitor_on", interval=interval_min),
            parse_mode="html",
        )

    # -------- .breakers ----------------------------------------------------

    @command("breakers", required=OWNER)
    async def breakers_cmd(self, event) -> None:
        items = _cb_registry.to_list()
        if not items:
            await event.reply(self.strings("breakers_empty"), parse_mode="html")
            return
        lines = ["<b>🛡 Circuit Breakers</b>", ""]
        for cb in items:
            ico = {"closed": "🟢", "half_open": "🟡", "open": "🔴"}.get(cb["state"], "⚪")
            lines.append(
                f"{ico} <b>{cb['name']}</b> — <code>{cb['state']}</code>\n"
                f"  • fails: <code>{cb['consecutive_failures']}/{cb['failure_threshold']}</code>"
                f" (всего {cb['failures']})\n"
                f"  • blocked: <code>{cb['blocked_calls']}</code>"
                f" / total: <code>{cb['total_calls']}</code>"
            )
            if cb["state"] == "open":
                lines.append(
                    f"  • cooldown remaining: <code>{cb['open_remaining_s']:.0f}с</code>"
                )
            lines.append("")
        await event.reply("\n".join(lines).rstrip(), parse_mode="html")

    # -------- .resetbreaker <name> -----------------------------------------

    @command("resetbreaker", required=OWNER)
    async def resetbreaker_cmd(self, event) -> None:
        parts = (event.message.text or "").split()
        if len(parts) < 2:
            await event.reply(
                "ℹ️ Использование: <code>.resetbreaker &lt;name&gt;</code>",
                parse_mode="html",
            )
            return
        name = parts[1]
        cb = _cb_registry.get(name)
        if cb is None:
            await event.reply(self.strings("no_breaker", name=name), parse_mode="html")
            return
        cb.reset()
        await event.reply(self.strings("breaker_reset", name=name), parse_mode="html")

    # -------- monitoring loop ----------------------------------------------

    def _start_monitor(self, interval: int | None = None) -> None:
        self._stop_monitor()
        if interval is None:
            interval = int(self.db.get(_DB_OWNER, "monitor_interval", _DEFAULT_INTERVAL))
        self._monitor_task = asyncio.ensure_future(self._monitor_loop(interval))

    def _stop_monitor(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = None

    async def _monitor_loop(self, interval: int) -> None:
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            try:
                await self._check_thresholds()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("HealthModule: threshold check failed")

    async def _check_thresholds(self) -> None:
        ram_limit = self.db.get(_DB_OWNER, "ram_limit", _DEFAULT_RAM_LIMIT)
        cpu_limit = self.db.get(_DB_OWNER, "cpu_limit", _DEFAULT_CPU_LIMIT)
        if not _PSUTIL:
            return
        try:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=1)
        except Exception:
            return
        logchat = self.db.get("kitsune.core", "logchat", None)
        if not logchat:
            return
        if mem.percent >= ram_limit:
            try:
                await self.client.send_message(
                    logchat,
                    self.strings("alert_ram", pct=mem.percent, limit=ram_limit),
                    parse_mode="html",
                )
            except Exception:
                logger.debug("HealthModule: failed to send RAM alert", exc_info=True)
        if cpu >= cpu_limit:
            try:
                await self.client.send_message(
                    logchat,
                    self.strings("alert_cpu", pct=cpu, limit=cpu_limit),
                    parse_mode="html",
                )
            except Exception:
                logger.debug("HealthModule: failed to send CPU alert", exc_info=True)
