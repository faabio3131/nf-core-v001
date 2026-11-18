"""Real SP adapter and synthetic A1/transport; no SEFAZ is contacted."""
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from test_mg_homologation_authorization import _request
from test_mg_homologation_authorization import material as material

from kordena_fiscal.domain import ElectronicInvoiceModel
from kordena_fiscal.gateway.nfe_sp_operations_homologation import (
    OfficialNfeOperationsError,
    SefazSpHomologationOperationsGateway,
)
from kordena_fiscal.operations import (
    CancellationRequest,
    FiscalEventStatus,
    FiscalQueryRequest,
    FiscalQueryStatus,
    InutilizationRequest,
)

NS = "http://www.portalfiscal.inf.br/nfe"


def _case(operation):
    original = _request("35")
    common = {"tpAmb": "2", "nProt": "135260000000001"}
    if operation == "query":
        return (
            FiscalQueryRequest(original.scope, original.access_key),
            common | {"cUF": "35", "chNFe": original.access_key.value, "cStat": "100"},
            '<retConsSitNFe xmlns="' + NS + '">{}</retConsSitNFe>',
        )
    if operation == "cancel":
        request = CancellationRequest.build(
            scope=original.scope, access_key=original.access_key,
            authorization_protocol="135260000000002",
            justification="Cancelamento sintetico para validar correlacao",
        )
        return (
            request,
            common | {"cOrgao": "35", "chNFe": original.access_key.value,
                      "tpEvento": "110111", "nSeqEvento": "1", "cStat": "135"},
            '<retEnvEvento xmlns="' + NS + '"><retEvento><infEvento>{}'
            '</infEvento></retEvento></retEnvEvento>',
        )
    request = InutilizationRequest.build(
        scope=original.scope, model=ElectronicInvoiceModel.NFE, series=1,
        first_number=50, last_number=51,
        justification="Inutilizacao sintetica para validar correlacao",
    )
    return (
        request,
        common | {"cUF": "35", "ano": datetime.now(UTC).strftime("%y"),
                  "CNPJ": "11222333000181", "mod": "55", "serie": "1",
                  "nNFIni": "50", "nNFFin": "51", "cStat": "102"},
        '<retInutNFe xmlns="' + NS + '"><infInut>{}</infInut></retInutNFe>',
    )


def _gateway(material, fields, template):
    body = ''.join(f'<{key}>{value}</{key}>' for key, value in fields.items())
    reply = ('<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope">'
             '<Body>' + template.format(body) + '</Body></Envelope>').encode()
    exchange = Mock(return_value=reply)
    gateway = SefazSpHomologationOperationsGateway(
        resolve_certificate=Mock(return_value=material),
        resolve_issuer=Mock(return_value="11222333000181"), exchange=exchange,
    )
    return gateway, exchange


@pytest.mark.parametrize("operation", ["query", "cancel", "inutilize"])
def test_matching_sp_response_is_still_accepted(material, operation):
    request, fields, template = _case(operation)
    gateway, exchange = _gateway(material, fields, template)
    result = getattr(gateway, operation)(request)
    assert result.status is (
        FiscalQueryStatus.AUTHORIZED if operation == "query" else FiscalEventStatus.ACCEPTED
    )
    assert exchange.call_count == 1


@pytest.mark.parametrize("operation,field", [
    ("query", "cUF"), ("query", "chNFe"),
    ("cancel", "cOrgao"), ("cancel", "chNFe"),
    ("cancel", "tpEvento"), ("cancel", "nSeqEvento"),
    ("inutilize", "cUF"), ("inutilize", "ano"), ("inutilize", "CNPJ"),
    ("inutilize", "mod"), ("inutilize", "serie"),
    ("inutilize", "nNFIni"), ("inutilize", "nNFFin"),
])
@pytest.mark.parametrize("mutation", ["different", "absent", "duplicate", "nested"])
def test_sp_success_cannot_belong_to_another_document_or_range(
    material, operation, field, mutation,
):
    request, fields, template = _case(operation)
    if mutation == "different":
        fields[field] = "999"
    elif mutation == "absent":
        del fields[field]
    elif mutation == "duplicate":
        fields[field] += f"</{field}><{field}>999"
    else:
        value = fields.pop(field)
        fields["untrusted"] = f"<{field}>{value}</{field}>"
    gateway, exchange = _gateway(material, fields, template)
    with pytest.raises(OfficialNfeOperationsError, match="mismatch"):
        getattr(gateway, operation)(request)
    assert exchange.call_count == 1


@pytest.mark.parametrize("operation", ["cancel", "inutilize"])
def test_sp_rejection_may_omit_conditional_correlation_fields(material, operation):
    request, fields, template = _case(operation)
    fields = {key: value for key, value in fields.items() if key in {"tpAmb", "cUF", "cOrgao"}}
    fields.update(cStat="215", xMotivo="Falha no schema XML")
    gateway, exchange = _gateway(material, fields, template)
    result = getattr(gateway, operation)(request)
    assert result.status is FiscalEventStatus.REJECTED
    assert result.rejection_code == "215"
    assert result.event_protocol_reference is None
    assert exchange.call_count == 1


@pytest.mark.parametrize("operation,field", [("cancel", "chNFe"), ("inutilize", "CNPJ")])
def test_sp_rejection_cannot_claim_another_document(material, operation, field):
    request, fields, template = _case(operation)
    fields.update(cStat="215", xMotivo="Falha no schema XML")
    fields[field] = "999"
    gateway, _ = _gateway(material, fields, template)
    with pytest.raises(OfficialNfeOperationsError, match="correlation mismatch"):
        getattr(gateway, operation)(request)
