"""Environment selection and unmodified primary-source NT009 schema checks."""
import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from importlib.resources import files

import pytest
from lxml import etree

from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError, Money
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.xml.nfse_nacional_schema import national_dps_validator
from kordena_fiscal.xml.nfse_national_profiles import (
    NT009_OFFICIAL_HASHES,
    NT009_RESTRICTED_PROFILE,
    PRODUCTION_PROFILE,
    national_restricted_validator,
    select_national_dps_profile,
)
from kordena_fiscal.xml.schema import XmlSchemaValidationError
from test_nfse_dps_builder import _certificate, _document, _request, _service

NS = {"n": "http://www.sped.fazenda.gov.br/nfse"}


@pytest.mark.parametrize("environment,day,expected", [
    (FiscalEnvironment.HOMOLOGATION, date(2026, 10, 19), PRODUCTION_PROFILE),
    (FiscalEnvironment.HOMOLOGATION, date(2026, 10, 20), NT009_RESTRICTED_PROFILE),
    (FiscalEnvironment.PRODUCTION, date(2026, 11, 16), PRODUCTION_PROFILE),
])
def test_profile_is_selected_by_environment_and_effective_date(environment, day, expected):
    assert select_national_dps_profile(
        environment=environment, schema_version="1.01", effective_on=day,
    ) == expected


def test_unreviewed_production_cutover_and_versions_are_rejected():
    with pytest.raises(FiscalValidationError, match="cutover"):
        select_national_dps_profile(
            environment=FiscalEnvironment.PRODUCTION, schema_version="1.01",
            effective_on=date(2026, 12, 1),
        )
    with pytest.raises(FiscalValidationError):
        select_national_dps_profile(
            environment=FiscalEnvironment.HOMOLOGATION, schema_version="1.00",
            effective_on=date(2026, 11, 16),
        )


def test_official_package_has_reproducible_hashes_and_all_roots_compile():
    directory = files("kordena_fiscal.xml").joinpath(
        "official", "NFSE_NACIONAL_1.01_NT009_20261020",
    )
    manifest = json.loads(directory.joinpath("manifest.json").read_bytes())
    assert manifest["files"] == NT009_OFFICIAL_HASHES
    for name, digest in NT009_OFFICIAL_HASHES.items():
        assert hashlib.sha256(directory.joinpath(name).read_bytes()).hexdigest() == digest
    for root in ("DPS_v1.01.xsd", "NFSe_v1.01.xsd", "evento_v1.01.xsd", "pedRegEvento_v1.01.xsd"):
        assert national_restricted_validator(root)


@pytest.mark.parametrize("city,state", [("3550308", "SP"), ("3106200", "MG")])
def test_same_national_layout_applies_beyond_one_municipality(city, state):
    from kordena_fiscal.domain import BrazilianJurisdiction
    document = _document(services=(_service(
        nbs_code="115021000", deduction_amount=Money(Decimal("10.00")),
    ),))
    jurisdiction = BrazilianJurisdiction(state, city)
    issuer = replace(document.issuer, state_registration=replace(
        document.issuer.state_registration, state_code=state,
    ), address=replace(
        document.issuer.address, jurisdiction=jurisdiction,
    ))
    document = replace(document, issuer=issuer, service_jurisdiction=jurisdiction)
    signed = build_signed_dps(
        _request(document), _certificate(), schema_profile=NT009_RESTRICTED_PROFILE,
    )
    national_restricted_validator("DPS_v1.01.xsd").validate_document(signed)
    root = etree.fromstring(signed)
    assert root.findtext("n:infDPS/n:finNFSe", namespaces=NS) == "0"
    service = root.find("n:infDPS/n:serv/n:cServ", NS)
    assert [etree.QName(child).localname for child in service] == [
        "cTribNac", "cNBS", "xDescServ",
    ]
    assert root.findtext(
        "n:infDPS/n:valores/n:vAjusteBC/n:vAjusteBCISSQN", namespaces=NS,
    ) == "10.00"
    with pytest.raises(XmlSchemaValidationError):
        national_dps_validator("1.01").validate_document(signed)


def test_legacy_municipal_builder_does_not_inherit_national_cutover():
    signed = build_signed_dps(_request(), _certificate())
    national_dps_validator("1.01").validate_document(signed)
    assert etree.fromstring(signed).find("n:infDPS/n:finNFSe", NS) is None
    with pytest.raises(XmlSchemaValidationError):
        national_restricted_validator("DPS_v1.01.xsd").validate_document(signed)


@pytest.mark.parametrize("series,accepted", [(89999, True), (90000, False)])
def test_nt009_series_boundary_preserves_legacy_municipal_contract(series, accepted):
    from kordena_fiscal.issuance.nfse_dps_builder import validate_sefin_dps_input
    document = replace(_document(), dps_series=series)
    # Legacy municipal DPS still has its own five-digit series contract.
    national_dps_validator("1.01").validate_document(
        build_signed_dps(_request(document), _certificate()),
    )
    if accepted:
        assert validate_sefin_dps_input(document) == NT009_RESTRICTED_PROFILE
    else:
        with pytest.raises(FiscalValidationError, match="series"):
            validate_sefin_dps_input(document)


def test_invalid_series_does_not_claim_transmission_or_access_a1(tmp_path):
    from unittest.mock import Mock

    from kordena_fiscal.application import FiscalApplicationService
    from kordena_fiscal.gateway.nfse_nacional_homologation import NfseNacionalHomologationGateway
    from kordena_fiscal.issuance.nfe_nfse import NfseGatewayClient
    from kordena_fiscal.lifecycle import FiscalDocumentState
    from kordena_fiscal.persistence import SqliteFiscalDatabase
    from kordena_fiscal.archive import RetentionPolicyMetadata

    db = SqliteFiscalDatabase(tmp_path / "profile-series.sqlite")
    db.initialize()
    app = FiscalApplicationService(db)
    document = replace(_document(), dps_number=None, dps_series=90000)
    scope = replace(document.scope, host_namespace="nfcore")
    document = replace(document, scope=scope, issuer=replace(document.issuer, scope=scope))
    now = document.issued_at
    retention = RetentionPolicyMetadata("profile-series-test", 1)
    prepared = app.prepare_nfse_authorization(document, occurred_at=now, retention=retention)
    certificate, builder, exchange = Mock(), Mock(), Mock()
    gateway = NfseNacionalHomologationGateway(
        resolve_certificate=certificate, build_signed_dps=builder, exchange=exchange,
    )
    with pytest.raises(FiscalValidationError, match="series"):
        app.authorize_prepared_document(
            document_id=document.document_id, request=prepared.request,
            gateway=NfseGatewayClient(gateway), occurred_at=now,
        )
    with db() as uow:
        state = uow.lifecycle.get(document.document_id)
        assert state is not None and state.state is FiscalDocumentState.READY_TO_TRANSMIT
    certificate.assert_not_called()
    builder.assert_not_called()
    exchange.assert_not_called()


def test_low_level_transport_rejects_legacy_layout_before_network():
    from unittest.mock import Mock

    from kordena_fiscal.gateway.nfse_national_homologation import NfseNationalHomologationTransport

    certificate = _certificate()
    legacy = build_signed_dps(_request(), certificate)
    exchange = Mock()
    transport = NfseNationalHomologationTransport(certificate=certificate, exchange=exchange)
    with pytest.raises(XmlSchemaValidationError):
        transport.submit_signed_dps(legacy)
    exchange.assert_not_called()
