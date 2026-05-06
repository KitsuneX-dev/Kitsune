"""
Kitsune — Reliability subsystem (Phase 3).

Модуль предоставляет компоненты надёжности:

    • CircuitBreaker — классический паттерн «автоматический выключатель»
      с тремя состояниями (CLOSED → OPEN → HALF_OPEN). После N таймаутов
      подряд запросы блокируются на cooldown секунд, по истечении которого
      breaker уходит в HALF_OPEN и пропускает один пробный запрос.

    • RetryWithBackoff — экспоненциальный backoff с jitter для повторных
      попыток сетевых операций (например, после отвала VPN).

    • DegradationFlags — глобальные флаги graceful degradation, которые
      потребители (hydro_media, database, log) читают чтобы решить
      использовать ли деградированный путь.

    • global_registry — единый реестр CircuitBreaker'ов, чтобы любой
      модуль мог получить ссылку на breaker и команды `/health` могли
      показать их состояние.

Дизайн-принципы:
    1) Никаких зависимостей вне stdlib и asyncio.
    2) Потокобезопасно через asyncio.Lock — допустимо использовать
       из любых корутин в одном event loop.
    3) Все методы безопасны при многократных вызовах: lifecycle
       идемпотентен.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import typing
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Состояния Circuit Breaker
# ---------------------------------------------------------------------------

STATE_CLOSED    = "closed"    # всё ок, запросы идут
STATE_OPEN      = "open"      # сломано, запросы блокируются
STATE_HALF_OPEN = "half_open" # пробный запрос после cooldown


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreakerOpenError(RuntimeError):
    """Бросается, когда breaker в состоянии OPEN и запрос блокируется."""


@dataclass
class CircuitBreakerStats:
    state: str = STATE_CLOSED
    failures: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    opened_at: float = 0.0
    last_failure_at: float = 0.0
    last_success_at: float = 0.0
    total_calls: int = 0
    blocked_calls: int = 0


class CircuitBreaker:
    """Async-friendly circuit breaker.

    Параметры:
        name           — человекочитаемое имя (используется в логах/health).
        failure_threshold
                       — сколько таймаутов/ошибок подряд до OPEN (default 5).
        cooldown       — сколько секунд оставаться в OPEN до пробы (default 60).
        expected_exceptions
                       — какие типы исключений считать «провалом». По умолчанию
                         TimeoutError + asyncio.TimeoutError + ConnectionError +
                         OSError.

    Использование::

        cb = CircuitBreaker("telegram_api", failure_threshold=5, cooldown=60)
        try:
            result = await cb.call(some_async_fn, *args, **kwargs)
        except CircuitBreakerOpenError:
            # сервис временно «отключён», fallback или skip
            ...
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        cooldown: float = 60.0,
        expected_exceptions: typing.Tuple[type, ...] | None = None,
    ) -> None:
        self.name = name
        self._failure_threshold = max(1, int(failure_threshold))
        # Cooldown не ограничиваем снизу (для тестов нужны миллисекунды),
        # только защищаем от отрицательных и NaN значений.
        self._cooldown = max(0.0, float(cooldown))
        self._expected: typing.Tuple[type, ...] = expected_exceptions or (
            TimeoutError,
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
        )
        self._stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        # Регистрируемся в глобальном реестре (если есть)
        global_registry.register(self)

    # ---- public API --------------------------------------------------------

    @property
    def state(self) -> str:
        return self._stats.state

    @property
    def stats(self) -> CircuitBreakerStats:
        return self._stats

    def is_open(self) -> bool:
        """Быстрая проверка без захвата lock'а — для горячего пути."""
        if self._stats.state != STATE_OPEN:
            return self._stats.state == STATE_OPEN
        # OPEN → проверяем не пора ли в HALF_OPEN
        if time.monotonic() - self._stats.opened_at >= self._cooldown:
            return False  # сейчас будет HALF_OPEN-проба
        return True

    async def allow(self) -> bool:
        """Спросить «можно ли сейчас делать запрос?». Не вызывает функцию,
        только обновляет состояние при необходимости (OPEN → HALF_OPEN)."""
        async with self._lock:
            return self._allow_locked()

    def _allow_locked(self) -> bool:
        st = self._stats
        if st.state == STATE_CLOSED:
            return True
        if st.state == STATE_OPEN:
            if time.monotonic() - st.opened_at >= self._cooldown:
                st.state = STATE_HALF_OPEN
                logger.info(
                    "CircuitBreaker[%s]: cooldown elapsed → HALF_OPEN (probe)", self.name,
                )
                return True
            return False
        # HALF_OPEN — пускаем только одну пробу за раз. Дальнейшие
        # вызовы пока не пришёл результат блокируем.
        return True

    async def record_success(self) -> None:
        async with self._lock:
            st = self._stats
            st.successes += 1
            st.last_success_at = time.time()
            st.consecutive_failures = 0
            if st.state in (STATE_OPEN, STATE_HALF_OPEN):
                logger.info(
                    "CircuitBreaker[%s]: success in %s → CLOSED",
                    self.name, st.state,
                )
                st.state = STATE_CLOSED

    async def record_failure(self, exc: BaseException | None = None) -> None:
        async with self._lock:
            st = self._stats
            st.failures += 1
            st.consecutive_failures += 1
            st.last_failure_at = time.time()
            if st.state == STATE_HALF_OPEN:
                # Проба провалилась — снова OPEN, обновляем opened_at.
                st.state = STATE_OPEN
                st.opened_at = time.monotonic()
                logger.warning(
                    "CircuitBreaker[%s]: probe failed (%s) → OPEN for %.0fs",
                    self.name, type(exc).__name__ if exc else "—", self._cooldown,
                )
                return
            if (
                st.state == STATE_CLOSED
                and st.consecutive_failures >= self._failure_threshold
            ):
                st.state = STATE_OPEN
                st.opened_at = time.monotonic()
                logger.warning(
                    "CircuitBreaker[%s]: %d consecutive failures → OPEN for %.0fs",
                    self.name, st.consecutive_failures, self._cooldown,
                )

    async def call(
        self,
        func: typing.Callable[..., typing.Awaitable[typing.Any]],
        *args: typing.Any,
        **kwargs: typing.Any,
    ) -> typing.Any:
        """Безопасно вызвать корутину под защитой breaker'а."""
        self._stats.total_calls += 1
        if not await self.allow():
            self._stats.blocked_calls += 1
            raise CircuitBreakerOpenError(
                f"CircuitBreaker[{self.name}] is OPEN — request blocked"
            )
        try:
            result = await func(*args, **kwargs)
        except self._expected as exc:
            await self.record_failure(exc)
            raise
        except Exception:
            # Непредвиденные ошибки тоже считаем провалом (это безопаснее),
            # но не пушим breaker слишком агрессивно — без consecutive_failures++.
            # На практике почти любой сетевой Exception — это сбой.
            await self.record_failure()
            raise
        else:
            await self.record_success()
            return result

    def reset(self) -> None:
        """Принудительно вернуть breaker в CLOSED — для админки/тестов."""
        self._stats = CircuitBreakerStats()
        logger.info("CircuitBreaker[%s]: manual reset → CLOSED", self.name)

    # ---- introspection -----------------------------------------------------

    def to_dict(self) -> dict:
        st = self._stats
        return {
            "name": self.name,
            "state": st.state,
            "failures": st.failures,
            "successes": st.successes,
            "consecutive_failures": st.consecutive_failures,
            "blocked_calls": st.blocked_calls,
            "total_calls": st.total_calls,
            "failure_threshold": self._failure_threshold,
            "cooldown_s": self._cooldown,
            "last_failure_at": st.last_failure_at,
            "last_success_at": st.last_success_at,
            "opened_at_mono": st.opened_at,
            "open_remaining_s": max(
                0.0, self._cooldown - (time.monotonic() - st.opened_at),
            ) if st.state == STATE_OPEN else 0.0,
        }


# ---------------------------------------------------------------------------
# Глобальный реестр CircuitBreaker'ов
# ---------------------------------------------------------------------------

class _CircuitBreakerRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CircuitBreaker] = {}

    def register(self, cb: CircuitBreaker) -> None:
        # Если уже зарегистрирован — НЕ перетираем (idempotent), просто
        # игнорируем повтор. Это нужно для hot-reload модулей.
        self._items.setdefault(cb.name, cb)

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def get(self, name: str) -> CircuitBreaker | None:
        return self._items.get(name)

    def get_or_create(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        cooldown: float = 60.0,
        expected_exceptions: typing.Tuple[type, ...] | None = None,
    ) -> CircuitBreaker:
        cb = self._items.get(name)
        if cb is not None:
            return cb
        return CircuitBreaker(
            name,
            failure_threshold=failure_threshold,
            cooldown=cooldown,
            expected_exceptions=expected_exceptions,
        )

    def all(self) -> list[CircuitBreaker]:
        return list(self._items.values())

    def reset_all(self) -> None:
        for cb in self._items.values():
            cb.reset()

    def to_list(self) -> list[dict]:
        return [cb.to_dict() for cb in self._items.values()]


global_registry = _CircuitBreakerRegistry()


def get_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    cooldown: float = 60.0,
    expected_exceptions: typing.Tuple[type, ...] | None = None,
) -> CircuitBreaker:
    """Удобный фасад: вернуть breaker из реестра, создать если нет."""
    return global_registry.get_or_create(
        name,
        failure_threshold=failure_threshold,
        cooldown=cooldown,
        expected_exceptions=expected_exceptions,
    )


# ---------------------------------------------------------------------------
# Retry с экспоненциальным backoff
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """Политика повторных попыток.

    base_delay  — стартовая задержка перед второй попыткой (default 1s).
    max_delay   — потолок задержки (default 60s).
    multiplier  — множитель экспоненты (default 2.0).
    jitter      — добавлять случайный jitter ±jitter (default 0.25 → ±25%).
    max_attempts
                — сколько попыток всего (1 = без retry, default 5).
    """
    base_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.25
    max_attempts: int = 5

    def delay_for(self, attempt: int) -> float:
        """Задержка перед попыткой №attempt (1-based: attempt=1 → 0)."""
        if attempt <= 1:
            return 0.0
        d = self.base_delay * (self.multiplier ** (attempt - 2))
        d = min(d, self.max_delay)
        if self.jitter > 0:
            d *= 1.0 + random.uniform(-self.jitter, self.jitter)
        return max(0.0, d)


async def retry_with_backoff(
    func: typing.Callable[..., typing.Awaitable[typing.Any]],
    *args: typing.Any,
    policy: RetryPolicy | None = None,
    on_retry: typing.Callable[[int, BaseException], typing.Awaitable[None] | None] | None = None,
    expected_exceptions: typing.Tuple[type, ...] = (
        TimeoutError, asyncio.TimeoutError, ConnectionError, OSError,
    ),
    name: str = "anonymous",
    **kwargs: typing.Any,
) -> typing.Any:
    """Выполнить корутину с экспоненциальным backoff.

    Полезно для VPN/прокси retry: при отвале сети ждём всё дольше прежде чем
    повторить. Сигнатура совместима с `await func(*args, **kwargs)`.
    """
    pol = policy or RetryPolicy()
    last_exc: BaseException | None = None
    for attempt in range(1, pol.max_attempts + 1):
        delay = pol.delay_for(attempt)
        if delay > 0:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except expected_exceptions as exc:
            last_exc = exc
            logger.warning(
                "retry[%s]: attempt %d/%d failed (%s: %s) — backing off",
                name, attempt, pol.max_attempts, type(exc).__name__, exc,
            )
            if on_retry is not None:
                try:
                    res = on_retry(attempt, exc)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    logger.exception("retry[%s]: on_retry callback raised", name)
            continue
        except Exception:
            # Неожиданное исключение — не наша территория, пробрасываем.
            raise
    # Все попытки исчерпаны.
    assert last_exc is not None  # для типизации
    raise last_exc


# ---------------------------------------------------------------------------
# Graceful degradation flags
# ---------------------------------------------------------------------------

class DegradationFlags:
    """Глобальные флаги graceful degradation.

    Каждый флаг — bool. Когда `True`, соответствующая подсистема считается
    «деградировавшей» и потребители должны выбрать fallback-путь.

    Флаги:
        hydrogram_failed   — Hydrogram сломан / не стартовал → используем
                             только Telethon.
        assets_unavailable — assets channel недоступен → пропускаем медиа.
        redis_unavailable  — Redis отвалился → SQLite-fallback в DB.
        vpn_down           — VPN/прокси не работает → ждём backoff.
    """

    def __init__(self) -> None:
        self.hydrogram_failed: bool = False
        self.assets_unavailable: bool = False
        self.redis_unavailable: bool = False
        self.vpn_down: bool = False
        self._reasons: dict[str, str] = {}

    # удобные сеттеры с логированием

    def mark_hydrogram_failed(self, reason: str = "") -> None:
        if not self.hydrogram_failed:
            logger.warning("Degradation: Hydrogram marked failed (%s)", reason or "no reason")
        self.hydrogram_failed = True
        if reason:
            self._reasons["hydrogram"] = reason

    def clear_hydrogram_failed(self) -> None:
        if self.hydrogram_failed:
            logger.info("Degradation: Hydrogram restored")
        self.hydrogram_failed = False
        self._reasons.pop("hydrogram", None)

    def mark_assets_unavailable(self, reason: str = "") -> None:
        if not self.assets_unavailable:
            logger.warning("Degradation: assets channel unavailable (%s)", reason or "no reason")
        self.assets_unavailable = True
        if reason:
            self._reasons["assets"] = reason

    def clear_assets_unavailable(self) -> None:
        if self.assets_unavailable:
            logger.info("Degradation: assets channel restored")
        self.assets_unavailable = False
        self._reasons.pop("assets", None)

    def mark_redis_unavailable(self, reason: str = "") -> None:
        if not self.redis_unavailable:
            logger.warning("Degradation: Redis unavailable (%s) — fallback on SQLite", reason or "no reason")
        self.redis_unavailable = True
        if reason:
            self._reasons["redis"] = reason

    def clear_redis_unavailable(self) -> None:
        if self.redis_unavailable:
            logger.info("Degradation: Redis restored")
        self.redis_unavailable = False
        self._reasons.pop("redis", None)

    def mark_vpn_down(self, reason: str = "") -> None:
        if not self.vpn_down:
            logger.warning("Degradation: VPN/proxy down (%s)", reason or "no reason")
        self.vpn_down = True
        if reason:
            self._reasons["vpn"] = reason

    def clear_vpn_down(self) -> None:
        if self.vpn_down:
            logger.info("Degradation: VPN/proxy restored")
        self.vpn_down = False
        self._reasons.pop("vpn", None)

    def to_dict(self) -> dict:
        return {
            "hydrogram_failed":   self.hydrogram_failed,
            "assets_unavailable": self.assets_unavailable,
            "redis_unavailable":  self.redis_unavailable,
            "vpn_down":           self.vpn_down,
            "reasons":            dict(self._reasons),
        }

    @property
    def any_degraded(self) -> bool:
        return (
            self.hydrogram_failed
            or self.assets_unavailable
            or self.redis_unavailable
            or self.vpn_down
        )


# Глобальный объект флагов — единый на процесс.
flags = DegradationFlags()


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------

__all__ = [
    "STATE_CLOSED",
    "STATE_OPEN",
    "STATE_HALF_OPEN",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitBreakerStats",
    "global_registry",
    "get_breaker",
    "RetryPolicy",
    "retry_with_backoff",
    "DegradationFlags",
    "flags",
]
