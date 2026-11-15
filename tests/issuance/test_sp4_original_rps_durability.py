"""SP4 original RPS / batch share one canonical numbering UoW.

Tests are entirely offline and use synthetic fiscal identifiers. They
exercise all four municipal paths without an A1 or municipal endpoint.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4ProviderOutcome,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
)
from kordena_fiscal.issuance.sp4_original_rps_archive import (
    build_sp4_original_from_reservation,
    decode_sp4_original,
    encode_sp4_original,
    expected_sp4_batch,
)
from kordena_fiscal.persistence.ports import (
    PersistenceConflictError,
    PersistenceStateError,
)
from kordena_fiscal.persistence.sqlite import SqliteFiscalDatabase
from kordena_fiscal.runtime.sp4_municipal_canonical_composition import (
    Sp4ReviewedMunicipalPorts,
    build_sp4_canonical_clients,
)

_NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
_POLICY = RetentionPolicyMetadata("nfcore-fiscal-archive", 1)
_CNPJ = Cnpj("11222333000181")


def _request(ibge: str, identifier: str = "one", *, tenant: str = "tenant-sp4",
             unit: str = "unit-a") -> NfseAuthorizationRequest:
    scope = ExecutionScope(
        tenant_id=tenant, unit_id=unit, host_namespace="nfcore",
        environment=FiscalEnvironment.HOMOLOGATION,
        correlation_id="sp4-" + identifier,
    )
    city = BrazilianJurisdiction("SP", ibge)
    issuer = FiscalProfile(
        profile_id="issuer-" + identifier, scope=scope,
        cnpj=_CNPJ, legal_name="Emissor sintetico de servicos",
        tax_regime=TaxRegimeCode.NORMAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("6201501"),
        address=FiscalAddress(
            street="Rua Sintetica", number="100", district="Centro",
            municipality_name="Municipio SP4", jurisdiction=city,
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    doc = NfseCanonicalDocument(
        document_id="sp4-document-" + identifier, scope=scope,
        source=SourceReference("service-order", "sp4-order-" + identifier),
        issued_at=_NOW, competence_date=date(2026, 11, 12),
        issuer=issuer, service_jurisdiction=city,
        services=(NfseServiceLine(
            line_number=1, municipal_service_code="0107",
            national_taxation_code="010701",
            description="Servico sintetico revisado",
            gross_amount=Money(Decimal("150.00")),
            iss_amount=Money(Decimal("3.00")),
            source_normative="urn:nfcore:synthetic:sp4-2026",
        ),),
    )
    return NfseAuthorizationRequest.build(doc)


def _prepare(app: FiscalApplicationService, request: NfseAuthorizationRequest,
             series: int = 1):
    result = app.prepare_nfse_authorization(
        request.document, occurred_at=_NOW, retention=_POLICY,
        sp4_rps_series=series,
        sp4_intent_builder=lambda reserved: build_sp4_original_from_reservation(
            request, reserved, rps_series="NF",
        ),
    )
    return result, app.load_sp4_original_rps(
        request.document.scope, request.document.document_id,
    )


@pytest.mark.parametrize("ibge", sorted(SP4_MUNICIPAL_PROVIDERS.values()))
def test_all_four_municipalities_archive_one_original_rps_in_same_transaction(
    tmp_path: Path, ibge: str,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / (ibge + ".sqlite"))
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request(ibge)
    first, original = _prepare(app, request)
    assert first.replay is False
    assert original.rps_number == "1"
    assert original.municipal_batch_id == expected_sp4_batch(ibge, 1)
    assert original.issuer_ibge == ibge
    assert original.request_fingerprint == request.request_fingerprint
    assert original.gross_amount == Decimal("150.00")

    restarted = FiscalApplicationService(SqliteFiscalDatabase(db.path))
    assert restarted.load_sp4_original_rps(
        request.document.scope, request.document.document_id,
    ) == original
    replay = restarted.prepare_nfse_authorization(
        request.document, occurred_at=_NOW, retention=_POLICY,
        sp4_rps_series=1,
        sp4_intent_builder=lambda _: pytest.fail(
            "idempotent replay must not reserve a second municipal number"
        ),
    )
    assert replay.replay is True
    assert restarted.load_sp4_original_rps(
        request.document.scope, request.document.document_id,
    ) == original
    second_request = _request(ibge, "two")
    _, second = _prepare(restarted, second_request)
    assert second.rps_number == "2"
    assert second.municipal_batch_id == expected_sp4_batch(ibge, 2)
    assert second.document_id != original.document_id


def test_replay_cannot_remove_or_add_original_rps_authority(tmp_path: Path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "replay.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3509205")
    _prepare(app, request)
    with pytest.raises(PersistenceConflictError, match="SP4 original RPS"):
        app.prepare_nfse_authorization(
            request.document, occurred_at=_NOW, retention=_POLICY,
        )


def test_other_tenant_or_unit_cannot_load_original_sp4_rps(tmp_path: Path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "scope.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3505708")
    _prepare(app, request)
    for changed_scope in (
        replace(request.document.scope, tenant_id="other-tenant"),
        replace(request.document.scope, unit_id="other-unit"),
    ):
        with pytest.raises((PersistenceConflictError, PersistenceStateError)):
            app.load_sp4_original_rps(
                changed_scope, request.document.document_id,
            )


def test_original_archive_token_and_amount_tampering_rejected(tmp_path: Path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "tamper.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3525904")
    _, original = _prepare(app, request)
    from kordena_fiscal.numbering import (
        FiscalNumberReservation,
        FiscalSequenceKey,
        InternalFiscalSequenceStream,
    )
    key = FiscalSequenceKey.from_scope(
        request.document.scope,
        model=InternalFiscalSequenceStream.NFSE_RPS, series=1,
    )
    reserved = FiscalNumberReservation(
        key=key, number=int(original.rps_number),
        reservation_token=__import__("hashlib").sha256(
            f"{key.canonical_material}|{original.rps_number}".encode(),
        ).hexdigest(),
    )
    valid = encode_sp4_original(request, original, reserved)
    assert decode_sp4_original(
        valid, scope=request.document.scope, request=request,
    ) == original
    for field, edited in (
        ("issuer_ibge", "3509205"),
        ("rps_number", "8"),
        ("gross_amount", "151.00"),
    ):
        payload = json.loads(valid)
        payload[field] = edited
        with pytest.raises(FiscalValidationError, match="altered|diverge"):
            decode_sp4_original(
                json.dumps(payload).encode(),
                scope=request.document.scope, request=request,
            )
    payload = json.loads(valid)
    payload["sequence"]["token"] = "0" * 64
    with pytest.raises(FiscalValidationError, match="altered"):
        decode_sp4_original(
            json.dumps(payload).encode(),
            scope=request.document.scope, request=request,
        )


def test_bad_reviewed_source_rolls_back_rps_reservation(tmp_path: Path) -> None:
    db = SqliteFiscalDatabase(tmp_path / "rollback.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3534401")

    def wrong_builder(reserved):
        return replace(
            build_sp4_original_from_reservation(
                request, reserved, rps_series="NF",
            ),
            issuer_ibge="3525904",
        )

    with pytest.raises(FiscalValidationError, match="diverge"):
        app.prepare_nfse_authorization(
            request.document, occurred_at=_NOW, retention=_POLICY,
            sp4_rps_series=1, sp4_intent_builder=wrong_builder,
        )
    _, approved = _prepare(app, request)
    assert approved.rps_number == "1"


@pytest.mark.parametrize("provider,ibge", sorted(SP4_MUNICIPAL_PROVIDERS.items()))
def test_four_real_canonical_gateway_clients_load_original_from_same_app_uow(
    tmp_path: Path, provider: str, ibge: str,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / (ibge + "-gateway.sqlite"))
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request(ibge)
    _, reserved_source = _prepare(app, request)
    legacy_loader = Mock(side_effect=AssertionError("parallel RPS authority used"))
    submit = Mock(return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING))
    resolver = Mock()
    resolver.resolve_provider_id.return_value = provider
    ports = Sp4ReviewedMunicipalPorts(
        load_original_rps=legacy_loader,
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        submit_official_rps=submit,
        query_official_rps=Mock(
            return_value=Sp4ProviderOutcome(status=AuthorizationStatus.PENDING),
        ),
        verify_official_invoice_xml=Mock(),
    )
    issue, query = build_sp4_canonical_clients(
        canonical_resolver=resolver,
        configured_municipalities={provider: ports},
        canonical_rps_loader=app.load_sp4_original_rps,
    )
    result = issue[provider].authorize(request)
    assert result.status is AuthorizationStatus.PENDING
    submit.assert_called_once_with(request, reserved_source)
    legacy_loader.assert_not_called()
    assert query[provider].query(request).status is AuthorizationStatus.PENDING
    legacy_loader.assert_not_called()
