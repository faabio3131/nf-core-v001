"""Cajamar immutable original RPS archive: isolated offline contract tests."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

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
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    InternalFiscalSequenceStream,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError, PersistenceStateError

_NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
_CNPJ = Cnpj("11222333000181")

def _request(ibge: str, identifier: str = "one", *, tenant: str = "tenant-cajamar",
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



def _reservation(request: NfseAuthorizationRequest, number: int = 42) -> FiscalNumberReservation:
    key = FiscalSequenceKey.from_scope(
        request.document.scope, model=InternalFiscalSequenceStream.NFSE_RPS,
        series=1,
    )
    token = hashlib.sha256(
        f"{key.canonical_material}|{number}".encode(),
    ).hexdigest()
    return FiscalNumberReservation(key=key, number=number, reservation_token=token)


def test_cajamar_rps_sequence_lot_archive_and_replay_are_stable() -> None:
    request = _request("3509205")
    first = _reservation(request)
    original = build_sp4_original_from_reservation(request, first, rps_series="NF")
    assert original.rps_number == "42"
    assert original.municipal_batch_id == expected_sp4_batch("3509205", 42)
    raw = encode_sp4_original(request, original, first)
    assert decode_sp4_original(raw, scope=request.document.scope, request=request) == original
    assert encode_sp4_original(request, original, first) == raw


@pytest.mark.parametrize("field,value", [
    ("issuer_ibge", "3534401"),
    ("rps_number", "43"),
    ("gross_amount", "151.00"),
    ("municipal_batch_id", "999"),
])
def test_cajamar_rps_tamper_never_returns_original(field: str, value: str) -> None:
    request = _request("3509205")
    reservation = _reservation(request)
    original = build_sp4_original_from_reservation(request, reservation, rps_series="NF")
    evidence = json.loads(encode_sp4_original(request, original, reservation))
    evidence[field] = value
    with pytest.raises(FiscalValidationError, match="altered|diverge"):
        decode_sp4_original(
            json.dumps(evidence).encode(), scope=request.document.scope, request=request,
        )


def test_cajamar_other_tenant_and_unit_cannot_reuse_original_archive() -> None:
    request = _request("3509205")
    reservation = _reservation(request)
    original = build_sp4_original_from_reservation(request, reservation, rps_series="NF")
    raw = encode_sp4_original(request, original, reservation)
    for scope in (
        replace(request.document.scope, tenant_id="another-tenant"),
        replace(request.document.scope, unit_id="another-unit"),
    ):
        with pytest.raises(FiscalValidationError):
            decode_sp4_original(raw, scope=scope, request=request)


def test_cajamar_numbering_limit_keeps_durable_RPS_in_bounds() -> None:
    assert expected_sp4_batch("3509205", 99_999_999) == "99999999"
    with pytest.raises(FiscalValidationError, match="exceeds"):
        expected_sp4_batch("3509205", 100_000_000)

def test_cajamar_same_tenant_and_unit_cannot_exchange_issuer_cnpj() -> None:
    """A different issuer CNPJ in the same unit cannot consume another original RPS."""
    request = _request("3509205")
    reservation = _reservation(request)
    original = build_sp4_original_from_reservation(request, reservation, rps_series="NF")
    raw = encode_sp4_original(request, original, reservation)

    other_issuer = replace(request.document.issuer, cnpj=Cnpj("22333444000181"))
    another_document = replace(request.document, issuer=other_issuer)
    another_request = NfseAuthorizationRequest.build(another_document)

    assert another_request.document.scope == request.document.scope
    assert another_request.document.issuer.cnpj != request.document.issuer.cnpj
    with pytest.raises(FiscalValidationError, match="altered|diverge"):
        decode_sp4_original(
            raw, scope=request.document.scope, request=another_request,
        )


def _prepare_cajamar(
    app: FiscalApplicationService,
    request: NfseAuthorizationRequest,
    *,
    builder=None,
):
    def original_builder(
        prepared: NfseAuthorizationRequest,
        number: FiscalNumberReservation,
    ):
        return build_sp4_original_from_reservation(
            prepared, number, rps_series="NF",
        )

    return app.prepare_nfse_authorization(
        request.document, occurred_at=_NOW,
        retention=RetentionPolicyMetadata("cajamar-internal-proof", 1),
        sp4_original_builder=builder if builder is not None else original_builder,
        sp4_rps_series=1,
    )


def test_cajamar_application_commits_original_rps_and_prepared_in_one_uow(
    tmp_path,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / "cajamar-prepare.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3509205")
    prepared = _prepare_cajamar(app, request)
    assert prepared.replay is False
    assert prepared.request.document.dps_number is None
    original = app.load_sp4_original_rps(request.document.scope, request.document.document_id)
    assert original.rps_number == "1"
    assert original.rps_series == "NF"
    assert original.municipal_batch_id == "1"
    assert original.issuer_cnpj == request.document.issuer.cnpj
    assert original.request_fingerprint == prepared.request.request_fingerprint
    assert app.load_prepared_nfse_authorization(
        request.document.scope, request.document.document_id,
    ) == prepared.request
    with db() as uow:
        archive = uow.archive.list_for_document(
            request.document.scope, request.document.document_id,
        )
    assert len(archive) == 2, "one canonical NFS-e request and one original RPS"


def test_cajamar_application_replay_never_reserves_next_rps_or_calls_builder_twice(
    tmp_path,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / "cajamar-replay.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3509205")
    invoked = []

    def builder(prepared, reservation):
        invoked.append(reservation.number)
        return build_sp4_original_from_reservation(
            prepared, reservation, rps_series="NF",
        )

    first = _prepare_cajamar(app, request, builder=builder)
    again = _prepare_cajamar(app, request, builder=builder)
    assert not first.replay and again.replay
    assert invoked == [1]
    assert first.request == again.request
    second = _request("3509205", identifier="second")
    prepared_second = _prepare_cajamar(app, second, builder=builder)
    original_second = app.load_sp4_original_rps(
        second.document.scope, second.document.document_id,
    )
    assert prepared_second.replay is False
    assert original_second.rps_number == "2"
    assert invoked == [1, 2]


def test_cajamar_application_rollback_never_consumes_failed_original_rps(
    tmp_path,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / "cajamar-rollback.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3509205")

    def failing_builder(prepared, reservation):
        raise FiscalValidationError("Synthetic validation failure before commit")

    with pytest.raises(FiscalValidationError, match="before commit"):
        _prepare_cajamar(app, request, builder=failing_builder)
    with pytest.raises((PersistenceConflictError, PersistenceStateError, FiscalValidationError)):
        app.load_prepared_nfse_authorization(
            request.document.scope, request.document.document_id,
        )
    first = _prepare_cajamar(app, request)
    assert first.replay is False
    assert app.load_sp4_original_rps(
        request.document.scope, request.document.document_id,
    ).rps_number == "1"


def test_cajamar_application_loader_cannot_leak_original_to_other_scope(
    tmp_path,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / "cajamar-isolation.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3509205")
    _prepare_cajamar(app, request)
    for scope in (
        replace(request.document.scope, tenant_id="other-tenant"),
        replace(request.document.scope, unit_id="other-unit"),
        replace(request.document.scope, environment=FiscalEnvironment.PRODUCTION),
    ):
        with pytest.raises((
            PersistenceConflictError, PersistenceStateError, FiscalValidationError,
        )):
            app.load_sp4_original_rps(scope, request.document.document_id)


def test_cajamar_application_rejects_parallel_extrema_and_municipal_numbering(
    tmp_path,
) -> None:
    db = SqliteFiscalDatabase(tmp_path / "cajamar-exclusive.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    request = _request("3509205")
    with pytest.raises(FiscalValidationError, match="exclusive"):
        app.prepare_nfse_authorization(
            request.document, occurred_at=_NOW,
            retention=RetentionPolicyMetadata("cajamar-internal-proof", 1),
            extrema_intent_builder=lambda _r: None, extrema_rps_series=1,
            sp4_original_builder=lambda _p, _r: None, sp4_rps_series=1,
        )
