"""Native National NFS-e preparation through the existing scoped fiscal engine.

This is a preparation boundary, not an issuer or provider transport. No browser
claim can choose the tenant, provider, A1, signed XML, numbering or environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.compliance.nfse_preaudit import nfse_preaudit
from kordena_fiscal.control_plane.commercial import ConfiguredFiscalOperation
from kordena_fiscal.control_plane.service import ControlPlaneNotFoundError
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    Cpf,
    ExecutionScope,
    FiscalAddress,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    Money,
    SourceReference,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.mg_nfse_channel_guard import (
    require_mg_national_channel_eligibility,
)
from kordena_fiscal.gateway.municipal_sp_routing import (
    require_guarulhos_nfse_channel,
    require_sp_municipal_nfse_issuance_permitted,
)
from kordena_fiscal.gateway.nfse_nacional_homologation import (
    NACIONAL_HOMOLOGATION_PROVIDER_ID,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import Sp4OriginalRps
from kordena_fiscal.issuance import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseForeignAddress,
    NfseNationalSubstitution,
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
from kordena_fiscal.runtime.native_nfse_policy import resolve_national_treatment
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
_TAKER_ADDRESS_FIELDS = frozenset({
    "taker_street", "taker_number", "taker_neighborhood", "taker_city",
    "taker_state", "taker_municipality_ibge", "taker_postal_code",
})
_FOREIGN_ADDRESS_FIELDS = frozenset({
    "taker_country_code", "taker_foreign_postal_code", "taker_foreign_city",
    "taker_foreign_region", "taker_street", "taker_number",
    "taker_neighborhood",
})
_FOREIGN_ID_FIELDS = frozenset({"taker_nif", "taker_no_nif_reason"})
_COMMON_FIELDS = _FIELDS - {"taker_document"}
_NBS_FIELD = frozenset({"nbs_code"})
_MUNICIPAL_DETAIL_FIELD = frozenset({"municipal_taxation_detail"})
_BASE_ALLOWED_PAYLOADS = frozenset({
    _FIELDS,
    _FIELDS | _TAKER_ADDRESS_FIELDS,
    _COMMON_FIELDS | _FOREIGN_ADDRESS_FIELDS | {"taker_nif"},
    _COMMON_FIELDS | _FOREIGN_ADDRESS_FIELDS | {"taker_no_nif_reason"},
})
_SUBSTITUTION_FIELDS = frozenset({
    "substitution_original_id", "substitution_reason_code",
    "substitution_reason_description", "substitution_human_approval",
})
_ALLOWED_NORMAL = frozenset(
    fields | optional
    for fields in _BASE_ALLOWED_PAYLOADS
    for optional in (frozenset(), _NBS_FIELD, _MUNICIPAL_DETAIL_FIELD,
                     _NBS_FIELD | _MUNICIPAL_DETAIL_FIELD)
)
_ALLOWED_PAYLOADS = _ALLOWED_NORMAL | frozenset(
    fields | _SUBSTITUTION_FIELDS for fields in _ALLOWED_NORMAL
)
_STRING_FIELDS = (
    (_FIELDS | _TAKER_ADDRESS_FIELDS | _FOREIGN_ADDRESS_FIELDS | _FOREIGN_ID_FIELDS
     | _NBS_FIELD | _MUNICIPAL_DETAIL_FIELD | _SUBSTITUTION_FIELDS)
    - {
        "iss_withheld", "rule_version", "fiscal_review_approved",
        "substitution_human_approval",
    }
)
_BARUERI_PROVIDER = "barueri-pmb004-homologation"
_CAJAMAR_PROVIDER = "cajamar-geisweb-homologation"
_OSASCO_PROVIDER = "osasco-rtc-homologation"
_JUNDIAI_PROVIDER = "jundiai-giss-v2-homologation"
_GUARULHOS_PROVIDER = "guarulhos-giss-v2-homologation"
_SANTANA_PROVIDER = "santana-simpliss-v1-homologation"
_SANTANA_IBGE = "3547304"
_CENTS = re.compile(r"(?:0|[1-9][0-9]{0,8})\.[0-9]{2}\Z")
_TAKER = re.compile(r"(?:[0-9]{11}|[0-9]{14})\Z")
_DIGITS_6 = re.compile(r"[0-9]{6}\Z")
_DIGITS_7 = re.compile(r"[0-9]{7}\Z")
_DIGITS_9 = re.compile(r"[0-9]{9}\Z")


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code})


def prepare_native_nfse(
    *, factory: FiscalUnitOfWorkFactory, authority: AuthenticatedHuman,
    payload: Mapping[str, Any], idempotency_key: str | None,
) -> Mapping[str, Any]:
    """Persist reviewed National or SP4 NFS-e through one canonical fiscal UoW."""
    key = (idempotency_key or "").strip()
    if (
        not isinstance(payload, Mapping)
        or frozenset(payload) not in _ALLOWED_PAYLOADS
        or any(
            type(payload[field]) is not str
            for field in _STRING_FIELDS & set(payload)
        )
        or type(payload.get("iss_withheld")) is not bool
        or type(payload.get("rule_version")) is not int
        or type(payload.get("fiscal_review_approved")) is not bool
        or (
            "substitution_human_approval" in payload
            and type(payload["substitution_human_approval"]) is not bool
        )
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
        if _SUBSTITUTION_FIELDS.issubset(payload):
            if (
                payload["substitution_human_approval"] is not True
                or not 8 <= len(key) <= 128 or not key.isascii()
            ):
                raise FiscalValidationError("National replacement requires human approval")
            authority.assert_permission(PortalPermission.DOCUMENT_CANCEL, unit_id=unit)
        if payload["environment"] != FiscalEnvironment.HOMOLOGATION.value:
            raise FiscalValidationError("Only NFS-e homologation may be prepared")
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
        # The canonical domain and DPS 1.01 serializer already support
        # foreign tomadores. Never coerce NIF/cNaoNIF into a Brazilian CPF/CNPJ.
        taker_id: Cnpj | Cpf | None = None
        taker_address: FiscalAddress | NfseForeignAddress | None = None
        if _FOREIGN_ADDRESS_FIELDS.issubset(payload):
            taker_address = NfseForeignAddress(
                country_code=payload["taker_country_code"],
                postal_code=payload["taker_foreign_postal_code"],
                city=payload["taker_foreign_city"],
                region=payload["taker_foreign_region"],
                street=payload["taker_street"],
                number=payload["taker_number"],
                district=payload["taker_neighborhood"],
            )
            nif = payload.get("taker_nif")
            no_nif = payload.get("taker_no_nif_reason")
            taker = NfseServiceTaker(
                tax_id=None, legal_name=payload["taker_name"],
                address=taker_address, nif=nif, no_nif_reason=no_nif,
            )
            taker_reference = (
                "nif:" + nif if nif is not None else
                "no-nif:" + payload["taker_country_code"] + ":" + payload["taker_name"]
            )
        else:
            if not _TAKER.fullmatch(payload["taker_document"]):
                raise FiscalValidationError("Validated CPF or CNPJ is mandatory")
            taker_id = (
                Cnpj(payload["taker_document"])
                if len(payload["taker_document"]) == 14
                else Cpf(payload["taker_document"])
            )
            if _TAKER_ADDRESS_FIELDS.issubset(payload):
                if not _DIGITS_7.fullmatch(payload["taker_municipality_ibge"]):
                    raise FiscalValidationError("Taker municipality IBGE code is required")
                taker_address = FiscalAddress(
                    street=payload["taker_street"],
                    number=payload["taker_number"],
                    district=payload["taker_neighborhood"],
                    municipality_name=payload["taker_city"],
                    jurisdiction=BrazilianJurisdiction(
                        payload["taker_state"], payload["taker_municipality_ibge"],
                    ),
                    postal_code=payload["taker_postal_code"],
                )
            taker = NfseServiceTaker(
                tax_id=taker_id, legal_name=payload["taker_name"],
                address=taker_address,
            )
            taker_reference = (
                "cnpj:" if isinstance(taker_id, Cnpj) else "cpf:"
            ) + taker_id.value
        for field in ("gross_amount", "deduction_amount", "iss_amount"):
            if not _CENTS.fullmatch(payload[field]):
                raise FiscalValidationError("Values require exact two-decimal BRL amounts")
        gross = Decimal(payload["gross_amount"])
        deductions = Decimal(payload["deduction_amount"])
        iss = Decimal(payload["iss_amount"])
        if not (Decimal("0") < gross and Decimal("0") <= deductions < gross and
                Decimal("0") <= iss <= gross - deductions):
            raise FiscalValidationError("Invalid reviewed service amounts")
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
        app = FiscalApplicationService(factory)
        previous = None
        try:
            previous = app.load_prepared_nfse_authorization(scope, document_id)
        except (PersistenceConflictError, PersistenceStateError):
            pass
        with factory() as uow:
            registration = uow.control_plane.get_unit(authority.tenant_id, unit)
            if (
                registration is None
                or FiscalEnvironment.HOMOLOGATION not in registration.enabled_environments
            ):
                raise FiscalValidationError("Unit is not enabled in homologation")
            profile = previous.document.issuer if previous else uow.control_plane.resolve_profile(
                host_namespace="fm-nfcore", tenant_id=authority.tenant_id,
                unit_id=unit, environment=FiscalEnvironment.HOMOLOGATION,
                instant=now,
            )
        if profile is None:
            raise FiscalValidationError("Issuer fiscal profile is not effective")
        provider = app.resolve_configured_provider_id(
            scope=scope, document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=profile.address.jurisdiction,
            operation=ConfiguredFiscalOperation.AUTHORIZE.value,
        )
        municipal_barueri = provider == _BARUERI_PROVIDER
        municipal_cajamar = provider == _CAJAMAR_PROVIDER
        municipal_osasco = provider == _OSASCO_PROVIDER
        municipal_jundiai = provider == _JUNDIAI_PROVIDER
        municipal_guarulhos = provider == _GUARULHOS_PROVIDER
        require_guarulhos_nfse_channel(
            issuer_jurisdiction=profile.address.jurisdiction,
            tax_regime=profile.tax_regime, competence_date=competence,
            provider_id=provider,
        )
        # A national provider binding is necessary, not sufficient: for MG-W1
        # cities, the federal/municipal channel and competence must be valid
        # before recording READY_TO_TRANSMIT or reserving any fiscal number.
        # Replays preserve immutable prior facts; the deterministic gateway
        # repeats this negative gate before reading A1 or calling SEFIN.
        if previous is None and provider == NACIONAL_HOMOLOGATION_PROVIDER_ID:
            require_mg_national_channel_eligibility(
                jurisdiction=profile.address.jurisdiction,
                tax_regime=profile.tax_regime,
                competence_date=competence,
                national_taxation_code=payload["national_taxation_code"],
            )
        municipal_sp = (
            municipal_barueri or municipal_cajamar
            or municipal_osasco or municipal_jundiai or municipal_guarulhos
        )
        if (
            provider not in (NACIONAL_HOMOLOGATION_PROVIDER_ID, _SANTANA_PROVIDER)
            and not municipal_sp
        ):
            raise FiscalValidationError("Configured NFS-e provider is not supported")
        if provider == _SANTANA_PROVIDER and (
            profile.address.jurisdiction.state_code != "SP"
            or profile.address.jurisdiction.municipality_ibge_code != _SANTANA_IBGE
        ):
            raise FiscalValidationError("Santana Simpliss requires its exact issuer city")
        if provider == _SANTANA_PROVIDER and not _DIGITS_9.fullmatch(
            str(payload.get("nbs_code", ""))
        ):
            raise FiscalValidationError("Santana requires reviewed NBS 2.0 nine-digit code")
        # Santana's Simpliss is municipal even though its payload reuses the
        # national DPS schema. Do not bypass the same federal Simples/MEI cutoffs.
        if provider == _SANTANA_PROVIDER and previous is None:
            require_sp_municipal_nfse_issuance_permitted(
                issuer_jurisdiction=profile.address.jurisdiction,
                tax_regime=profile.tax_regime, competence_date=competence,
            )
        if municipal_sp:
            expected_city = (
                "3505708" if municipal_barueri else
                "3509205" if municipal_cajamar else
                "3534401" if municipal_osasco else
                "3525904" if municipal_jundiai else "3518800"
            )
            if (
                profile.address.jurisdiction.state_code != "SP"
                or profile.address.jurisdiction.municipality_ibge_code != expected_city
                or not isinstance(taker_address, FiscalAddress)
            ):
                raise FiscalValidationError(
                    "Municipal NFS-e requires issuer city and complete taker address"
                )
            require_sp_municipal_nfse_issuance_permitted(
                issuer_jurisdiction=profile.address.jurisdiction,
                tax_regime=profile.tax_regime, competence_date=competence,
            )
        policy = None
        treatment = previous.document.national_tax_treatment if previous else None
        if previous is None and provider == NACIONAL_HOMOLOGATION_PROVIDER_ID:
            policy = resolve_national_treatment(os.environ, scope, {
                "issuer_profile_id": profile.profile_id,
                "issuer_profile_version": profile.version,
                "issuer_cnpj": profile.cnpj.value,
                "issuer_tax_regime": int(profile.tax_regime),
                "issuer_municipality_ibge": profile.address.jurisdiction.municipality_ibge_code,
                "service_state_code": service_jurisdiction.state_code,
                "service_municipality_ibge": service_jurisdiction.municipality_ibge_code,
                "national_taxation_code": payload["national_taxation_code"],
                "municipal_service_code": payload["municipal_service_code"],
                "taker_country": (
                    taker_address.country_code
                    if isinstance(taker_address, NfseForeignAddress) else "BR"
                ),
                "iss_withheld": payload["iss_withheld"],
                "nbs_code": payload.get("nbs_code"),
                "municipal_taxation_detail": payload.get("municipal_taxation_detail"),
                "source_normative": payload["source_normative"].strip(),
                "rule_version": payload["rule_version"],
            }, competence, source_type=source.source_type, source_id=source.source_id)
            treatment = policy.treatment if policy is not None else None
        if treatment is not None and provider != NACIONAL_HOMOLOGATION_PROVIDER_ID:
            raise FiscalValidationError("National decision cannot change municipal treatment")
        # Estimativa (2) and BH ato cooperado (1) are explicitly permitted
        # by a scoped, reviewed policy to avoid ISS highlighting.
        no_iss_highlight = treatment is not None and (
            treatment.special_regime_code == "2" or (
                profile.address.jurisdiction.municipality_ibge_code == "3106200"
                and treatment.special_regime_code == "1"
            )
        )
        # For MEI the national invoice is taxable but ISS is collected in the
        # fixed DAS-SIMEI, never assessed or highlighted per service invoice.
        # The canonical document itself rejects any nonzero ISS or retention.
        mei_national = (
            provider == NACIONAL_HOMOLOGATION_PROVIDER_ID
            and profile.tax_regime is TaxRegimeCode.MEI
        )
        ordinary_taxable = not mei_national and (
            treatment is None or (
                treatment.iss_taxation_code == "1" and not no_iss_highlight
            )
        )
        if ordinary_taxable and iss <= 0:
            raise FiscalValidationError("Taxable service requires positive reviewed ISS")
        if no_iss_highlight and (
            iss > 0 or payload["iss_withheld"]
        ):
            raise FiscalValidationError("Reviewed special regime cannot highlight or withhold ISS")
        # BH documentary deductions are checked by NfseCanonicalDocument,
        # including direct API/gateway paths; no Portal-only fiscal rule.
        if profile.tax_regime is TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT and (
            provider != NACIONAL_HOMOLOGATION_PROVIDER_ID
            or treatment is None or treatment.simples_assessment_code is None
        ):
            raise FiscalValidationError("Simples sublimit requires an approved national decision")
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
            nbs_code=payload.get("nbs_code"),
            municipal_taxation_detail=payload.get("municipal_taxation_detail"),
        )
        document = NfseCanonicalDocument(
            document_id=document_id, scope=scope, source=source,
            issued_at=issued_at, competence_date=competence, issuer=profile,
            service_jurisdiction=service_jurisdiction, services=(line,),
            service_taker_reference=taker_reference,
            service_taker=taker, national_tax_treatment=treatment,
        )
        if _SUBSTITUTION_FIELDS.issubset(payload):
            if provider != NACIONAL_HOMOLOGATION_PROVIDER_ID:
                raise FiscalValidationError("Replacement DPS requires national provider")
            original_id = payload["substitution_original_id"]
            existing_link = (
                previous.document.national_substitution if previous is not None else None
            )
            if existing_link is not None:
                if (
                    existing_link.original_document_id != original_id
                    or existing_link.reason_code != payload["substitution_reason_code"]
                    or existing_link.reason_description
                    != payload["substitution_reason_description"]
                    or existing_link.approval_reference != key
                ):
                    raise PersistenceConflictError("National replacement review changed")
                original_key = existing_link.original_invoice_reference
            else:
                original_key = app.review_prepared_national_nfse_substitution(
                    scope=scope, original_id=original_id, replacement=document,
                )
            document = replace(document, national_substitution=NfseNationalSubstitution(
                original_document_id=original_id,
                original_invoice_reference=original_key,
                reason_code=payload["substitution_reason_code"],
                reason_description=payload["substitution_reason_description"],
                approval_reference=key,
            ))
        if provider == NACIONAL_HOMOLOGATION_PROVIDER_ID:
            from kordena_fiscal.issuance.nfse_dps_builder import validate_sefin_dps_input
            validate_sefin_dps_input(document)
        nfse_preaudit(NfseAuthorizationRequest.build(document))
        # Browser cannot choose provider, series or sequence. The same UoW
        # reserves a city's original RPS without creating a second counter.
        def municipal_original(
            prepared: NfseAuthorizationRequest,
            reserved: FiscalNumberReservation,
        ) -> Sp4OriginalRps:
            return build_sp4_original_from_reservation(
                prepared, reserved, rps_series=(
                    "" if municipal_barueri else
                    "NF" if municipal_cajamar else "R1"
                ),
            )

        if policy is not None:
            # Pin the deployed configuration version in the same scoped durable
            # authority already used by sale policies. A version cannot mutate.
            policy_key = "native-nfse-policy:" + hashlib.sha256(json.dumps(
                [policy.policy_id, policy.version]
            ).encode()).hexdigest()
            with factory() as uow:
                replay = uow.commercial.reserve_configuration_command(
                    scope, policy_key, policy.digest,
                )
                if replay is None:
                    uow.archive.append(FiscalArchiveEntry.build(
                        scope=scope, document_reference=policy_key,
                        kind=FiscalArchiveKind.OTHER, content=policy.content,
                        media_type="application/vnd.nfcore.nfse-fiscal-policy.v1+json",
                        archived_at=now,
                        retention=RetentionPolicyMetadata("nfcore-fiscal-policy", 1),
                    ))
                uow.commercial.complete_configuration_command(
                    scope, policy_key, {"sha256": policy.digest},
                )
                uow.commit()

        result = app.prepare_nfse_authorization(
            document, occurred_at=now,
            retention=RetentionPolicyMetadata("nfcore-fiscal-archive", 1),
            sp4_original_builder=municipal_original if municipal_sp else None,
            sp4_rps_series=1 if municipal_sp else None,
            deduction_evidence=policy.deduction_evidence if policy is not None else (),
        )
        return {
            "document_id": result.attempt.document_id,
            "status": result.lifecycle.state.value,
            "replay": result.replay,
            "environment": "homologation",
            "transmitted": False,
            "fiscal_authorization": "not_inferred_from_preparation",
            "fiscal_policy_state": (
                "reviewed_policy_pinned_at_preparation"
                if provider == NACIONAL_HOMOLOGATION_PROVIDER_ID
                and treatment is not None
                and treatment.policy_id is not None
                and treatment.policy_sha256 is not None
                and (
                    not result.request.document.requires_reviewed_iss_rate
                    or treatment.iss_rate is not None
                )
                else "review_required_before_sefin"
                if provider == NACIONAL_HOMOLOGATION_PROVIDER_ID
                else "municipal_provider_contract"
            ),
            "dps_numbering": (
                "reserved_durable"
                if result.request.document.dps_number is not None
                else "not_applicable_municipal_original_rps"
            ),
            "dps_series": (
                result.request.document.dps_series
                if result.request.document.dps_number is not None else None
            ),
            "dps_number": result.request.document.dps_number,
            "numbering_authority": (
                "municipal_rps_durable" if municipal_sp
                else "national_dps_durable"
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
