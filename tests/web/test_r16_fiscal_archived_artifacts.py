"""Scoped archive access: never fabricate XML or DANFE."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import HTTPException

from kordena_fiscal.archive import (
    FiscalArchiveEntry,
    FiscalArchiveKind,
    InMemoryFiscalArchiveStore,
    RetentionPolicyMetadata,
)
from kordena_fiscal.domain import ExecutionScope, FiscalEnvironment
from kordena_fiscal.persistence.ports import FiscalUnitOfWorkFactory
from kordena_fiscal.security.human_identity import AuthenticatedHuman, PortalPermission
from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor


class _Authorized:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def assert_permission(self, permission: PortalPermission, *, unit_id: str) -> None:
        assert permission is PortalPermission.DOCUMENT_QUERY
        assert unit_id == "unit-a"


class _Uow:
    def __init__(self, archive: InMemoryFiscalArchiveStore) -> None:
        self.archive = archive

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def test_xml_danfe_and_tenant_isolation() -> None:
    scope = ExecutionScope(
        host_namespace="fm-nfcore", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="test",
    )
    archive = InMemoryFiscalArchiveStore()
    archive.append(FiscalArchiveEntry.build(
        scope=scope, document_reference="NF-123",
        kind=FiscalArchiveKind.AUTHORIZED_XML,
        content=b"<nfeProc/>", media_type="application/xml",
        archived_at=datetime.now(UTC),
        retention=RetentionPolicyMetadata(policy_id="test", policy_version=1),
    ))
    executor = DurableHumanPortalExecutor(
        cast(FiscalUnitOfWorkFactory, lambda: _Uow(archive))
    )

    def read(tenant: str, kind: FiscalArchiveKind) -> tuple[bytes, str]:
        return executor.fiscal_artifact(
            authority=cast(AuthenticatedHuman, _Authorized(tenant)),
            unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
            document_reference="NF-123", kind=kind,
        )

    assert read("tenant-a", FiscalArchiveKind.AUTHORIZED_XML) == (
        b"<nfeProc/>", "application/xml"
    )
    with pytest.raises(HTTPException) as different_tenant:
        read("tenant-b", FiscalArchiveKind.AUTHORIZED_XML)
    assert different_tenant.value.status_code == 404
    with pytest.raises(HTTPException) as not_archived:
        read("tenant-a", FiscalArchiveKind.DANFE)
    assert not_archived.value.status_code == 404
    with pytest.raises(HTTPException) as forbidden_kind:
        read("tenant-a", FiscalArchiveKind.OTHER)
    assert forbidden_kind.value.status_code == 400


def test_danfe_is_rendered_only_after_scoped_authorized_xml_lookup() -> None:
    scope = ExecutionScope(
        host_namespace="fm-nfcore", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="pdf-test",
    )
    archive = InMemoryFiscalArchiveStore()
    xml = b"<nfeProc xmlns='http://www.portalfiscal.inf.br/nfe' versao='4.00'/>"
    archive.append(FiscalArchiveEntry.build(
        scope=scope, document_reference="NF-123",
        kind=FiscalArchiveKind.AUTHORIZED_XML,
        content=xml, media_type="application/xml",
        archived_at=datetime.now(UTC),
        retention=RetentionPolicyMetadata(policy_id="test", policy_version=1),
    ))
    observed: list[bytes] = []

    def mock_renderer(document: bytes) -> bytes:
        observed.append(document)
        return b"%PDF-1.7\\nNFCore test"

    executor = DurableHumanPortalExecutor(
        cast(FiscalUnitOfWorkFactory, lambda: _Uow(archive)),
        danfe_renderer=mock_renderer,
    )

    def render(tenant: str) -> tuple[bytes, str]:
        return executor.fiscal_artifact(
            authority=cast(AuthenticatedHuman, _Authorized(tenant)),
            unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
            document_reference="NF-123", kind=FiscalArchiveKind.DANFE,
        )

    assert render("tenant-a") == (b"%PDF-1.7\\nNFCore test", "application/pdf")
    assert observed == [xml]
    with pytest.raises(HTTPException) as foreign:
        render("different-tenant")
    assert foreign.value.status_code == 404
    assert observed == [xml]


def test_legacy_danfe_never_renders_national_nfse_and_unified_path_uses_danfse() -> None:
    scope = ExecutionScope(
        host_namespace="fm-nfcore", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="nfse-pdf",
    )
    archive = InMemoryFiscalArchiveStore()
    key = "35" + "0" * 48
    xml = (
        f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">'
        f'<infNFSe Id="NFS{key}"/></NFSe>'
    ).encode()
    archive.append(FiscalArchiveEntry.build(
        scope=scope, document_reference="NFSE-123",
        kind=FiscalArchiveKind.AUTHORIZED_XML, content=xml, media_type="application/xml",
        archived_at=datetime.now(UTC),
        retention=RetentionPolicyMetadata(policy_id="test", policy_version=1),
    ))
    rendered: list[str] = []
    executor = DurableHumanPortalExecutor(
        cast(FiscalUnitOfWorkFactory, lambda: _Uow(archive)),
        danfe_renderer=lambda _xml: rendered.append("danfe") or b"%PDF-1.7\nWRONG",
        danfse_renderer=lambda _xml: rendered.append("danfse") or b"%PDF-1.7\nRIGHT",
    )

    def read(kind: FiscalArchiveKind) -> tuple[bytes, str]:
        return executor.fiscal_artifact(
            authority=cast(AuthenticatedHuman, _Authorized("tenant-a")),
            unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
            document_reference="NFSE-123", kind=kind,
        )

    with pytest.raises(HTTPException) as forbidden:
        read(FiscalArchiveKind.DANFE)
    assert forbidden.value.status_code == 409
    assert rendered == []
    assert read(FiscalArchiveKind.AUXILIARY_PDF) == (
        b"%PDF-1.7\nRIGHT", "application/pdf",
    )
    assert rendered == ["danfse"]


def test_nfce_uses_model65_danfce_only_on_authorized_scoped_xml() -> None:
    from kordena_fiscal.web.portal_runtime import _printable_authorized_xml

    scope = ExecutionScope(
        host_namespace="fm-nfcore", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="nfce-pdf",
    )
    key = "3" * 44
    xml = (
        '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        f'<NFe><infNFe Id="NFe{key}"><ide><mod>65</mod>'
        '<tpAmb>2</tpAmb></ide></infNFe>'
        f'<infNFeSupl><qrCode>https://sefaz.example/nfce?p={key}</qrCode></infNFeSupl>'
        '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignedInfo/></Signature>'
        '</NFe><protNFe><infProt>'
        f'<chNFe>{key}</chNFe><tpAmb>2</tpAmb><cStat>100</cStat>'
        '<nProt>123456789</nProt></infProt></protNFe></nfeProc>'
    ).encode()
    archive = InMemoryFiscalArchiveStore()
    entry = FiscalArchiveEntry.build(
        scope=scope, document_reference="NFCE-65",
        kind=FiscalArchiveKind.AUTHORIZED_XML, content=xml, media_type="application/xml",
        archived_at=datetime.now(UTC),
        retention=RetentionPolicyMetadata(policy_id="test", policy_version=1),
    )
    archive.append(entry)
    assert _printable_authorized_xml(entry)
    observed: list[str] = []
    executor = DurableHumanPortalExecutor(
        cast(FiscalUnitOfWorkFactory, lambda: _Uow(archive)),
        danfe_renderer=lambda _xml: observed.append("danfe55") or b"%PDF-1.7\nWRONG",
        danfce_renderer=lambda _xml: observed.append("danfce65") or b"%PDF-1.7\nNFCe",
    )

    def read(kind: FiscalArchiveKind, tenant: str = "tenant-a") -> tuple[bytes, str]:
        return executor.fiscal_artifact(
            authority=cast(AuthenticatedHuman, _Authorized(tenant)),
            unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
            document_reference="NFCE-65", kind=kind,
        )

    with pytest.raises(HTTPException) as legacy:
        read(FiscalArchiveKind.DANFE)
    assert legacy.value.status_code == 409
    assert observed == []
    assert read(FiscalArchiveKind.AUXILIARY_PDF) == (
        b"%PDF-1.7\nNFCe", "application/pdf",
    )
    assert observed == ["danfce65"]
    with pytest.raises(HTTPException) as cross_tenant:
        read(FiscalArchiveKind.AUXILIARY_PDF, "another-tenant")
    assert cross_tenant.value.status_code == 404


def test_legacy_danfe_handles_bad_xml_as_safe_http_error() -> None:
    scope = ExecutionScope(
        host_namespace="fm-nfcore", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="bad-xml",
    )
    archive = InMemoryFiscalArchiveStore()
    archive.append(FiscalArchiveEntry.build(
        scope=scope, document_reference="BAD-XML",
        kind=FiscalArchiveKind.AUTHORIZED_XML,
        content=b"<nfeProc>", media_type="application/xml",
        archived_at=datetime.now(UTC),
        retention=RetentionPolicyMetadata(policy_id="test", policy_version=1),
    ))
    rendered: list[bytes] = []
    executor = DurableHumanPortalExecutor(
        cast(FiscalUnitOfWorkFactory, lambda: _Uow(archive)),
        danfe_renderer=lambda xml: rendered.append(xml) or b"%PDF-1.7\nWRONG",
    )
    with pytest.raises(HTTPException) as error:
        executor.fiscal_artifact(
            authority=cast(AuthenticatedHuman, _Authorized("tenant-a")),
            unit_id="unit-a", environment=FiscalEnvironment.HOMOLOGATION,
            document_reference="BAD-XML", kind=FiscalArchiveKind.DANFE,
        )
    assert error.value.status_code == 409
    assert rendered == []



@pytest.mark.parametrize(
    ("document_model", "advertise_pdf"),
    [("55", True), ("65", False), ("57", False)],
)
def test_portal_advertises_nfe_danfe_only_for_supported_model(
    document_model: str, advertise_pdf: bool,
) -> None:
    """A supported nfeProc root alone does not mean model 65 can print as DANFE 55."""
    from kordena_fiscal.web.portal_runtime import _printable_authorized_xml

    scope = ExecutionScope(
        host_namespace="fm-nfcore", tenant_id="tenant-a", unit_id="unit-a",
        environment=FiscalEnvironment.HOMOLOGATION, correlation_id="pdf-model-scope",
    )
    xml = (
        '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
        '<NFe><infNFe Id="NFe' + ("1" * 44) + '">'
        '<ide><mod>' + document_model + '</mod></ide>'
        '</infNFe></NFe></nfeProc>'
    ).encode("ascii")
    entry = FiscalArchiveEntry.build(
        scope=scope,
        document_reference="MODEL-" + document_model,
        kind=FiscalArchiveKind.AUTHORIZED_XML,
        content=xml,
        media_type="application/xml",
        archived_at=datetime.now(UTC),
        retention=RetentionPolicyMetadata(policy_id="test", policy_version=1),
    )
    assert _printable_authorized_xml(entry) is advertise_pdf
