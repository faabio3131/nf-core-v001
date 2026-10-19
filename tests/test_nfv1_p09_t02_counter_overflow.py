"""Operational counter overflow must never poison the canonical registry."""

import sys

import pytest

from kordena_fiscal.runtime.observability import MetricsRegistry


def test_counter_overflow_preserves_last_valid_sample() -> None:
    metrics = MetricsRegistry()
    metrics.increment("nfcore_fiscal_rejection_total", sys.float_info.max, outcome="failed")
    before = metrics.snapshot()
    with pytest.raises(ValueError, match="accumulation must remain finite"):
        metrics.increment("nfcore_fiscal_rejection_total", sys.float_info.max, outcome="failed")
    assert metrics.snapshot() == before


def test_valid_counter_increments_still_accumulate() -> None:
    metrics = MetricsRegistry()
    metrics.increment("nfcore_fiscal_rejection_total", 1.0, outcome="failed")
    metrics.increment("nfcore_fiscal_rejection_total", 2.0, outcome="failed")
    assert metrics.snapshot()[0].value == 3.0
