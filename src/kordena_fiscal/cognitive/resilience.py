"""Failure isolation for model calls: deadline, circuit breaker and bulkhead."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TypeVar

T = TypeVar("T")


class DeadlineExceeded(Exception):
    pass


class CircuitOpen(Exception):
    pass


class BulkheadFull(Exception):
    pass


class CircuitBreaker:
    """Opens after consecutive failures; half-opens after a cool-down for one probe."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0:
            raise ValueError("invalid circuit breaker configuration")
        self._threshold = failure_threshold
        self._recovery = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._clock() - self._opened_at >= self._recovery:
                return "half_open"
            return "open"

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if self._clock() - self._opened_at < self._recovery:
                raise CircuitOpen("circuit open")
            if self._probing:
                raise CircuitOpen("circuit half-open probe in flight")
            self._probing = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probing = False

    def record_failure(self) -> None:
        with self._lock:
            self._probing = False
            self._failures += 1
            if self._failures >= self._threshold or self._opened_at is not None:
                self._opened_at = self._clock()


class Bulkhead:
    """Caps in-flight model calls so a slow provider cannot exhaust the process."""

    def __init__(self, max_concurrent: int = 4) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._semaphore = threading.BoundedSemaphore(max_concurrent)

    def acquire(self) -> None:
        if not self._semaphore.acquire(blocking=False):
            raise BulkheadFull("too many concurrent advisory calls")

    def release(self) -> None:
        self._semaphore.release()


_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cognitive-model")


def call_with_deadline(fn: Callable[[], T], seconds: float) -> T:
    """Run ``fn`` and give up after ``seconds``. The worker thread cannot be killed, so the
    bulkhead must bound how many abandoned calls can pile up."""

    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=seconds)
    except FutureTimeout as exc:
        future.cancel()
        raise DeadlineExceeded(f"model call exceeded {seconds}s") from exc
