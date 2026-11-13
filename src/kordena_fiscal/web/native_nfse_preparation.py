"""Native National NFS-e preparation through the existing scoped fiscal engine.

This is a preparation boundary, not an issuer or provider transport. No browser
claim can choose the tenant, provider, A1, signed XML, numbering or environment.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import RetentionPolicyMetadata
from kordena_fiscal.compliance.nfse_preaudit import nfse_preaudit
from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
from kordena_fiscal.control_plane.service import ControlPlaneNotFoundError
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    Cpf,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    Money,
    SourceReference,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
    NfseServiceTaker,
)
from kordena_fiscal.issuance.sp4_original_rps_archive import (
    build_sp4_original_from_reservation,
)
from kordena_fiscal.lifecycle.idempotency import IdempotencyConflictError
from kordena_fiscal.numbering import FiscalNumberReservation
from kordena_fiscal.persistence.ports import (
    FiscalUnitOfWorkFactory,
    PersistenceConflictError,
    PersistenceStateError,
)
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanAuthorizationError,
    PortalPermission,
    PortalRole,
)

_FIELDS = frozenset({
    "unit_id", "environment", "source_id", "competence_date",
    "service_state_code", "service_municipality_ibge", "national_taxation_code",
    "municipal_service_code", "description", "gross_amount", "deduction_amount",
    "iss_amount", "iss_withheld", "taker_document", "taker_name",
    "source_normative", "rule_version", "fiscal_review_approved",
})
_STRING_FIELDS = _FIELDS - {"iss_withheld", "rule_version", "fiscal_review_approved"}
_CENTS = re.compile(r"(?:0|[1-9][0-9]{0,8})\.[0-9]{2}\Z")
_TAKER = re.compile(r"(?:[0-9]{11}|[0-9]{14})\Z")
_DIGITS_6 = re.compile(r"[0-9]{6}\Z")
_DIGITS_7 = re.compile(r"[0-9]{7}\Z")


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code})


def prepare_native_nfse(
    *, factory: FiscalUnitOfWorkFactory, authority: AuthenticatedHuman,
    payload: Mapping[str, Any], idempotency_key: str | None,
    resolve_sp4_numbering: Callable[
        [ExecutionScope, str, str], tuple[int, str]
    ] | None = None,
) -> Mapping[str, Any]:
    """Persist one reviewed NFS-e, using the existing issuer/sequence authority.

    For municipalities the already-authorized, scoped RPS series comes from
    trusted composition, never from the HTTP request or an arbitrary fallback.
    """
    key = (idempotency_key or "").strip()
    if (
        not isinstance(payload, Mapping) or set(payload) != _FIELDS
        or any(type(payload.get(field)) is not str for field in _STRING_FIELDS)
        or type(payload.get("iss_withheld")) is not bool
        or type(payload.get("rule_version")) is not int
        or type(payload.get("fiscal_review_approved")) is not bool
        or not key or len(key) > 256
    ):
        raise _error(400, "NATIVE_NFSE_INVALID_REQUEST")
    if (
        authority.account.role not in {PortalRole.OWNER, PortalRole.ADMIN}
        or payload["fiscal_review_approved"] is not True
        or PortalPermission.CONFIGURATION_WRITE not in authority.permissions
        or PortalPermission.DOCUMENT_ISSUE not in authority.permissions
    ):
        raise _error(403, "NATIVE_NFSE_REVIEW_REQUIRED")

    unit = payload["unit_id"].strip()
    try:
        authority.assert_permission(PortalPermission.DOCUMENT_ISSUE, unit_id=unit)
        authority.assert_permission(PortalPermission.CONFIGURATION_WRITE, unit_id=unit)
        if payload["environment"] != FiscalEnvironment.HOMOLOGATION.value:
            raise FiscalValidationError("Only National NFS-e homologation may be prepared")
        source_id = payload["source_id"].strip()
        if not source_id or len(source_id) > 120:
            raise FiscalValidationError("Unique source reference is required")
        competence = date.fromisoformat(payload["competence_date"])
        if competence.isoformat() != payload["competence_date"]:
            raise FiscalValidationError("Competence date must be ISO")
        service_jurisdiction = BrazilianJurisdiction(
            payload["service_state_code"], payload["service_municipality_ibge"]
        )
        if not _DIGITS_7.fullmatch(payload["service_municipality_ibge"]):
            raise FiscalValidationError("Municipality IBGE code is required")
        if not _DIGITS_6.fullmatch(payload["national_taxation_code"]):
            raise FiscalValidationError("Official national service code is required")
        if not 1 <= payload["rule_version"] <= 99999:
            raise FiscalValidationError("Rule version must be explicit")
        if not 1 <= len(payload["source_normative"].strip()) <= 512:
            raise FiscalValidationError("Reviewed normative source is required")
        if not _TAKER.fullmatch(payload["taker_document"]):
            raise FiscalValidationError("Validated CPF or CNPJ is mandatory")
        taker_id = (
            Cnpj(payload["taker_document"]) if len(payload["taker_document"]) == 14
            else Cpf(payload["taker_document"])
        )
        taker = NfseServiceTaker(tax_id=taker_id, legal_name=payload["taker_name"])
        for field in ("gross_amount", "deduction_amount", "iss_amount"):
            if not _CENTS.fullmatch(payload[field]):
                raise FiscalValidationError("Values require exact two-decimal BRL amounts")
        gross = Decimal(payload["gross_amount"])
        deductions = Decimal(payload["deduction_amount"])
        iss = Decimal(payload["iss_amount"])
        # No tax assumption: the present DPS builder hardcodes taxed ISS.
        # Non-incidence, exemption, zero ISS and special regimes remain blocked
        # until an explicit normative classification is modeled.
        if not (Decimal("0") < gross and Decimal("0") <= deductions < gross and
                Decimal("0") < iss <= gross - deductions):
            raise FiscalValidationError("This preparer only supports reviewed taxable ISS")
        now = datetime.now(UTC)
        scope = ExecutionScope(
            host_namespace="fm-nfcore", tenant_id=authority.tenant_id,
            unit_id=unit, environment=FiscalEnvironment.HOMOLOGATION,
            correlation_id="native-nfse-" + hashlib.sha256(
                (authority.tenant_id + ":" + unit + ":" + source_id).encode()
            ).hexdigest()[:24],
        )
        source = SourceReference("nfcore-portal", source_id)
        document_id = "native-nfse-" + hashlib.sha256(
            (repr(scope.identity_partition_key) + ":" + source_id).encode()
        ).hexdigest()[:40]
        with factory() as uow:
            registration = uow.control_plane.get_unit(authority.tenant_id, unit)
            if (
                registration is None
                or FiscalEnvironment.HOMOLOGATION not in registration.enabled_environments
            ):
                raise FiscalValidationError("Unit is not enabled in homologation")
            profile = uow.control_plane.resolve_profile(
                host_namespace="fm-nfcore", tenant_id=authority.tenant_id,
                unit_id=unit, environment=FiscalEnvironment.HOMOLOGATION,
                instant=now,
            )
        if profile is None:
            raise FiscalValidationError("Issuer fiscal profile is not effective")
        app = FiscalApplicationService(factory)
        provider = app.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=profile.address.jurisdiction,
            operation=ConfiguredFiscalOperation.AUTHORIZE.value,
        )
        municipal = provider in SP4_MUNICIPAL_PROVIDERS
        if not municipal and provider != NACIONAL_HOMOLOGATION_PROVIDER_ID:
            raise FiscalValidationError("NFS-e binding is not approved")
        sp4_series: tuple[int, str] | None = None
        if municipal:
            if (
                resolve_sp4_numbering is None
                or SP4_MUNICIPAL_PROVIDERS[provider]
                != profile.address.jurisdiction.municipality_ibge_code
                or profile.tax_regime is not TaxRegimeCode.NORMAL
            ):
                raise FiscalValidationError("Reviewed SP4 municipal policy is unavailable")
            sp4_series = resolve_sp4_numbering(
                scope, profile.cnpj.value, provider,
            )
            if (
                not isinstance(sp4_series, tuple) or len(sp4_series) != 2
                or type(sp4_series[0]) is not int
                or not 0 <= sp4_series[0] <= 99_999
                or not isinstance(sp4_series[1], str)
                or not 0 <= len(sp4_series[1]) <= 16
            ):
                raise FiscalValidationError("Reviewed SP4 RPS numbering series invalid")
        previous = None
        try:
            previous = app.load_prepared_nfse_authorization(scope, document_id)
        except (PersistenceConflictError, PersistenceStateError):
            pass
        issued_at = previous.document.issued_at if previous else now
        profile = previous.document.issuer if previous else profile
        line = NfseServiceLine(
            line_number=1,
            municipal_service_code=payload["municipal_service_code"],
            national_taxation_code=payload["national_taxation_code"],
            description=payload["description"],
            gross_amount=Money(gross), deduction_amount=Money(deductions),
            iss_amount=Money(iss), iss_withheld=payload["iss_withheld"],
            source_normative=payload["source_normative"].strip(),
            rule_version=payload["rule_version"],
        )
        document = NfseCanonicalDocument(
            document_id=document_id, scope=scope, source=source,
            issued_at=issued_at, competence_date=competence, issuer=profile,
            service_jurisdiction=service_jurisdiction, services=(line,),
            service_taker_reference=(
                "cnpj:" if isinstance(taker.tax_id, Cnpj) else "cpf:"
            ) + taker.tax_id.value,
            service_taker=taker,
        )
        nfse_preaudit(NfseAuthorizationRequest.build(document))
        sp4_intent_builder: Callable[[FiscalNumberReservation], Sp4OriginalRps] | None = None
        if sp4_series is not None:
            # Reuse the same canonical immutable document, not a second RPS
            # numbering allocation or a provider-specific database.
            prepared_request = NfseAuthorizationRequest.build(document)
            _, label = sp4_series
            def build_reviewed_sp4_rps(numbered: FiscalNumberReservation) -> Sp4OriginalRps:
                return build_sp4_original_from_reservation(
                    prepared_request, numbered, rps_series=label,
                )

            sp4_intent_builder = build_reviewed_sp4_rps
        result = app.prepare_nfse_authorization(
            document, occurred_at=now,
            retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
            sp4_intent_builder=sp4_intent_builder,
            sp4_rps_series=sp4_series[0] if sp4_series is not None else None,
        )
        municipal_source = (
            app.load_sp4_original_rps(scope, result.attempt.document_id)
            if sp4_series is not None else None
        )
        return {
            "document_id": result.attempt.document_id,
            "status": result.lifecycle.state.value,
            "replay": result.replay,
            "environment": "homologation",
            "transmitted": False,
            "fiscal_authorization": "not_inferred_from_preparation",
            "dps_numbering": (
                "not_applicable_municipal"
                if municipal_source is not None else "pending_durable_authority"
            ),
            **(
                {
                    "rps_number": municipal_source.rps_number,
                    "rps_series": municipal_source.rps_series,
                    "municipal_batch_id": municipal_source.municipal_batch_id,
                }
                if municipal_source is not None else {}
            ),
        }
    except HumanAuthorizationError as exc:
        raise _error(403, "NATIVE_NFSE_UNIT_FORBIDDEN") from exc
    except ControlPlaneNotFoundError as exc:
        raise _error(409, "NATIVE_NFSE_PROVIDER_NOT_CONFIGURED") from exc
    except (PersistenceConflictError, IdempotencyConflictError) as exc:
        raise _error(409, "NATIVE_NFSE_CONTENT_CONFLICT") from exc
    except PersistenceStateError as exc:
        raise _error(409, "NATIVE_NFSE_PREPARATION_STATE_CONFLICT") from exc
    except (FiscalValidationError, ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise _error(400, "NATIVE_NFSE_INVALID_FISCAL_FACTS") from exc
