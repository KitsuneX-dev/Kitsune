from __future__ import annotations

import asyncio
import logging
import time
import typing

logger = logging.getLogger(__name__)


class TokenBucket:

    __slots__ = ("capacity", "rate", "_tokens", "_last_refill", "_lock")

    def __init__(self, capacity: float = 10.0, rate: float = 1.0) -> None:
        self.capacity = capacity
        self.rate = rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, amount: float = 1.0) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= amount:
                self._tokens -= amount
                return True
            return False

    def remaining(self) -> float:
        elapsed = time.monotonic() - self._last_refill
        return min(self.capacity, self._tokens + elapsed * self.rate)


class RateLimiter:

    def __init__(
        self,
        owner_capacity: float = 20.0,
        owner_rate: float = 3.0,
        other_capacity: float = 5.0,
        other_rate: float = 0.5,
    ) -> None:
        self._owner_capacity = owner_capacity
        self._owner_rate = owner_rate
        self._other_capacity = other_capacity
        self._other_rate = other_rate
        self._buckets: dict[int, TokenBucket] = {}
        self._owner_id: int | None = None
        self._cleanup_task: asyncio.Task | None = None

    def set_owner(self, owner_id: int) -> None:
        self._owner_id = owner_id

    def _get_bucket(self, user_id: int) -> TokenBucket:
        if user_id not in self._buckets:
            if user_id == self._owner_id:
                self._buckets[user_id] = TokenBucket(self._owner_capacity, self._owner_rate)
            else:
                self._buckets[user_id] = TokenBucket(self._other_capacity, self._other_rate)
        return self._buckets[user_id]

    async def check(self, user_id: int, command: str = "") -> bool:
        bucket = self._get_bucket(user_id)
        allowed = await bucket.consume()
        if not allowed:
            logger.debug(
                "Rate limit hit: user_id=%d command=%r remaining=%.2f",
                user_id, command, bucket.remaining(),
            )
        return allowed

    def remaining(self, user_id: int) -> float:
        return self._get_bucket(user_id).remaining()

    def start_cleanup(self, interval: float = 300.0) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.ensure_future(self._cleanup_loop(interval))

    async def _cleanup_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            stale = [
                uid for uid, bucket in self._buckets.items()
                if bucket.remaining() >= bucket.capacity and uid != self._owner_id
            ]
            for uid in stale:
                del self._buckets[uid]
            if stale:
                logger.debug("RateLimiter: cleaned up %d stale buckets", len(stale))
