"""Osasco WCF composition: one canonical RPS loader and no implicit activation."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoRtcHomologationTransport,
    OsascoWcfContract,
)
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.runtime.canonical_fiscal_composition import (
    build_runtime_fiscal_handler_factory,
)
from kordena_fiscal.runtime.osasco_operational_composition import (
    OsascoTrustedRuntimePorts,
    build_osasco_trusted_transport,
)
from kordena_fiscal.runtime.osasco_pinned_composition import (
    OsascoReviewedSchemaPorts,
    build_osasco_pinned_operational_ports,
)
from kordena_fiscal.runtime.osasco_wsdl_contract import OsascoPinnedWcfWsdl
from kordena_fiscal.vault.contracts import SecretResolutionService


def _ports() -> OsascoTrustedRuntimePorts:
    transport = OsascoRtcHomologationTransport(
        resolver=Mock(),
        resolve_key=Mock(side_effect=AssertionError("no real key at composition")),
        validated_request=Mock(),
        contract_for_method=Mock(),
    )
    return OsascoTrustedRuntimePorts(
        transport=transport,
        build_wcf_operation=Mock(),
        verify_wcf_rps_identity=Mock(),
        fiscal_issuer_policy=Mock(),
        validate_prepared_rps=Mock(),
        verify_official_invoice_xml=Mock(),
        interpret_official_result=Mock(),
    )


def test_osasco_attaches_to_existing_application_factory_without_second_uow(
    tmp_path: object,
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    db = SqliteFiscalDatabase(tmp_path / "osasco-operational.sqlite")
    db.initialize()
    application = FiscalApplicationService(db)
    ports = _ports()
    reviewed = ports.attach(application)
    assert reviewed.load_original_rps.__closure__ is not None
    handlers = build_runtime_fiscal_handler_factory(
        sp4_reviewed_municipalities={"osasco-rtc-homologation": reviewed},
    )(application)
    assert {"issueFiscalDocument", "queryFiscalDocument"} <= set(handlers)
    default = build_runtime_fiscal_handler_factory()(application)
    assert "issueFiscalDocument" in default
    assert "cancelCajamarNfse" not in default


def test_osasco_port_set_rejects_missing_external_verified_interpreter() -> None:
    ports = _ports()
    with pytest.raises(ValueError, match="complete reviewed"):
        OsascoTrustedRuntimePorts(
            transport=ports.transport,
            build_wcf_operation=ports.build_wcf_operation,
            verify_wcf_rps_identity=ports.verify_wcf_rps_identity,
            fiscal_issuer_policy=ports.fiscal_issuer_policy,
            validate_prepared_rps=ports.validate_prepared_rps,
            verify_official_invoice_xml=ports.verify_official_invoice_xml,
            interpret_official_result=None,  # type: ignore[arg-type]
        )


def test_osasco_real_transport_builder_reuses_fiscal_application_without_io(
    tmp_path: object,
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    db = SqliteFiscalDatabase(tmp_path / "osasco-factory.sqlite")
    db.initialize()
    application = FiscalApplicationService(db)
    vault = Mock()
    secret_resolver = SecretResolutionService(
        unit_of_work_factory=db, vault=vault,
    )
    transport = build_osasco_trusted_transport(
        application=application,
        unit_of_work_factory=db,
        secrets=secret_resolver,
        workload_id="nfcore-api",
        validate_official_request=Mock(),
        contract_for_method=Mock(),
    )
    assert isinstance(transport, OsascoRtcHomologationTransport)
    assert vault.resolve.call_count == 0
    with pytest.raises(ValueError, match="contract ports"):
        build_osasco_trusted_transport(
            application=application, unit_of_work_factory=db,
            secrets=secret_resolver, workload_id="nfcore-api",
            validate_official_request=None,  # type: ignore[arg-type]
            contract_for_method=Mock(),
        )


def test_osasco_pinned_wsdl_composes_same_runtime_without_accessing_secrets(
    tmp_path: object,
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    db = SqliteFiscalDatabase(tmp_path / "osasco-pinned-schema.sqlite")
    db.initialize()
    application = FiscalApplicationService(db)
    secret_service = SecretResolutionService(
        unit_of_work_factory=db, vault=Mock(),
    )
    actions = {
        m: OsascoWcfContract(
            action="http://tempuri.org/INotaFiscalEletronica/" + m,
            method=m, wsdl_sha256="a" * 64,
        ) for m in ("RTC_EmitirNFE", "ConsultarNotaCompleta", "Cancelar")
    }
    wsdl = OsascoPinnedWcfWsdl(
        sha256="a" * 64, binding_name="BasicHttpBinding_Reviewed",
        operations=actions,
    )
    schema = OsascoReviewedSchemaPorts(
        validate_issuance=Mock(), validate_query=Mock(),
        validate_cancellation=Mock(), verify_full_invoice=Mock(),
    )
    ports = build_osasco_pinned_operational_ports(
        application=application, unit_of_work_factory=db,
        secrets=secret_service, workload_id="nfcore-api",
        wsdl=wsdl, schema=schema,
        resolve_policy=Mock(), fiscal_issuer_policy=Mock(),
    )
    assert isinstance(ports, OsascoTrustedRuntimePorts)
    assert ports.verify_official_cancel is None
    assert "cancelOsascoNfse" not in build_runtime_fiscal_handler_factory(
        osasco_runtime_ports=ports,
    )(application)
    with pytest.raises(ValueError, match="dependencies"):
        build_osasco_pinned_operational_ports(
            application=application, unit_of_work_factory=db,
            secrets=secret_service, workload_id="nfcore-api",
            wsdl=wsdl, schema=schema, resolve_policy=Mock(),
            fiscal_issuer_policy=None,  # type: ignore[arg-type]
        )
