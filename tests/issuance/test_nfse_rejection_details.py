"""Typed, lossless NFS-e rejection contract; provider text stays out of Portal."""
from __future__ import annotations

import pytest

from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationResult, NfseRejectionDetail
from kordena_fiscal.lifecycle import IdempotencyKey


def _result(
    status: AuthorizationStatus,
    *,
    code: str | None = None,
    message: str | None = None,
    details: tuple[NfseRejectionDetail, ...] = (),
) -> NfseAuthorizationResult:
    return NfseAuthorizationResult(
        status=status,
        scope=ExecutionScope(
            tenant_id="test-tenant", unit_id="test-unit",
            environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="rejection-test", host_namespace="nfcore-test",
        ),
        document_id="test-nfse",
        idempotency_key=IdempotencyKey("f" * 64),
        request_fingerprint="e" * 64,
        provider=GatewayProviderMetadata("sefin-nacional-test", "1"),
        invoice_reference="synthetic-key" if status is AuthorizationStatus.AUTHORIZED else None,
        rejection_code=code,
        rejection_message=message,
        rejections=details,
    )


def test_long_raw_message_is_preserved_without_512_character_truncation() -> None:
    raw = "  Erro fiscal detalhado: " + "conteudo " * 110
    detail = NfseRejectionDetail(code="E002", origin="SEFIN_NACIONAL", raw_message=raw)
    result = _result(
        AuthorizationStatus.REJECTED, code=detail.code,
        message=raw.strip(), details=(detail,),
    )
    assert len(raw) > 512
    assert result.normalized_rejections()[0].raw_message == raw
    assert result.rejection_message == raw.strip()


def test_multiple_rejections_keep_order_origin_and_exact_raw_text() -> None:
    first = NfseRejectionDetail("A001", "SEFIN", "primeira linha\nsegunda")
    second = NfseRejectionDetail("A002", "SEFIN", "outro motivo")
    result = _result(
        AuthorizationStatus.REJECTED,
        code=first.code, message=first.raw_message, details=(first, second),
    )
    assert result.normalized_rejections() == (first, second)


def test_legacy_rejection_summary_gets_deterministic_provider_origin() -> None:
    result = _result(
        AuthorizationStatus.REJECTED, code="LEGACY", message="antigo",
    )
    assert result.normalized_rejections() == (
        NfseRejectionDetail("LEGACY", "sefin-nacional-test", "antigo"),
    )


@pytest.mark.parametrize("status", [AuthorizationStatus.AUTHORIZED, AuthorizationStatus.PENDING])
def test_non_rejected_states_cannot_carry_rejection_details(
    status: AuthorizationStatus,
) -> None:
    detail = NfseRejectionDetail("A001", "SEFIN", "rejeitado")
    with pytest.raises(FiscalValidationError, match="cannot contain rejection metadata"):
        _result(status, details=(detail,))


def test_summary_and_structured_rejection_must_agree() -> None:
    detail = NfseRejectionDetail("A001", "SEFIN", "primeira")
    with pytest.raises(FiscalValidationError, match="disagrees with summary"):
        _result(
            AuthorizationStatus.REJECTED, code="A999",
            message="primeira", details=(detail,),
        )


def test_oversized_provider_text_fails_closed_without_silent_loss() -> None:
    with pytest.raises(FiscalValidationError, match="32768"):
        NfseRejectionDetail("A001", "SEFIN", "x" * 32769)


def test_unbounded_number_of_rejections_is_denied() -> None:
    detail = NfseRejectionDetail("A001", "SEFIN", "primeira")
    with pytest.raises(FiscalValidationError, match="at most 32"):
        _result(
            AuthorizationStatus.REJECTED, code=detail.code,
            message=detail.raw_message, details=(detail,) * 33,
        )
