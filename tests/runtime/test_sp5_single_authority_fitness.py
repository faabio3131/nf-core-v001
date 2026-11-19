"""SP5 architectural fitness: preserve one fiscal authority across web/gateway.

These source-contract tests complement behavioral/E2E coverage, but are NOT
external homologation or a genuinely independent code review.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


def test_sp5_web_mutations_reuse_durable_fiscal_intents() -> None:
    portal = _source("portal/app.js")
    recovery = _source("src/kordena_fiscal/web/fiscal_intent_recovery.py")

    assert '/v1/portal/fiscal-intents/prepare/' in portal
    assert '/v1/portal/fiscal-intents/' in portal
    assert '/resume' in portal
    assert '"Idempotency-Key": pendingFiscalRequest.key' in portal
    assert '"X-CSRF-Token": csrfToken()' in portal
    assert 'row.get("tenant_id") != scope.tenant_id' in recovery
    assert 'row.get("unit_id") != scope.unit_id' in recovery


def test_sp5_nfse_preparation_reuses_authenticated_scope_and_durable_serial() -> None:
    preparer = _source("src/kordena_fiscal/web/native_nfse_preparation.py")
    application = _source("src/kordena_fiscal/application/service.py")
    builder = _source("src/kordena_fiscal/issuance/nfse_dps_builder.py")

    assert (
        "authority.assert_permission(PortalPermission.DOCUMENT_ISSUE, unit_id=unit)"
        in preparer
    )
    assert (
        "authority.assert_permission(PortalPermission.CONFIGURATION_WRITE, "
        "unit_id=unit)"
        in preparer
    )
    assert "tenant_id=authority.tenant_id" in preparer
    assert "app = FiscalApplicationService(factory)" in preparer
    assert "app.prepare_nfse_authorization(" in preparer
    assert "uow.dps_sequences.reserve(" in application
    assert "DPS number not reserved by durable fiscal Unit of Work" in builder


def test_sp5_national_get_and_post_share_signed_receipt_verifier() -> None:
    query = _source("src/kordena_fiscal/gateway/nfse_national_query.py")
    gateway = _source("src/kordena_fiscal/gateway/nfse_national_homologation.py")
    receipt = _source("src/kordena_fiscal/gateway/nfse_national_receipt.py")

    assert "return validate_official_nfse_receipt(" in query
    # GET binds the receipt to the archived dispatch identity (or the governed
    # legacy context), both derived from the canonical request identity.
    assert "expected, profile = evidence.identity, evidence.schema_profile" in query
    assert "legacy_national_receipt_context(xml, key, request)" in query
    assert (
        "return NationalReceiptIdentity.from_request(request, schema_profile=profile), profile"
        in receipt
    )
    assert "document = validate_official_nfse_receipt(" in gateway
    assert "expected=expected, schema_profile=schema_profile" in gateway
    assert "def _verify_nfse_receipt_signature(" in receipt
    assert '_verify_nfse_receipt_signature(root, infos[0], "NFS" + key)' in receipt


def test_sp5_fitness_does_not_hide_nfce_manual_or_icp_trust_gaps() -> None:
    portal = _source("portal/app.js")
    receipt = _source("src/kordena_fiscal/gateway/nfse_national_receipt.py")

    assert (
        'if (usesPreparedReference()) return '
        '{document_id: operationDocument.value.trim()}'
        in portal
    )
    assert "not ICP-Brasil path/revocation" in receipt
    # Receipt XSD is selected by explicit profile (NT009 restricted or
    # production); unsupported profiles still fail closed.
    assert (
        "national_nfse_receipt_validator(profile=schema_profile).validate_document(xml)"
        in receipt
    )
    assert "National NFSe receipt schema profile unsupported" in receipt
