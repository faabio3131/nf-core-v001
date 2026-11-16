"""PR440 cTribMun reconciled into the existing line, fingerprint and archive."""
from dataclasses import replace

import pytest
from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.issuance.nfse_archive import decode_prepared_nfse, encode_prepared_nfse
from kordena_fiscal.issuance.nfse_dps_builder import build_signed_dps
from kordena_fiscal.xml.nfse_national_profiles import NT009_RESTRICTED_PROFILE, PRODUCTION_PROFILE
from test_nfse_dps_builder import _certificate, _document, _request, _service

NS = {"n": "http://www.sped.fazenda.gov.br/nfse"}


@pytest.mark.parametrize("value", ["12", "1234", "ABC", "１２３", 123, " 123", ""])
def test_municipal_detail_requires_exact_reviewed_three_digit_code(value):
    with pytest.raises(FiscalValidationError, match="cTribMun"):
        _service(municipal_taxation_detail=value)


@pytest.mark.parametrize("profile", [PRODUCTION_PROFILE, NT009_RESTRICTED_PROFILE])
def test_reviewed_municipal_detail_uses_official_order_in_both_layouts(profile):
    document = _document(services=(_service(
        municipal_taxation_detail="001", nbs_code="115021000",
    ),))
    xml = build_signed_dps(_request(document), _certificate(), schema_profile=profile)
    service = etree.fromstring(xml).find("n:infDPS/n:serv/n:cServ", NS)
    assert [etree.QName(child).localname for child in service][:2] == ["cTribNac", "cTribMun"]
    assert service.findtext("n:cTribMun", namespaces=NS) == "001"
    assert service.findtext("n:cNBS", namespaces=NS) == "115021000"


def test_detail_roundtrips_and_is_bound_to_fingerprint_without_breaking_legacy():
    old = _request()
    legacy = encode_prepared_nfse(old)
    assert b"municipal_taxation_detail" not in legacy
    assert decode_prepared_nfse(legacy, scope=old.document.scope) == old
    document = replace(old.document, services=(replace(
        old.document.services[0], municipal_taxation_detail="001",
    ),))
    reviewed = _request(document)
    assert reviewed.request_fingerprint != old.request_fingerprint
    encoded = encode_prepared_nfse(reviewed)
    assert decode_prepared_nfse(encoded, scope=document.scope) == reviewed
    with pytest.raises(FiscalValidationError):
        decode_prepared_nfse(encoded.replace(b'"001"', b'"002"'), scope=document.scope)
