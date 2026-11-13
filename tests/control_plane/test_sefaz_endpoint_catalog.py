"""Exact endpoint discovery and isolation from provider selection."""
from urllib.parse import urlsplit

import pytest

from kordena_fiscal.control_plane.sefaz_endpoint_catalog import SefazService, resolve_sefaz_endpoint
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
)


@pytest.mark.parametrize("ibge,uf,authorizer,city", [
    ("35", "SP", "SP", "3550308"), ("31", "MG", "MG", "3106200"),
    ("33", "RJ", "SVRS", "3304557"), ("41", "PR", "PR", "4106902"),
    ("51", "MT", "MT", "5103403"), ("50", "MS", "MS", "5002704"),
])
@pytest.mark.parametrize("family", [FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE])
def test_complete_priority_matrix_is_exact(ibge, uf, authorizer, city, family):
    for service in SefazService:
        endpoints = [
            resolve_sefaz_endpoint(
                state_ibge_code=ibge, document_kind=family, environment=environment,
                service=service, jurisdiction=BrazilianJurisdiction(uf, city),
            )
            for environment in FiscalEnvironment
        ]
        assert endpoints[0].url != endpoints[1].url
        for endpoint, environment in zip(endpoints, FiscalEnvironment, strict=True):
            assert (endpoint.uf, endpoint.authorizer) == (uf, authorizer)
            assert endpoint.protocol_version == "4.00"
            assert (endpoint.document_kind, endpoint.environment, endpoint.service) == (
                family, environment, service,
            )
            assert urlsplit(endpoint.url).scheme == "https"


@pytest.mark.parametrize("ibge,kind,jurisdiction", [
    ("33", FiscalDocumentKind.NFE, BrazilianJurisdiction("SP", "3550308")),
    ("33", FiscalDocumentKind.NFE, BrazilianJurisdiction("RJ", "3550308")),
    ("33", FiscalDocumentKind.NFSE, BrazilianJurisdiction("RJ", "3304557")),
    ("43", FiscalDocumentKind.NFE, None),
    ("3304557", FiscalDocumentKind.NFE, None),
])
def test_invalid_coordinates_do_not_fallback(ibge, kind, jurisdiction):
    with pytest.raises(FiscalValidationError):
        resolve_sefaz_endpoint(
            state_ibge_code=ibge, document_kind=kind, environment=FiscalEnvironment.HOMOLOGATION,
            service=SefazService.AUTHORIZE, jurisdiction=jurisdiction,
        )


@pytest.mark.parametrize("ibge,family,service,tail", [
    ("33", FiscalDocumentKind.NFE, SefazService.QUERY, "/ws/NfeConsulta/NfeConsulta4.asmx"),
    ("51", FiscalDocumentKind.NFCE, SefazService.CANCEL, "/nfcews/services/RecepcaoEvento4"),
    ("35", FiscalDocumentKind.NFE, SefazService.RECEIPT, "/ws/nferetautorizacao4.asmx"),
    ("50", FiscalDocumentKind.NFCE, SefazService.RECEIPT, "/ws/NFeRetAutorizacao4"),
])
def test_service_paths_retain_authorizer_specific_spelling(ibge, family, service, tail):
    route = resolve_sefaz_endpoint(
        state_ibge_code=ibge, document_kind=family, environment=FiscalEnvironment.HOMOLOGATION,
        service=service,
    )
    assert urlsplit(route.url).path == tail



@pytest.mark.parametrize("document_kind,official_source,expected_host", [
    (
        FiscalDocumentKind.NFE,
        "https://portal.fazenda.sp.gov.br/servicos/nfe/Paginas/URL-WEBSERVICES.aspx",
        "homologacao.nfe.fazenda.sp.gov.br",
    ),
    (
        FiscalDocumentKind.NFCE,
        "https://portal.fazenda.sp.gov.br/servicos/nfce/Paginas/WebServices.aspx",
        "homologacao.nfce.fazenda.sp.gov.br",
    ),
])
@pytest.mark.parametrize("operation", [
    SefazService.AUTHORIZE, SefazService.QUERY, SefazService.CANCEL,
    SefazService.STATUS, SefazService.RECEIPT,
])
def test_sp55_sp65_must_use_respective_sefaz_sp_sources_not_svrs(
    document_kind: FiscalDocumentKind, official_source: str,
    expected_host: str, operation: SefazService,
) -> None:
    route = resolve_sefaz_endpoint(
        state_ibge_code="35",
        document_kind=document_kind,
        environment=FiscalEnvironment.HOMOLOGATION,
        service=operation,
        jurisdiction=BrazilianJurisdiction("SP", "3550308"),
    )
    assert route.source_url == official_source
    assert urlsplit(route.url).hostname == expected_host
    assert route.authorizer == "SP"
