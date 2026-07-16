from __future__ import annotations
import asyncio
import time
import unittest
from kitsune.core.reliability import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    DegradationFlags,
    RetryPolicy,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    flags as global_flags,
    get_breaker,
    global_registry,
    retry_with_backoff,
)


def _arun(coro):
    return asyncio.run(coro)
class CircuitBreakerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.name = f"test_cb_{id(self)}_{time.monotonic_ns()}"
    def tearDown(self) -> None:
        global_registry.unregister(self.name)
    def test_initial_state_closed(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=3, cooldown=1.0)
        self.assertEqual(cb.state, STATE_CLOSED)
        self.assertTrue(_arun(cb.allow()))
    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=3, cooldown=10.0)
        for _ in range(3):
            _arun(cb.record_failure(TimeoutError()))
        self.assertEqual(cb.state, STATE_OPEN)
        self.assertFalse(_arun(cb.allow()))
    def test_blocks_calls_when_open(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=2, cooldown=10.0)
        async def boom():
            raise TimeoutError("simulated")
        async def runner():
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    await cb.call(boom)
            with self.assertRaises(CircuitBreakerOpenError):
                await cb.call(boom)
            self.assertGreaterEqual(cb.stats.blocked_calls, 1)
        _arun(runner())
    def test_half_open_after_cooldown_and_recover(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=2, cooldown=0.05)
        async def fail():
            raise TimeoutError("x")
        async def ok():
            return "ok"
        async def runner():
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    await cb.call(fail)
            self.assertEqual(cb.state, STATE_OPEN)
            await asyncio.sleep(0.08)
            result = await cb.call(ok)
            self.assertEqual(result, "ok")
            self.assertEqual(cb.state, STATE_CLOSED)
        _arun(runner())
    def test_half_open_failure_returns_to_open(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=2, cooldown=0.05)
        async def fail():
            raise TimeoutError("x")
        async def runner():
            for _ in range(2):
                with self.assertRaises(TimeoutError):
                    await cb.call(fail)
            await asyncio.sleep(0.08)
            with self.assertRaises(TimeoutError):
                await cb.call(fail)
            self.assertEqual(cb.state, STATE_OPEN)
        _arun(runner())
    def test_reset(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=2, cooldown=10.0)
        for _ in range(2):
            _arun(cb.record_failure(TimeoutError()))
        self.assertEqual(cb.state, STATE_OPEN)
        cb.reset()
        self.assertEqual(cb.state, STATE_CLOSED)
        self.assertEqual(cb.stats.consecutive_failures, 0)
    def test_to_dict_shape(self) -> None:
        cb = CircuitBreaker(self.name, failure_threshold=5, cooldown=60.0)
        d = cb.to_dict()
        for required in (
            "name", "state", "failures", "successes",
            "consecutive_failures", "blocked_calls", "total_calls",
            "failure_threshold", "cooldown_s",
        ):
            self.assertIn(required, d)
class RetryWithBackoffTests(unittest.TestCase):
    def test_succeeds_first_try(self) -> None:
        calls = {"n": 0}
        async def ok():
            calls["n"] += 1
            return 42
        result = _arun(retry_with_backoff(
            ok, policy=RetryPolicy(base_delay=0.01, max_attempts=3),
            name="ok",
        ))
        self.assertEqual(result, 42)
        self.assertEqual(calls["n"], 1)
    def test_retries_then_succeeds(self) -> None:
        calls = {"n": 0}
        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("flaky")
            return "ok"
        result = _arun(retry_with_backoff(
            flaky,
            policy=RetryPolicy(base_delay=0.001, max_delay=0.01,
                               jitter=0.0, max_attempts=5),
            name="flaky",
        ))
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 3)
    def test_raises_after_max_attempts(self) -> None:
        calls = {"n": 0}
        async def always_fail():
            calls["n"] += 1
            raise TimeoutError("nope")
        with self.assertRaises(TimeoutError):
            _arun(retry_with_backoff(
                always_fail,
                policy=RetryPolicy(base_delay=0.001, max_delay=0.01,
                                   jitter=0.0, max_attempts=4),
                name="t",
            ))
        self.assertEqual(calls["n"], 4)
    def test_unexpected_exception_not_retried(self) -> None:
        calls = {"n": 0}
        async def boom():
            calls["n"] += 1
            raise ValueError("not a retryable error")
        with self.assertRaises(ValueError):
            _arun(retry_with_backoff(
                boom,
                policy=RetryPolicy(base_delay=0.001, max_attempts=3),
                name="boom",
            ))
        self.assertEqual(calls["n"], 1)
    def test_delay_for_monotonic(self) -> None:
        pol = RetryPolicy(base_delay=1.0, multiplier=2.0,
                          max_delay=10.0, jitter=0.0)
        self.assertEqual(pol.delay_for(1), 0.0)
        self.assertAlmostEqual(pol.delay_for(2), 1.0, delta=0.001)
        self.assertAlmostEqual(pol.delay_for(3), 2.0, delta=0.001)
        self.assertLessEqual(pol.delay_for(10), 10.0)
class DegradationFlagsTests(unittest.TestCase):
    def test_default_all_clear(self) -> None:
        f = DegradationFlags()
        self.assertFalse(f.hydrogram_failed)
        self.assertFalse(f.assets_unavailable)
        self.assertFalse(f.redis_unavailable)
        self.assertFalse(f.vpn_down)
        self.assertFalse(f.any_degraded)
    def test_set_and_clear(self) -> None:
        f = DegradationFlags()
        f.mark_hydrogram_failed("test")
        self.assertTrue(f.hydrogram_failed)
        self.assertTrue(f.any_degraded)
        f.clear_hydrogram_failed()
        self.assertFalse(f.hydrogram_failed)
    def test_to_dict(self) -> None:
        f = DegradationFlags()
        f.mark_redis_unavailable("ping timeout")
        d = f.to_dict()
        self.assertTrue(d["redis_unavailable"])
        self.assertEqual(d["reasons"].get("redis"), "ping timeout")
    def test_global_flags_singleton(self) -> None:
        self.assertTrue(hasattr(global_flags, "hydrogram_failed"))
        self.assertTrue(hasattr(global_flags, "redis_unavailable"))
class RegistryTests(unittest.TestCase):
    def test_get_breaker_idempotent(self) -> None:
        name = f"reg_{time.monotonic_ns()}"
        cb1 = get_breaker(name, failure_threshold=2, cooldown=5.0)
        cb2 = get_breaker(name, failure_threshold=99, cooldown=999.0)
        self.assertIs(cb1, cb2)
        global_registry.unregister(name)
    def test_to_list_includes_breaker(self) -> None:
        name = f"reg_list_{time.monotonic_ns()}"
        cb = get_breaker(name)
        listed = [item["name"] for item in global_registry.to_list()]
        self.assertIn(name, listed)
        global_registry.unregister(name)
if __name__ == "__main__":
    unittest.main()

