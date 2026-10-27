"""Single opt-in wiring point for provider-backed fiscal read and event operations.

The caller must explicitly supply an approved FiscalOperationsClient. The
factory never discovers credentials, chooses providers or enables production.
Prepared XML issuance and recovery require explicit durable application, gateway
and retention inputs; client-only callers keep their existing read/event surface.
"""

from __future__ import annotations

from datetime import UTC, datetime

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.gateway import FiscalGatewayClient
from kordena_fiscal.issuance import NfseGatewayClient, NfseQueryClient
from kordena_fiscal.operations import (
    CancellationResult,
    FiscalOperationsClient,
    InutilizationResult,
)
from kordena_fiscal.operations.event_archive import build_event_result_evidence

from .fiscal_runtime import FiscalOperationHandler
from .provider_event_handlers import (
    build_provider_cancel_handler,
    build_provider_inutilization_handler,
)
from .provider_issuance_handler import (
    build_provider_issuance_handler,
    build_provider_reconciliation_handler,
)
from .provider_query_handler import build_provider_query_handler


def build_provider_operation_handlers(
    client: FiscalOperationsClient,
    *,
    application: FiscalApplicationService | None = None,
    prepared_xml_gateway: FiscalGatewayClient | None = None,
    prepared_nfse_gateway: NfseGatewayClient | None = None,
    prepared_nfse_query_client: NfseQueryClient | None = None,
    archive_retention: RetentionPolicyMetadata | None = None,
) -> dict[str, FiscalOperationHandler]:
    """Compose the existing provider client into the canonical Portal/Bridge path."""
    if not isinstance(client, FiscalOperationsClient):
        raise TypeError("an explicitly configured FiscalOperationsClient is required")
    handlers = {
        "queryFiscalDocument": build_provider_query_handler(client),
        "cancelFiscalDocument": build_provider_cancel_handler(client),
        "inutilizeFiscalRange": build_provider_inutilization_handler(client),
    }
    if any(
        value is not None
        for value in (
            application,
            prepared_xml_gateway,
            prepared_nfse_gateway,
            prepared_nfse_query_client,
            archive_retention,
        )
    ):
        if (
            not isinstance(application, FiscalApplicationService)
            or not isinstance(archive_retention, RetentionPolicyMetadata)
            or (prepared_xml_gateway is not None
                and not isinstance(prepared_xml_gateway, FiscalGatewayClient))
            or (prepared_nfse_gateway is not None
                and not isinstance(prepared_nfse_gateway, NfseGatewayClient))
            or (prepared_nfse_query_client is not None
                and not isinstance(prepared_nfse_query_client, NfseQueryClient))
        ):
            raise TypeError("prepared operations require application, gateway and retention")

        def record_event(result: CancellationResult | InutilizationResult) -> str:
            assert application is not None and archive_retention is not None
            return application.archive(build_event_result_evidence(
                result, archived_at=datetime.now(UTC), retention=archive_retention
            )).entry_id

        handlers["cancelFiscalDocument"] = build_provider_cancel_handler(
            client, record_result=record_event
        )
        handlers["inutilizeFiscalRange"] = build_provider_inutilization_handler(
            client, record_result=record_event
        )
        if prepared_xml_gateway is None and prepared_nfse_gateway is None:
            if prepared_nfse_query_client is not None:
                raise TypeError("prepared query requires an issuance gateway")
            return handlers
        primary_gateway: FiscalGatewayClient | NfseGatewayClient
        if prepared_xml_gateway is not None:
            primary_gateway = prepared_xml_gateway
        elif prepared_nfse_gateway is not None:
            primary_gateway = prepared_nfse_gateway
        else:  # The validated guard above makes this unreachable.
            raise TypeError("one prepared provider gateway is required")
        handlers["issueFiscalDocument"] = build_provider_issuance_handler(
            application,
            resolve_prepared=application.load_prepared_document_authorization,
            gateway=primary_gateway,
            nfse_gateway=prepared_nfse_gateway,
        )
        handlers["reconcileFiscalOperation"] = build_provider_reconciliation_handler(
            application,
            client=client,
            archive_retention=archive_retention,
            nfse_client=prepared_nfse_query_client,
        )
    return handlers
