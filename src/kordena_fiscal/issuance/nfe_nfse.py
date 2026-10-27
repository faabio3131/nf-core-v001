"""Provider-neutral NF-e and NFS-e issuance contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from kordena_fiscal.documents import CanonicalFiscalDocument
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
)
from kordena_fiscal.gateway import (
    AuthorizationRequest,
    AuthorizationStatus,
    GatewayProviderMetadata,
)
from kordena_fiscal.lifecycle import (
    IdempotencyKey,
    build_issuance_key,
    build_request_fingerprint,
)
from kordena_fiscal.xml import NfeAccessKey


class NfeIssuanceContractError(FiscalDomainError):
    """Raised when a model-55 envelope conflicts with its canonical document."""


class NfseGatewayContractError(FiscalDomainError):
    """Raised when an NFS-e adapter violates the canonical gateway contract."""


def _required(value: str, field_name: str, max_length: int = 256) -> str:
    normalized = value.strip()
    if not normalized:
        raise FiscalValidationError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _optional(value: str | None, field_name: str, max_length: int = 256) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise FiscalValidationError(f"{field_name} exceeds max length {max_length}")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FiscalValidationError(f"{field_name} must be timezone-aware")
    return value


def _money(value: Money, field_name: str) -> Money:
    if not isinstance(value, Money):
        raise FiscalValidationError(f"{field_name} must be Money")
    if value.amount < 0:
        raise FiscalValidationError(f"{field_name} must be non-negative")
    return value


def _sha256_hex(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise FiscalValidationError(f"{field_name} must be SHA-256 hex")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise FiscalValidationError(f"{field_name} must be hexadecimal") from exc
    return normalized


@dataclass(frozen=True, slots=True)
class NfeIssuanceEnvelope:
    """Validated model-55 envelope reusing the existing signed-XML gateway."""

    document: CanonicalFiscalDocument
    access_key: NfeAccessKey
    signed_xml: bytes
    idempotency_key: IdempotencyKey
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.document, CanonicalFiscalDocument):
            raise FiscalValidationError("document must be CanonicalFiscalDocument")
        if self.document.document_kind is not FiscalDocumentKind.NFE:
            raise NfeIssuanceContractError("NF-e envelope requires document_kind NFE")
        if not isinstance(self.access_key, NfeAccessKey):
            raise FiscalValidationError("access_key must be NfeAccessKey")
        if self.access_key.model is not ElectronicInvoiceModel.NFE:
            raise NfeIssuanceContractError("NF-e envelope requires access-key model 55")
        if self.access_key.issuer_identifier != self.document.issuer.cnpj.value:
            raise NfeIssuanceContractError("NF-e access key issuer does not match document issuer")
        if not isinstance(self.signed_xml, bytes) or not self.signed_xml:
            raise FiscalValidationError("signed_xml must be non-empty bytes")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise FiscalValidationError("idempotency_key must be IdempotencyKey")
        expected_key = build_issuance_key(self.document)
        if self.idempotency_key != expected_key:
            raise NfeIssuanceContractError("NF-e idempotency key does not match document")
        normalized = _sha256_hex(self.request_fingerprint, "request_fingerprint")
        expected_fingerprint = build_request_fingerprint(self.document)
        if normalized != expected_fingerprint:
            raise NfeIssuanceContractError("NF-e request fingerprint does not match document")
        object.__setattr__(self, "request_fingerprint", normalized)

    @classmethod
    def build(
        cls,
        document: CanonicalFiscalDocument,
        access_key: NfeAccessKey,
        signed_xml: bytes,
    ) -> NfeIssuanceEnvelope:
        return cls(
            document=document,
            access_key=access_key,
            signed_xml=signed_xml,
            idempotency_key=build_issuance_key(document),
            request_fingerprint=build_request_fingerprint(document),
        )

    def to_gateway_request(self) -> AuthorizationRequest:
        return AuthorizationRequest(
            scope=self.document.scope,
            access_key=self.access_key,
            signed_xml=self.signed_xml,
            idempotency_key=self.idempotency_key,
            request_fingerprint=self.request_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class NfseServiceLine:
    """Frozen service-tax line without municipality/provider transport assumptions."""

    line_number: int
    municipal_service_code: str
    description: str
    gross_amount: Money
    deduction_amount: Money = Money.zero()
    iss_amount: Money = Money.zero()
    iss_withheld: bool = False
    national_taxation_code: str | None = None
    rule_version: int = 1
    source_normative: str = "external-rule-set"

    def __post_init__(self) -> None:
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool):
            raise FiscalValidationError("line_number must be an integer")
        if self.line_number < 1:
            raise FiscalValidationError("line_number must be >= 1")
        object.__setattr__(
            self,
            "municipal_service_code",
            _required(self.municipal_service_code, "municipal_service_code", 64),
        )
        object.__setattr__(
            self,
            "description",
            _required(self.description, "description", 1000),
        )
        _money(self.gross_amount, "gross_amount")
        _money(self.deduction_amount, "deduction_amount")
        _money(self.iss_amount, "iss_amount")
        if self.gross_amount.amount <= 0:
            raise FiscalValidationError("gross_amount must be greater than zero")
        if self.deduction_amount.amount > self.gross_amount.amount:
            raise FiscalValidationError("deduction_amount cannot exceed gross_amount")
        if self.iss_amount.amount > self.taxable_amount.amount:
            raise FiscalValidationError("iss_amount cannot exceed taxable_amount")
        if not isinstance(self.iss_withheld, bool):
            raise FiscalValidationError("iss_withheld must be bool")
        object.__setattr__(
            self,
            "national_taxation_code",
            _optional(self.national_taxation_code, "national_taxation_code", 64),
        )
        if not isinstance(self.rule_version, int) or isinstance(self.rule_version, bool):
            raise FiscalValidationError("rule_version must be an integer")
        if self.rule_version < 1:
            raise FiscalValidationError("rule_version must be >= 1")
        object.__setattr__(
            self,
            "source_normative",
            _required(self.source_normative, "source_normative", 512),
        )

    @property
    def taxable_amount(self) -> Money:
        return self.gross_amount - self.deduction_amount


@dataclass(frozen=True, slots=True)
class NfseDocumentTotals:
    gross_amount: Money
    deduction_amount: Money
    taxable_amount: Money
    iss_amount: Money


@dataclass(frozen=True, slots=True)
class NfseCanonicalDocument:
    """Canonical NFS-e service snapshot kept separate from merchandise-line semantics."""

    document_id: str
    scope: ExecutionScope
    source: SourceReference
    issued_at: datetime
    competence_date: date
    issuer: FiscalProfile
    service_jurisdiction: BrazilianJurisdiction
    services: tuple[NfseServiceLine, ...]
    service_taker_reference: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _required(self.document_id, "document_id", 128))
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        if not isinstance(self.source, SourceReference):
            raise FiscalValidationError("source must be SourceReference")
        _aware(self.issued_at, "issued_at")
        if not isinstance(self.competence_date, date):
            raise FiscalValidationError("competence_date must be date")
        if not isinstance(self.issuer, FiscalProfile):
            raise FiscalValidationError("issuer must be FiscalProfile")
        if self.issuer.scope.identity_partition_key != self.scope.identity_partition_key:
            raise FiscalValidationError("issuer and NFS-e document must share the same scope")
        if not self.issuer.is_effective_at(self.issued_at):
            raise FiscalValidationError("issuer fiscal profile is not effective at issued_at")
        if not isinstance(self.service_jurisdiction, BrazilianJurisdiction):
            raise FiscalValidationError("service_jurisdiction must be BrazilianJurisdiction")
        if self.service_jurisdiction.municipality_ibge_code is None:
            raise FiscalValidationError("NFS-e requires municipality_ibge_code")
        if not self.services:
            raise FiscalValidationError("NFS-e document requires at least one service line")
        if not all(isinstance(line, NfseServiceLine) for line in self.services):
            raise FiscalValidationError("services must contain NfseServiceLine values")
        line_numbers = [line.line_number for line in self.services]
        if len(line_numbers) != len(set(line_numbers)):
            raise FiscalValidationError("NFS-e line_number values must be unique")
        object.__setattr__(
            self,
            "service_taker_reference",
            _optional(self.service_taker_reference, "service_taker_reference", 256),
        )
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise FiscalValidationError("schema_version must be an integer")
        if self.schema_version < 1:
            raise FiscalValidationError("schema_version must be >= 1")

    @property
    def totals(self) -> NfseDocumentTotals:
        gross = sum((line.gross_amount.amount for line in self.services), Decimal("0"))
        deductions = sum(
            (line.deduction_amount.amount for line in self.services),
            Decimal("0"),
        )
        iss = sum((line.iss_amount.amount for line in self.services), Decimal("0"))
        return NfseDocumentTotals(
            gross_amount=Money(gross),
            deduction_amount=Money(deductions),
            taxable_amount=Money(gross - deductions),
            iss_amount=Money(iss),
        )


def build_nfse_issuance_key(document: NfseCanonicalDocument) -> IdempotencyKey:
    if not isinstance(document, NfseCanonicalDocument):
        raise FiscalValidationError("document must be NfseCanonicalDocument")
    material = {
        "tenant_id": document.scope.tenant_id,
        "unit_id": document.scope.unit_id,
        "environment": document.scope.environment.value,
        "source_type": document.source.source_type,
        "source_id": document.source.source_id,
        "document_kind": FiscalDocumentKind.NFSE.value,
        "operation": "issue",
    }
    if document.scope.host_namespace is not None:
        material["host_namespace"] = document.scope.host_namespace
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return IdempotencyKey(hashlib.sha256(encoded).hexdigest())


def build_nfse_request_fingerprint(document: NfseCanonicalDocument) -> str:
    if not isinstance(document, NfseCanonicalDocument):
        raise FiscalValidationError("document must be NfseCanonicalDocument")
    scope_payload = {
        "tenant_id": document.scope.tenant_id,
        "unit_id": document.scope.unit_id,
        "environment": document.scope.environment.value,
    }
    if document.scope.host_namespace is not None:
        scope_payload["host_namespace"] = document.scope.host_namespace
    payload = {
        "scope": scope_payload,
        "source": document.source.canonical_tuple,
        "issued_at": document.issued_at.isoformat(),
        "competence_date": document.competence_date.isoformat(),
        "issuer": {
            "cnpj": document.issuer.cnpj.value,
            "profile_id": document.issuer.profile_id,
            "version": document.issuer.version,
        },
        "service_jurisdiction": {
            "state_code": document.service_jurisdiction.state_code,
            "municipality_ibge_code": document.service_jurisdiction.municipality_ibge_code,
        },
        "service_taker_reference": document.service_taker_reference,
        "schema_version": document.schema_version,
        "services": [
            {
                "line_number": line.line_number,
                "municipal_service_code": line.municipal_service_code,
                "national_taxation_code": line.national_taxation_code,
                "description": line.description,
                "gross_amount": str(line.gross_amount.amount),
                "deduction_amount": str(line.deduction_amount.amount),
                "iss_amount": str(line.iss_amount.amount),
                "iss_withheld": line.iss_withheld,
                "rule_version": line.rule_version,
                "source_normative": line.source_normative,
            }
            for line in document.services
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class NfseAuthorizationRequest:
    document: NfseCanonicalDocument
    idempotency_key: IdempotencyKey
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.document, NfseCanonicalDocument):
            raise FiscalValidationError("document must be NfseCanonicalDocument")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise FiscalValidationError("idempotency_key must be IdempotencyKey")
        if self.idempotency_key != build_nfse_issuance_key(self.document):
            raise NfseGatewayContractError("NFS-e idempotency key does not match document")
        normalized = _sha256_hex(self.request_fingerprint, "request_fingerprint")
        if normalized != build_nfse_request_fingerprint(self.document):
            raise NfseGatewayContractError("NFS-e request fingerprint does not match document")
        object.__setattr__(self, "request_fingerprint", normalized)

    @classmethod
    def build(cls, document: NfseCanonicalDocument) -> NfseAuthorizationRequest:
        return cls(
            document=document,
            idempotency_key=build_nfse_issuance_key(document),
            request_fingerprint=build_nfse_request_fingerprint(document),
        )


@dataclass(frozen=True, slots=True)
class NfseAuthorizationResult:
    status: AuthorizationStatus
    scope: ExecutionScope
    document_id: str
    idempotency_key: IdempotencyKey
    request_fingerprint: str
    provider: GatewayProviderMetadata
    provider_request_id: str | None = None
    invoice_reference: str | None = None
    verification_code: str | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AuthorizationStatus):
            raise FiscalValidationError("status must be AuthorizationStatus")
        if not isinstance(self.scope, ExecutionScope):
            raise FiscalValidationError("scope must be ExecutionScope")
        object.__setattr__(self, "document_id", _required(self.document_id, "document_id", 128))
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise FiscalValidationError("idempotency_key must be IdempotencyKey")
        object.__setattr__(
            self,
            "request_fingerprint",
            _sha256_hex(self.request_fingerprint, "request_fingerprint"),
        )
        if not isinstance(self.provider, GatewayProviderMetadata):
            raise FiscalValidationError("provider must be GatewayProviderMetadata")
        for field_name in (
            "provider_request_id",
            "invoice_reference",
            "verification_code",
            "rejection_code",
            "rejection_message",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional(getattr(self, field_name), field_name, 512),
            )
        if self.status is AuthorizationStatus.AUTHORIZED:
            if self.invoice_reference is None:
                raise FiscalValidationError("authorized NFS-e requires invoice_reference")
            if self.rejection_code is not None or self.rejection_message is not None:
                raise FiscalValidationError("authorized NFS-e cannot contain rejection metadata")
        elif self.status is AuthorizationStatus.REJECTED:
            if self.invoice_reference is not None or self.verification_code is not None:
                raise FiscalValidationError("rejected NFS-e cannot contain invoice metadata")
            if self.rejection_code is None or self.rejection_message is None:
                raise FiscalValidationError(
                    "rejected NFS-e requires rejection_code and rejection_message"
                )
        else:
            if self.invoice_reference is not None or self.verification_code is not None:
                raise FiscalValidationError("pending NFS-e cannot contain invoice metadata")
            if self.rejection_code is not None or self.rejection_message is not None:
                raise FiscalValidationError("pending NFS-e cannot contain rejection metadata")


class NfseGateway(Protocol):
    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult: ...


class NfseQueryGateway(Protocol):
    """Read-only recovery boundary; implementations must never retransmit issuance."""

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult: ...


def _validated_nfse_result(
    request: NfseAuthorizationRequest, result: object
) -> NfseAuthorizationResult:
    if not isinstance(result, NfseAuthorizationResult):
        raise NfseGatewayContractError("gateway must return NfseAuthorizationResult")
    if result.scope != request.document.scope:
        raise NfseGatewayContractError("NFS-e gateway returned a different scope")
    if result.document_id != request.document.document_id:
        raise NfseGatewayContractError("NFS-e gateway returned a different document_id")
    if result.idempotency_key != request.idempotency_key:
        raise NfseGatewayContractError("NFS-e gateway returned a different idempotency key")
    if result.request_fingerprint != request.request_fingerprint:
        raise NfseGatewayContractError("NFS-e gateway returned a different fingerprint")
    return result


class NfseGatewayClient:
    """Fail-closed boundary around national, municipal or provider NFS-e adapters."""

    def __init__(self, gateway: NfseGateway) -> None:
        self._gateway = gateway

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        if not isinstance(request, NfseAuthorizationRequest):
            raise FiscalValidationError("request must be NfseAuthorizationRequest")
        return _validated_nfse_result(request, self._gateway.authorize(request))


class NfseQueryClient:
    """Validated read-only NFS-e recovery client with no issuance fallback."""

    def __init__(self, gateway: NfseQueryGateway) -> None:
        self._gateway = gateway

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        if not isinstance(request, NfseAuthorizationRequest):
            raise FiscalValidationError("request must be NfseAuthorizationRequest")
        return _validated_nfse_result(request, self._gateway.query(request))
