"""REC-22: server-derived cognitive usage identity and context-provenance isolation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kordena_fiscal.cognitive import Capability, ContextPackBuilder
from kordena_fiscal.cognitive.api import _scoped_advice_request_id
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError

from .conftest import make_request


def test_scoped_advice_request_id_separates_all_server_authorities() -> None:
    baseline = {
        "tenant_id": "tenant-a",
        "unit_id": "unit-a",
        "account_id": "owner-a",
        "environment": FiscalEnvironment.HOMOLOGATION,
        "capability": Capability.EXPLAIN_REJECTION,
        "subject_id": "doc-1",
        "key": "same-browser-key",
    }
    expected = _scoped_advice_request_id(**baseline)
    assert len(expected) == 64 and expected == _scoped_advice_request_id(**baseline)
    alternatives = (
        ("tenant_id", "tenant-b"),
        ("unit_id", "unit-b"),
        ("account_id", "operator-a"),
        ("environment", FiscalEnvironment.PRODUCTION),
        ("capability", Capability.EXPLAIN_RECONCILIATION),
        ("subject_id", "doc-2"),
        ("subject_id", None),
        ("key", "other-browser-key"),
    )
    for field, value in alternatives:
        other = {**baseline, field: value}
        assert _scoped_advice_request_id(**other) != expected, field


def test_context_hash_separates_authenticated_actor_and_subject() -> None:
    request = make_request()
    builder = ContextPackBuilder(nonce_factory=lambda: "fixed-test-boundary")
    baseline = builder.build(request).prompt.context_hash
    assert baseline == builder.build(request).prompt.context_hash

    actor = replace(request, actor_id="another-authorized-account")
    first_subject = replace(request, subject_id="doc-1")
    second_subject = replace(request, subject_id="doc-2")
    fingerprints = {
        builder.build(other).prompt.context_hash
        for other in (request, actor, first_subject, second_subject)
    }
    assert len(fingerprints) == 4


@pytest.mark.parametrize("invalid", ["", "   ", "x" * 129])
def test_cognitive_subject_identity_cannot_be_blank_or_oversized(invalid: str) -> None:
    with pytest.raises(FiscalValidationError):
        replace(make_request(), subject_id=invalid)
