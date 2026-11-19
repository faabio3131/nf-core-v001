"""Document-specific reviewed deductions: domain, archive and both DPS schemas."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from lxml import etree
from test_nfse_dps_builder import _certificate, _document, _issuer, _request, _service

from kordena_fiscal.domain import BrazilianJurisdiction, FiscalValidationError, Money
from kordena_fiscal.issuance.nfe_nfse import NfseDeductionDocument, NfseNationalTaxTreatment
from kordena_fiscal.issuance.nfse_archive import decode_prepared_nfse, encode_prepared_nfse
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator
from kordena_fiscal.xml.nfse_national_profiles import NT009_RESTRICTED_PROFILE, PRODUCTION_PROFILE

_NS = {"n": "http://www.sped.fazenda.gov.br/nfse"}


def _reviewed():
    issuer = _issuer()
    city = BrazilianJurisdiction("MG", "3106200")
    issuer = replace(issuer, address=replace(issuer.address, jurisdiction=city),
                     state_registration=replace(issuer.state_registration, state_code="MG"))
    item = NfseDeductionDocument(
        kind="nfse", access_key="3" * 50, legacy_code="7", nt009_code="7",
        issued_on=date(2026, 10, 1), document_total_amount=Money(Decimal("50.00")),
        eligible_amount=Money(Decimal("20.00")),
        applied_amount=Money(Decimal("10.00")), evidence_sha256="a" * 64,
    )
    decision = NfseNationalTaxTreatment(
        iss_taxation_code="1", special_regime_code="0", normative_reference="synthetic-review",
        rule_version=1, effective_from=date(2026, 1, 1), policy_id="synthetic:deduction",
        policy_sha256="b" * 64, deduction_source_type="service-order",
        deduction_source_id="order-dps-1", deduction_documents=(item,),
    )
    return replace(_document(
        issuer=issuer, services=(_service(
            national_taxation_code="070201", deduction_amount=Money(Decimal("10.00")),
        ),), tax_treatment=decision,
    ), service_jurisdiction=city)


@pytest.mark.parametrize("profile", [PRODUCTION_PROFILE, NT009_RESTRICTED_PROFILE])
def test_reviewed_deduction_round_trip_and_xml(profile):
    document = _reviewed()
    request = _request(document)
    recovered = decode_prepared_nfse(encode_prepared_nfse(request), scope=document.scope)
    assert recovered == request
    xml = build_signed_dps(recovered, _certificate(), schema_profile=profile)
    national_dps_validator("1.01", profile=profile).validate_document(xml)
    root = etree.fromstring(xml)
    if profile == PRODUCTION_PROFILE:
        assert root.findtext(".//n:docDedRed/n:chNFSe", namespaces=_NS) == "3" * 50
        assert root.findtext(".//n:docDedRed/n:vDeducaoReducao", namespaces=_NS) == "10.00"
        assert root.find(".//n:vDR", namespaces=_NS) is None
    else:
        assert root.findtext(".//n:docAjusteBC/n:dFeNacional/n:chaveDFe", namespaces=_NS) == "3" * 50
        assert root.findtext(".//n:docAjusteBC/n:vAjusteAplic", namespaces=_NS) == "10.00"
        assert root.findtext(".//n:docAjusteBC/n:vTotDoc", namespaces=_NS) == "50.00"


def test_deduction_cannot_be_replayed_for_other_source_or_amount():
    document = _reviewed()
    decision = document.national_tax_treatment
    assert decision is not None
    with pytest.raises(FiscalValidationError, match="reviewed source or value"):
        replace(document, national_tax_treatment=replace(decision, deduction_source_id="other"))
    with pytest.raises(FiscalValidationError, match="reviewed source or value"):
        replace(document, services=(replace(
            document.services[0], deduction_amount=Money(Decimal("11.00")),
        ),))
    with pytest.raises(FiscalValidationError, match="Duplicated documentary"):
        replace(decision, deduction_documents=decision.deduction_documents * 2)


def test_deduction_proof_enters_fingerprint():
    document = _reviewed()
    decision = document.national_tax_treatment
    assert decision is not None
    amended = replace(document, national_tax_treatment=replace(
        decision, deduction_documents=(replace(
            decision.deduction_documents[0], evidence_sha256="c" * 64,
        ),),
    ))
    assert _request(document).request_fingerprint != _request(amended).request_fingerprint


def test_durable_evidence_allocation_refuses_other_source_after_policy_rotation(tmp_path):
    from kordena_fiscal.application import FiscalApplicationService
    from kordena_fiscal.archive import RetentionPolicyMetadata
    from kordena_fiscal.domain import SourceReference
    from kordena_fiscal.persistence import PersistenceConflictError, SqliteFiscalDatabase

    original = replace(_reviewed(), dps_number=None)
    database = SqliteFiscalDatabase(tmp_path / "deductions.sqlite")
    database.initialize()
    application = FiscalApplicationService(database)
    retention = RetentionPolicyMetadata("deduction-test", 1)
    first = application.prepare_nfse_authorization(
        original, occurred_at=original.issued_at, retention=retention,
    )
    replay = application.prepare_nfse_authorization(
        original, occurred_at=original.issued_at, retention=retention,
    )
    assert first.request == replay.request
    decision = original.national_tax_treatment
    assert decision is not None
    other = replace(
        original, document_id="another-dps",
        source=SourceReference("service-order", "another-order"),
        national_tax_treatment=replace(
            decision, deduction_source_id="another-order", policy_sha256="f" * 64,
        ),
    )
    with pytest.raises(PersistenceConflictError, match="configuration idempotency conflict"):
        application.prepare_nfse_authorization(
            other, occurred_at=other.issued_at, retention=retention,
        )
    with database() as uow:
        assert uow.lifecycle.get(other.document_id) is None


def test_deduction_eligible_amount_cannot_exceed_original_document():
    decision = _reviewed().national_tax_treatment
    assert decision is not None
    with pytest.raises(FiscalValidationError, match="eligible or document"):
        replace(decision.deduction_documents[0], document_total_amount=Money(Decimal("9.00")))
