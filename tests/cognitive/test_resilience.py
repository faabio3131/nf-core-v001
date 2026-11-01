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
