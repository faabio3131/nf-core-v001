import time

import pytest

from kordena_fiscal.cognitive import Bulkhead, CircuitBreaker
from kordena_fiscal.cognitive.resilience import (
    BulkheadFull,
    CircuitOpen,
    DeadlineExceeded,
    call_with_deadline,
)


def test_breaker_opens_then_half_opens_and_recovers() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=10, clock=lambda: now[0])
    breaker.before_call()
    breaker.record_failure()
    breaker.before_call()
    breaker.record_failure()
    assert breaker.state == "open"
    with pytest.raises(CircuitOpen):
        breaker.before_call()
    now[0] = 11
    assert breaker.state == "half_open"
    breaker.before_call()  # single probe allowed
    with pytest.raises(CircuitOpen):
        breaker.before_call()
    breaker.record_success()
    assert breaker.state == "closed"


def test_failed_probe_reopens_immediately() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=5, clock=lambda: now[0])
    breaker.record_failure()
    now[0] = 6
    breaker.before_call()
    breaker.record_failure()
    assert breaker.state == "open"


def test_bulkhead_limits_concurrency() -> None:
    bulkhead = Bulkhead(1)
    bulkhead.acquire()
    with pytest.raises(BulkheadFull):
        bulkhead.acquire()
    bulkhead.release()
    bulkhead.acquire()


def test_deadline_raises_when_call_is_too_slow() -> None:
    assert call_with_deadline(lambda: 7, 1.0) == 7
    with pytest.raises(DeadlineExceeded):
        call_with_deadline(lambda: time.sleep(0.5), 0.05)


def test_deadline_keeps_running_worker_slot_until_completion() -> None:
    from threading import Event

    bulkhead = Bulkhead(1)
    started, allow_exit, released = Event(), Event(), Event()

    def work() -> int:
        started.set()
        allow_exit.wait(timeout=5)
        return 7

    def release() -> None:
        bulkhead.release()
        released.set()

    bulkhead.acquire()
    try:
        with pytest.raises(DeadlineExceeded):
            call_with_deadline(work, 0.1, on_complete=release)
        assert started.is_set()
        with pytest.raises(BulkheadFull):
            bulkhead.acquire()
    finally:
        allow_exit.set()
        assert released.wait(5)
    bulkhead.acquire()
    bulkhead.release()


def test_deadline_releases_slot_on_success_and_exception() -> None:
    bulkhead = Bulkhead(1)
    bulkhead.acquire()
    assert call_with_deadline(lambda: 7, 1, on_complete=bulkhead.release) == 7
    bulkhead.acquire()

    def failed() -> int:
        raise ValueError("test failure")

    with pytest.raises(ValueError, match="test failure"):
        call_with_deadline(failed, 1, on_complete=bulkhead.release)
    bulkhead.acquire()
    bulkhead.release()


def test_deadline_releases_cancelled_queued_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from kordena_fiscal.cognitive import resilience

    gate, started, ran = Event(), Event(), Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(resilience, "_EXECUTOR", executor)

        def occupy() -> None:
            started.set()
            gate.wait(5)

        blocker = executor.submit(occupy)
        bulkhead = Bulkhead(1)
        bulkhead.acquire()
        try:
            assert started.wait(5)
            with pytest.raises(DeadlineExceeded):
                call_with_deadline(ran.set, 0.05, on_complete=bulkhead.release)
            bulkhead.acquire()
            bulkhead.release()
        finally:
            gate.set()
            blocker.result(timeout=5)
    assert not ran.is_set()


def test_deadline_releases_slot_on_submission_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from kordena_fiscal.cognitive import resilience

    executor = ThreadPoolExecutor(max_workers=1)
    executor.shutdown()
    monkeypatch.setattr(resilience, "_EXECUTOR", executor)
    bulkhead = Bulkhead(1)
    bulkhead.acquire()
    with pytest.raises(RuntimeError):
        call_with_deadline(lambda: 1, 1, on_complete=bulkhead.release)
    bulkhead.acquire()
    bulkhead.release()
