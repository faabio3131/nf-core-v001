"""Durable SP4 municipal RPS identity using the existing fiscal UoW archive.

This is NOT a second sequence authority. A reserved number comes exclusively
from FiscalUnitOfWork.sequences (NFSE_RPS stream); the original RPS and its
canonical request are committed in the SAME transaction. Municipal lot IDs
are deterministic functions of that reserved number for safe read-only retry.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    SP4_MUNICIPAL_PROVIDERS,
    Sp4OriginalRps,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    InternalFiscalSequenceStream,
)

SP4_ORIGINAL_RPS_MEDIA_TYPE = "application/vnd.nfcore.sp4-original-rps.v1+json"
_MAXIMUM = {
    "3509205": 99_999_999,            # Cajamar GeisWeb: 8-digit RPS
    "3505708": 9_999_999,             # Barueri PMB004: 7-digit RPS
    "3534401": 999_999_999_999_999,   # Osasco WCF: existing 15-digit sequence
    "3525904": 999_999_999_999_999,   # Jundiai GissOnline: numeric RPS/lot
}


def expected_sp4_batch(ibge: str, number: int) -> str | None:
    """Deterministic official-format lot/reference, never a random second ID."""
    if ibge is None or ibge not in SP4_MUNICIPAL_PROVIDERS.values():
        raise FiscalValidationError("Unsupported SP4 original RPS issuer")
    if type(number) is not int or not 1 <= number <= _MAXIMUM[ibge]:
        raise FiscalValidationError("Original SP4 fiscal sequence exceeds city limit")
    if ibge == "3534401":  # synchronous Osasco RTC does not use a batch ID
        return None
    if ibge == "3505708":  # Barueri PMB004 mandates precisely 11 digits
        return f"{number:011d}"
    return str(number)



def build_sp4_original_from_reservation(
    request: NfseAuthorizationRequest,
    reservation: FiscalNumberReservation,
    *,
    rps_series: str,
) -> Sp4OriginalRps:
    """Create one source-bound RPS from the already reserved fiscal stream.

    The reviewed municipality-specific series must be provided by trusted
    composition. Do not allocate another number or infer it from a browser.
    """
    if not isinstance(request, NfseAuthorizationRequest):
        raise FiscalValidationError("SP4 requires canonical NFS-e request")
    doc = request.document
    ibge = doc.issuer.address.jurisdiction.municipality_ibge_code
    if ibge is None or ibge not in SP4_MUNICIPAL_PROVIDERS.values():
        raise FiscalValidationError("SP4 requires registered issuer municipality")
    if not isinstance(rps_series, str) or len(rps_series) > 16:
        raise FiscalValidationError("SP4 reviewed RPS series is invalid")
    if rps_series == "" and ibge != "3505708":
        raise FiscalValidationError("SP4 RPS series is required")
    original = Sp4OriginalRps(
        scope=doc.scope,
        document_id=doc.document_id,
        request_fingerprint=request.request_fingerprint,
        issuer_cnpj=doc.issuer.cnpj,
        issuer_ibge=ibge,
        competence_date=doc.competence_date,
        rps_number=str(reservation.number),
        rps_series=rps_series,
        gross_amount=doc.totals.gross_amount.amount,
        municipal_batch_id=expected_sp4_batch(ibge, reservation.number),
    )
    validate_sp4_original(request, original, reservation)
    return original


def validate_sp4_original(
    request: NfseAuthorizationRequest,
    original: Sp4OriginalRps,
    reservation: FiscalNumberReservation,
) -> None:
    """Prove RPS/lot/issuer/tenant match the SAME transaction's sequence."""
    if (
        not isinstance(request, NfseAuthorizationRequest)
        or not isinstance(original, Sp4OriginalRps)
        or not isinstance(reservation, FiscalNumberReservation)
    ):
        raise FiscalValidationError("SP4 requires reviewed canonical original RPS")
    doc = request.document
    issuer_ibge = doc.issuer.address.jurisdiction.municipality_ibge_code
    key = reservation.key
    if (
        key.model is not InternalFiscalSequenceStream.NFSE_RPS
        or key.host_namespace != doc.scope.host_namespace
        or key.tenant_id != doc.scope.tenant_id
        or key.unit_id != doc.scope.unit_id
        or key.environment != doc.scope.environment
        or doc.scope.environment is not FiscalEnvironment.HOMOLOGATION
        or not doc.scope.host_namespace
        or doc.issuer.address.jurisdiction.state_code != "SP"
        or issuer_ibge not in SP4_MUNICIPAL_PROVIDERS.values()
        or original.scope.identity_partition_key != doc.scope.identity_partition_key
        or original.document_id != doc.document_id
        or original.request_fingerprint != request.request_fingerprint
        or original.issuer_cnpj != doc.issuer.cnpj
        or original.issuer_ibge != issuer_ibge
        or original.competence_date != doc.competence_date
        or original.gross_amount != doc.totals.gross_amount.amount
        or original.rps_number != str(reservation.number)
        or original.municipal_batch_id
        != expected_sp4_batch(issuer_ibge, reservation.number)
    ):
        raise FiscalValidationError("SP4 RPS and archived fiscal source diverge")


def encode_sp4_original(
    request: NfseAuthorizationRequest,
    original: Sp4OriginalRps,
    reservation: FiscalNumberReservation,
) -> bytes:
    validate_sp4_original(request, original, reservation)
    payload = {
        "version": 1,
        "document_id": original.document_id,
        "request_fingerprint": original.request_fingerprint,
        "issuer_cnpj": original.issuer_cnpj.value,
        "issuer_ibge": original.issuer_ibge,
        "competence_date": original.competence_date.isoformat(),
        "gross_amount": str(original.gross_amount),
        "rps_number": original.rps_number,
        "rps_series": original.rps_series,
        "municipal_batch_id": original.municipal_batch_id,
        "sequence": {
            "series": reservation.key.series,
            "number": reservation.number,
            "token": reservation.reservation_token,
        },
    }
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


def decode_sp4_original(
    raw: bytes, *, scope: ExecutionScope, request: NfseAuthorizationRequest,
) -> Sp4OriginalRps:
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 8192:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "version", "document_id", "request_fingerprint", "issuer_cnpj",
            "issuer_ibge", "competence_date", "gross_amount", "rps_number",
            "rps_series", "municipal_batch_id", "sequence",
        } or data["version"] != 1:
            raise ValueError
        number = data["sequence"]
        if not isinstance(number, dict) or set(number) != {
            "series", "number", "token",
        }:
            raise ValueError
        key = FiscalSequenceKey.from_scope(
            scope, model=InternalFiscalSequenceStream.NFSE_RPS,
            series=number["series"],
        )
        reserved = FiscalNumberReservation(
            key=key, number=number["number"],
            reservation_token=number["token"],
        )
        token = hashlib.sha256(
            f"{key.canonical_material}|{reserved.number}".encode(),
        ).hexdigest()
        if reserved.reservation_token != token:
            raise ValueError
        original = Sp4OriginalRps(
            scope=scope,
            document_id=data["document_id"],
            request_fingerprint=data["request_fingerprint"],
            issuer_cnpj=Cnpj(data["issuer_cnpj"]),
            issuer_ibge=data["issuer_ibge"],
            competence_date=date.fromisoformat(data["competence_date"]),
            gross_amount=Decimal(data["gross_amount"]),
            rps_number=data["rps_number"],
            rps_series=data["rps_series"],
            municipal_batch_id=data["municipal_batch_id"],
        )
        validate_sp4_original(request, original, reserved)
    except (
        KeyError, ValueError, TypeError, FiscalValidationError,
        InvalidOperation, OverflowError, AttributeError,
    ):
        raise FiscalValidationError("Invalid or altered original SP4 fiscal archive") from None
    return original
