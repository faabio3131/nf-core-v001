"""Provider-neutral NF-e and NFS-e issuance contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from kordena_fiscal.documents import CanonicalFiscalDocument
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    Cpf,
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalAddress,
    FiscalDocumentKind,
    FiscalDomainError,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
    TaxRegimeCode,
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
    nbs_code: str | None = None
    municipal_taxation_detail: str | None = None

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
        if self.nbs_code is not None and (
            type(self.nbs_code) is not str
            or not self.nbs_code.isascii()
            or len(self.nbs_code) != 9
            or not self.nbs_code.isdecimal()
        ):
            raise FiscalValidationError("NBS service code must have exactly nine ASCII digits")
        if self.municipal_taxation_detail is not None and (
            type(self.municipal_taxation_detail) is not str
            or not self.municipal_taxation_detail.isascii()
            or not self.municipal_taxation_detail.isdecimal()
            or len(self.municipal_taxation_detail) != 3
        ):
            raise FiscalValidationError("cTribMun requires three reviewed ASCII digits")
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
class NfseForeignAddress:
    """National DPS endExt fields; no invented Brazilian municipality authority."""

    country_code: str
    postal_code: str
    city: str
    region: str
    street: str
    number: str
    district: str
    complement: str | None = None

    def __post_init__(self) -> None:
        country = _required(self.country_code, "taker.country_code", 2)
        if (
            len(country) != 2 or not country.isascii()
            or not country.isalpha() or country != country.upper()
        ):
            raise FiscalValidationError("Foreign country must use two uppercase ISO letters")
        if country == "BR":
            raise FiscalValidationError("Brazilian taker address requires FiscalAddress")
        object.__setattr__(self, "country_code", country)
        for field_name, limit in (
            ("postal_code", 11), ("city", 60), ("region", 60),
            ("street", 255), ("number", 60), ("district", 60),
        ):
            object.__setattr__(
                self, field_name,
                _required(getattr(self, field_name), f"taker.{field_name}", limit),
            )
        object.__setattr__(
            self, "complement", _optional(self.complement, "taker.complement", 156)
        )


@dataclass(frozen=True, slots=True)
class NfseServiceTaker:
    """Single verified DPS toma identity: CPF/CNPJ, NIF or official cNaoNIF."""

    tax_id: Cnpj | Cpf | None
    legal_name: str
    address: FiscalAddress | NfseForeignAddress | None = None
    municipal_registration: str | None = None
    nif: str | None = None
    no_nif_reason: str | None = None

    def __post_init__(self) -> None:
        if self.tax_id is not None and not isinstance(self.tax_id, (Cnpj, Cpf)):
            raise FiscalValidationError("NFS-e taker requires a validated tax identity")
        if sum((
            self.tax_id is not None, self.nif is not None, self.no_nif_reason is not None,
        )) != 1:
            raise FiscalValidationError("NFS-e taker requires exactly one tax identity")
        if self.nif is not None:
            object.__setattr__(self, "nif", _required(self.nif, "taker.nif", 40))
        if self.no_nif_reason is not None and self.no_nif_reason not in {"0", "1", "2"}:
            raise FiscalValidationError("NFS-e cNaoNIF must be official code 0, 1 or 2")
        if self.address is not None and not isinstance(
            self.address, (FiscalAddress, NfseForeignAddress)
        ):
            raise FiscalValidationError("NFS-e taker address is invalid")
        if isinstance(self.address, NfseForeignAddress) and self.tax_id is not None:
            raise FiscalValidationError("Foreign taker address requires NIF or cNaoNIF")
        if isinstance(self.address, FiscalAddress) and self.tax_id is None:
            raise FiscalValidationError("NIF/cNaoNIF taker must use foreign address")
        object.__setattr__(
            self, "legal_name", _required(self.legal_name, "taker.legal_name", 300)
        )
        object.__setattr__(
            self, "municipal_registration",
            _optional(self.municipal_registration, "taker.municipal_registration", 15),
        )


@dataclass(frozen=True, slots=True)
class NfseDeductionDocument:
    """Operator-reviewed national fiscal document and allocated deduction.

    The two official profiles have different adjustment taxonomies: both
    codes are explicit reviewed facts, never inferred by the builder.
    """

    kind: str
    access_key: str
    legacy_code: str
    nt009_code: str
    issued_on: date
    eligible_amount: Money
    applied_amount: Money
    evidence_sha256: str
    description: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("nfe", "nfse"):
            raise FiscalValidationError("Unsupported documentary deduction kind")
        width = 44 if self.kind == "nfe" else 50
        if not isinstance(self.access_key, str) or not re.fullmatch(
            rf"[0-9]{{{width}}}", self.access_key,
        ):
            raise FiscalValidationError("Invalid documentary deduction access key")
        if self.legacy_code not in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "99"}:
            raise FiscalValidationError("Invalid legacy documentary deduction code")
        if self.nt009_code not in {
            "2", "5", "6", "7", "8", "9", "99",
            "101", "102", "103", "104", "105", "199",
        }:
            raise FiscalValidationError("Invalid NT009 documentary adjustment code")
        if type(self.issued_on) is not date:
            raise FiscalValidationError("Documentary deduction date is required")
        _money(self.eligible_amount, "eligible_amount")
        _money(self.applied_amount, "applied_amount")
        if not Decimal("0") < self.applied_amount.amount <= self.eligible_amount.amount:
            raise FiscalValidationError("Documentary deduction exceeds eligible value")
        if not isinstance(self.evidence_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.evidence_sha256,
        ):
            raise FiscalValidationError("Documentary deduction evidence digest is required")
        if self.description is not None:
            object.__setattr__(self, "description", _required(
                self.description, "deduction.description", 150,
            ))
        if (self.legacy_code == "99" or self.nt009_code in {"99", "199"}) and not self.description:
            raise FiscalValidationError("Other documentary deduction requires description")

    def as_payload(self) -> dict[str, str | None]:
        return {
            "kind": self.kind, "access_key": self.access_key,
            "legacy_code": self.legacy_code, "nt009_code": self.nt009_code,
            "issued_on": self.issued_on.isoformat(),
            "eligible_amount": str(self.eligible_amount.amount),
            "applied_amount": str(self.applied_amount.amount),
            "evidence_sha256": self.evidence_sha256, "description": self.description,
        }

    @classmethod
    def from_payload(cls, data: object) -> NfseDeductionDocument:
        if not isinstance(data, dict) or set(data) != {
            "kind", "access_key", "legacy_code", "nt009_code", "issued_on",
            "eligible_amount", "applied_amount", "evidence_sha256", "description",
        } or any(
            not isinstance(value, str)
            for key, value in data.items() if key != "description"
        ):
            raise FiscalValidationError("Invalid reviewed documentary deduction fields")
        if data["description"] is not None and not isinstance(data["description"], str):
            raise FiscalValidationError("Invalid documentary deduction description")
        for key in ("eligible_amount", "applied_amount"):
            if not re.fullmatch(r"(?:0|[1-9][0-9]{0,12})\.[0-9]{2}", data[key]):
                raise FiscalValidationError("Documentary deduction requires exact BRL cents")
        try:
            issued_on = date.fromisoformat(data["issued_on"])
            if issued_on.isoformat() != data["issued_on"]:
                raise ValueError("date format")
            return cls(
                kind=data["kind"], access_key=data["access_key"],
                legacy_code=data["legacy_code"], nt009_code=data["nt009_code"],
                issued_on=issued_on, eligible_amount=Money(Decimal(data["eligible_amount"])),
                applied_amount=Money(Decimal(data["applied_amount"])),
                evidence_sha256=data["evidence_sha256"], description=data["description"],
            )
        except (ValueError, ArithmeticError) as exc:
            raise FiscalValidationError("Invalid reviewed documentary deduction") from exc


@dataclass(frozen=True, slots=True)
class NfseNationalTaxTreatment:
    """Reviewed National DPS 1.01 fiscal treatment for one effective period.

    These codes are taken from the pinned official TSRegEspTrib, TSTribISSQN
    and TSRegimeApuracaoSimpNac tables. Browser input is not their authority;
    the caller must supply an approved, effective-dated domain decision.
    """

    iss_taxation_code: str
    special_regime_code: str
    normative_reference: str
    rule_version: int
    effective_from: date
    effective_to: date | None = None
    simples_assessment_code: str | None = None
    result_country_code: str | None = None
    immunity_type_code: str | None = None
    municipal_benefit_id: str | None = None
    policy_id: str | None = None
    policy_sha256: str | None = None
    iss_rate: str | None = None
    complementary_information: str | None = None
    deduction_source_type: str | None = None
    deduction_source_id: str | None = None
    deduction_documents: tuple[NfseDeductionDocument, ...] = ()

    def __post_init__(self) -> None:
        if (self.policy_id is None) != (self.policy_sha256 is None):
            raise FiscalValidationError("National policy identity and digest must be paired")
        if self.policy_id is not None:
            if not isinstance(self.policy_id, str) or not 1 <= len(self.policy_id) <= 128:
                raise FiscalValidationError("National policy identity is invalid")
            digest = self.policy_sha256
            if not isinstance(digest, str) or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise FiscalValidationError("National policy SHA-256 is invalid")
        if not isinstance(self.deduction_documents, tuple) or not all(
            isinstance(item, NfseDeductionDocument) for item in self.deduction_documents
        ):
            raise FiscalValidationError("Documentary deductions must be immutable reviewed records")
        if self.deduction_documents:
            if (
                self.policy_id is None or self.iss_taxation_code != "1"
                or not isinstance(self.deduction_source_type, str)
                or not isinstance(self.deduction_source_id, str)
                or not self.deduction_source_type.strip() or not self.deduction_source_id.strip()
                or len(self.deduction_source_type) > 128 or len(self.deduction_source_id) > 256
                or len(self.deduction_documents) > 100
            ):
                raise FiscalValidationError("Documentary deductions require scoped reviewed policy")
            keys = [(item.kind, item.access_key) for item in self.deduction_documents]
            if len(set(keys)) != len(keys):
                raise FiscalValidationError("Duplicated documentary deduction")
        elif self.deduction_source_type is not None or self.deduction_source_id is not None:
            raise FiscalValidationError("Documentary source requires reviewed documents")
        if self.iss_taxation_code not in {"1", "2", "3", "4"}:
            raise FiscalValidationError("National ISSQN taxation requires official code 1..4")
        if self.special_regime_code not in {"0", "1", "2", "3", "4", "5", "6", "9"}:
            raise FiscalValidationError("National NFS-e special regime code is not official")
        # SEFIN E0172: immunity/export/non-incidence use regEspTrib=0.
        if self.iss_taxation_code != "1" and self.special_regime_code != "0":
            raise FiscalValidationError("Non-taxable national ISS cannot use special regime")
        if self.municipal_benefit_id is not None and (
            type(self.municipal_benefit_id) is not str
            or len(self.municipal_benefit_id) != 14
            or not self.municipal_benefit_id.isascii()
            or not self.municipal_benefit_id.isdecimal()
            or self.iss_taxation_code != "1"
        ):
            raise FiscalValidationError("Reviewed municipal benefit ID is invalid")
        if self.iss_rate is not None and (
            not isinstance(self.iss_rate, str)
            or not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})\.[0-9]{2}", self.iss_rate)
            or not Decimal("0.00") < Decimal(self.iss_rate) <= Decimal("100.00")
            or self.iss_taxation_code != "1"
            or self.special_regime_code == "2"
        ):
            raise FiscalValidationError("Reviewed ISS rate must be explicit and applicable")
        if self.complementary_information is not None:
            message = self.complementary_information
            if (
                not isinstance(message, str) or not message.strip()
                or len(message) > 2000
                or any(ord(char) < 32 and char not in "\t\n\r" for char in message)
            ):
                raise FiscalValidationError("Reviewed NFS-e complementary information invalid")
        if self.simples_assessment_code not in {None, "1", "2", "3"}:
            raise FiscalValidationError("National Simples assessment requires code 1..3")
        if type(self.effective_from) is not date:
            raise FiscalValidationError("National tax decision requires effective_from date")
        if self.effective_to is not None and (
            type(self.effective_to) is not date or self.effective_to <= self.effective_from
        ):
            raise FiscalValidationError("National tax decision effective_to is invalid")
        if type(self.rule_version) is not int or self.rule_version < 1:
            raise FiscalValidationError("National tax decision rule_version must be >= 1")
        object.__setattr__(
            self, "normative_reference",
            _required(self.normative_reference, "tax_treatment.normative_reference", 512),
        )
        if self.iss_taxation_code == "3":
            country = self.result_country_code
            if (
                not isinstance(country, str) or len(country) != 2
                or not country.isascii() or not country.isalpha()
                or country != country.upper() or country == "BR"
            ):
                raise FiscalValidationError("Exported service requires reviewed ISO result country")
        elif self.result_country_code is not None:
            raise FiscalValidationError("Result country is only valid for exported services")
        if self.iss_taxation_code == "2":
            if self.immunity_type_code not in {"0", "1", "2", "3", "4", "5"}:
                raise FiscalValidationError("ISS immunity requires official reviewed immunity type")
        elif self.immunity_type_code is not None:
            raise FiscalValidationError("Immunity type is only valid for immune services")


@dataclass(frozen=True, slots=True)
class NfseNationalSubstitution:
    """Reviewed original NFS-e reference for a replacement DPS, never a second event."""

    original_document_id: str
    original_invoice_reference: str
    reason_code: str
    reason_description: str
    approval_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "original_document_id",
            _required(self.original_document_id, "original_document_id", 128),
        )
        key = self.original_invoice_reference
        if (
            not isinstance(key, str) or len(key) != 50
            or not key.isascii() or not key.isdecimal()
            or self.reason_code not in {"01", "02", "03", "04", "05", "99"}
            or not isinstance(self.reason_description, str)
            or not 15 <= len(self.reason_description.strip()) <= 255
            or any(ord(char) < 32 for char in self.reason_description)
            or not isinstance(self.approval_reference, str)
            or not 8 <= len(self.approval_reference.strip()) <= 128
            or not self.approval_reference.isascii()
        ):
            raise FiscalValidationError("National substitution needs reviewed original and reason")


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
    service_taker: NfseServiceTaker | None = None
    dps_series: int = 1
    dps_number: int | None = None
    national_tax_treatment: NfseNationalTaxTreatment | None = None
    national_substitution: NfseNationalSubstitution | None = None

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
        if self.service_taker is not None and not isinstance(self.service_taker, NfseServiceTaker):
            raise FiscalValidationError("service_taker must be NfseServiceTaker")
        treatment = self.national_tax_treatment
        if treatment is not None and not isinstance(treatment, NfseNationalTaxTreatment):
            raise FiscalValidationError("national_tax_treatment must be a reviewed decision")
        documents = treatment.deduction_documents if treatment is not None else ()
        documentary_required = self.issuer.address.jurisdiction.municipality_ibge_code == "3106200"
        documentary_codes = frozenset({
            "0702", "0705", "0901", "1001", "1002", "1003",
            "1004", "1005", "1008", "1706",
        })
        if documentary_required and any(
            line.deduction_amount.amount > 0
            and (line.national_taxation_code or "")[:4] in documentary_codes
            for line in self.services
        ) and not documents:
            raise FiscalValidationError("BH documentary deduction requires reviewed evidence")
        if documents:
            assert treatment is not None
            if (
                len(self.services) != 1
                or treatment.deduction_source_type != self.source.source_type
                or treatment.deduction_source_id != self.source.source_id
                or any(item.issued_on > self.competence_date for item in documents)
                or sum((item.applied_amount.amount for item in documents), Decimal("0"))
                != self.services[0].deduction_amount.amount
            ):
                raise FiscalValidationError("Documentary deduction differs from reviewed source or value")
        # MEI pays fixed ISS in DAS-SIMEI; this document must never assess,
        # highlight or withhold per-invoice ISS or claim a special ISS regime.
        # Single domain invariant applies to Portal and all DPS callers.
        if self.issuer.tax_regime is TaxRegimeCode.MEI:
            if treatment is not None and treatment.special_regime_code != "0":
                raise FiscalValidationError("MEI cannot claim special ISS regime")
            if any(
                line.iss_amount.amount > 0 or line.iss_withheld for line in self.services
            ):
                raise FiscalValidationError("MEI cannot highlight or withhold ISS")
        if treatment is not None:
            if not isinstance(treatment, NfseNationalTaxTreatment):
                raise FiscalValidationError("national_tax_treatment must be a reviewed decision")
            if self.competence_date < treatment.effective_from or (
                treatment.effective_to is not None
                and self.competence_date >= treatment.effective_to
            ):
                raise FiscalValidationError(
                    "National tax treatment is not effective for competence"
                )
            if (
                treatment.simples_assessment_code is not None
                and self.issuer.tax_regime not in {
                    TaxRegimeCode.SIMPLES_NACIONAL,
                    TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
                }
            ):
                raise FiscalValidationError("Simples assessment conflicts with issuer tax regime")
            benefit_id = treatment.municipal_benefit_id
            if benefit_id is not None:
                jurisdiction_ibge = self.service_jurisdiction.municipality_ibge_code
                if not benefit_id.startswith(jurisdiction_ibge or ""):
                    raise FiscalValidationError("Municipal benefit belongs to another city")
                if jurisdiction_ibge == "3106200":
                    approved = (
                        "31062000200004" if self.scope.environment.value == "homologation"
                        else "31062000200002"
                    )
                    if benefit_id != approved or treatment.special_regime_code != "0":
                        raise FiscalValidationError("BH cooperative benefit requires exact ID")
            no_iss_highlight = treatment.special_regime_code == "2" or (
                self.issuer.address.jurisdiction.municipality_ibge_code == "3106200"
                and treatment.special_regime_code == "1"
            )
            if no_iss_highlight and any(
                line.iss_amount.amount > 0 or line.iss_withheld for line in self.services
            ):
                raise FiscalValidationError(
                    "Reviewed special regime cannot highlight or withhold ISS"
                )
            if treatment.iss_taxation_code != "1" and any(
                line.iss_amount.amount > 0 or line.iss_withheld for line in self.services
            ):
                raise FiscalValidationError(
                    "Non-taxable ISS treatment cannot charge or withhold ISS"
                )
            if treatment.iss_rate is not None:
                if not self.requires_reviewed_iss_rate:
                    raise FiscalValidationError(
                        "ISS rate conflicts with reviewed no-highlight regime"
                    )
                rate = Decimal(treatment.iss_rate)
                for line in self.services:
                    expected_iss = (line.taxable_amount.amount * rate / 100).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP,
                    )
                    if line.iss_amount.amount != expected_iss:
                        raise FiscalValidationError("ISS amount differs from reviewed rate")
        if (
            self.national_substitution is not None
            and (
                not isinstance(self.national_substitution, NfseNationalSubstitution)
                or self.national_substitution.original_document_id == self.document_id
            )
        ):
            raise FiscalValidationError("Invalid canonical national substitution reference")
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise FiscalValidationError("schema_version must be an integer")
        if self.schema_version < 1:
            raise FiscalValidationError("schema_version must be >= 1")
        if (
            not isinstance(self.dps_series, int)
            or isinstance(self.dps_series, bool)
            or not 1 <= self.dps_series <= 99_999
        ):
            raise FiscalValidationError("DPS series must be between 1 and 99999")
        if self.dps_number is not None and (
            not isinstance(self.dps_number, int)
            or isinstance(self.dps_number, bool)
            or not 1 <= self.dps_number <= 999_999_999_999_999
        ):
            raise FiscalValidationError("DPS serial number is invalid")

    @property
    def requires_reviewed_iss_rate(self) -> bool:
        """Use the existing National ordinary-taxable/no-highlight boundary."""
        treatment = self.national_tax_treatment
        return (
            treatment is not None
            and treatment.iss_taxation_code == "1"
            and self.issuer.tax_regime is not TaxRegimeCode.MEI
            and treatment.special_regime_code != "2"
            and not (
                treatment.special_regime_code == "1"
                and self.issuer.address.jurisdiction.municipality_ibge_code == "3106200"
            )
        )

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
    scope_payload: dict[str, str] = {
        "tenant_id": document.scope.tenant_id,
        "unit_id": document.scope.unit_id,
        "environment": document.scope.environment.value,
    }
    if document.scope.host_namespace is not None:
        scope_payload["host_namespace"] = document.scope.host_namespace
    payload: dict[str, object] = {
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
                **({"nbs_code": line.nbs_code} if line.nbs_code is not None else {}),
                **({"municipal_taxation_detail": line.municipal_taxation_detail}
                   if line.municipal_taxation_detail is not None else {}),
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
    if document.national_tax_treatment is not None:
        treatment = document.national_tax_treatment
        treatment_payload: dict[str, object] = {
            "iss_taxation_code": treatment.iss_taxation_code,
            "special_regime_code": treatment.special_regime_code,
            "simples_assessment_code": treatment.simples_assessment_code,
            "result_country_code": treatment.result_country_code,
            "immunity_type_code": treatment.immunity_type_code,
            "normative_reference": treatment.normative_reference,
            "rule_version": treatment.rule_version,
            "effective_from": treatment.effective_from.isoformat(),
            "effective_to": (
                treatment.effective_to.isoformat() if treatment.effective_to else None
            ),
        }
        if treatment.policy_id is not None:
            treatment_payload["policy_id"] = treatment.policy_id
            treatment_payload["policy_sha256"] = treatment.policy_sha256
        if treatment.iss_rate is not None:
            treatment_payload["iss_rate"] = treatment.iss_rate
        if treatment.complementary_information is not None:
            treatment_payload["complementary_information"] = treatment.complementary_information
        if treatment.deduction_documents:
            treatment_payload["deduction_source_type"] = treatment.deduction_source_type
            treatment_payload["deduction_source_id"] = treatment.deduction_source_id
            treatment_payload["deduction_documents"] = [
                item.as_payload() for item in treatment.deduction_documents
            ]
        payload["national_tax_treatment"] = treatment_payload
    if document.service_taker is not None:
        taker = document.service_taker
        address = taker.address
        taker_payload: dict[str, object] = {
            "tax_id_type": (
                "cnpj" if isinstance(taker.tax_id, Cnpj)
                else "cpf" if isinstance(taker.tax_id, Cpf)
                else "nif" if taker.nif is not None else "cNaoNIF"
            ),
            "tax_id": taker.tax_id.value if taker.tax_id is not None else None,
            "nif": taker.nif,
            "no_nif_reason": taker.no_nif_reason,
            "legal_name": taker.legal_name,
            "municipal_registration": taker.municipal_registration,
        }
        if isinstance(address, FiscalAddress):
            taker_payload["address"] = {
                "type": "national", "street": address.street, "number": address.number,
                "district": address.district, "municipality_name": address.municipality_name,
                "state_code": address.jurisdiction.state_code,
                "municipality_ibge_code": address.jurisdiction.municipality_ibge_code,
                "postal_code": address.postal_code, "complement": address.complement,
            }
        elif isinstance(address, NfseForeignAddress):
            taker_payload["address"] = {
                "type": "foreign", "country_code": address.country_code,
                "postal_code": address.postal_code, "city": address.city,
                "region": address.region, "street": address.street,
                "number": address.number, "district": address.district,
                "complement": address.complement,
            }
        else:
            taker_payload["address"] = None
        payload["service_taker"] = taker_payload
    if document.national_substitution is not None:
        linked = document.national_substitution
        payload["national_substitution"] = {
            "original_document_id": linked.original_document_id,
            "original_invoice_reference": linked.original_invoice_reference,
            "reason_code": linked.reason_code,
            "reason_description": linked.reason_description,
            "approval_reference": linked.approval_reference,
        }
    # Preserve the historic fingerprint of unnumbered/archived requests.
    # On new preparations the UoW supplies a legally reserved DPS serial,
    # and this serial is bound to the immutable request fingerprint.
    if document.dps_number is not None:
        payload["dps_numbering"] = {
            "series": document.dps_series,
            "number": document.dps_number,
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
class NfseRejectionDetail:
    """Lossless bounded provider rejection evidence; never expose raw text to Portal."""

    code: str
    origin: str
    raw_message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required(self.code, "rejection.code", 512))
        object.__setattr__(self, "origin", _required(self.origin, "rejection.origin", 128))
        if (
            not isinstance(self.raw_message, str)
            or not self.raw_message.strip()
            or len(self.raw_message) > 32768
        ):
            raise FiscalValidationError(
                "rejection.raw_message must be non-empty and at most 32768 characters"
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
    invoice_number: str | None = None
    authorized_xml: bytes | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None
    rejections: tuple[NfseRejectionDetail, ...] = ()

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
            "invoice_number",
            "rejection_code",
            "rejection_message",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional(
                    getattr(self, field_name), field_name,
                    32768 if field_name == "rejection_message" else 512,
                ),
            )
        if (
            not isinstance(self.rejections, tuple)
            or len(self.rejections) > 32
            or any(not isinstance(item, NfseRejectionDetail) for item in self.rejections)
        ):
            raise FiscalValidationError("NFS-e rejections require at most 32 typed details")
        if self.authorized_xml is not None and (
            not isinstance(self.authorized_xml, bytes)
            or not 0 < len(self.authorized_xml) <= 2 * 1024 * 1024
        ):
            raise FiscalValidationError("Invalid authorized NFS-e XML evidence")
        if self.status is AuthorizationStatus.AUTHORIZED:
            if self.invoice_reference is None:
                raise FiscalValidationError("authorized NFS-e requires invoice_reference")
            if (
                self.rejection_code is not None
                or self.rejection_message is not None
                or self.rejections
            ):
                raise FiscalValidationError("authorized NFS-e cannot contain rejection metadata")
        elif self.status is AuthorizationStatus.REJECTED:
            if (
                self.invoice_reference is not None or self.verification_code is not None
                or self.invoice_number is not None or self.authorized_xml is not None
            ):
                raise FiscalValidationError("rejected NFS-e cannot contain invoice metadata")
            if self.rejection_code is None or self.rejection_message is None:
                raise FiscalValidationError(
                    "rejected NFS-e requires rejection_code and rejection_message"
                )
            if self.rejections and (
                self.rejections[0].code != self.rejection_code
                or self.rejections[0].raw_message.strip() != self.rejection_message
            ):
                raise FiscalValidationError("NFS-e first rejection disagrees with summary")
        else:
            if (
                self.invoice_reference is not None or self.verification_code is not None
                or self.invoice_number is not None or self.authorized_xml is not None
            ):
                raise FiscalValidationError("pending NFS-e cannot contain invoice metadata")
            if (
                self.rejection_code is not None
                or self.rejection_message is not None
                or self.rejections
            ):
                raise FiscalValidationError("pending NFS-e cannot contain rejection metadata")

    def normalized_rejections(self) -> tuple[NfseRejectionDetail, ...]:
        """Retain every structured provider error or a compatible legacy summary."""
        if self.status is not AuthorizationStatus.REJECTED:
            return ()
        if self.rejections:
            return self.rejections
        assert self.rejection_code is not None and self.rejection_message is not None
        return (NfseRejectionDetail(
            code=self.rejection_code,
            origin=self.provider.provider_name,
            raw_message=self.rejection_message,
        ),)


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

    def validate_pre_dispatch(self, request: NfseAuthorizationRequest) -> None:
        """Run an optional trusted adapter's pure checks before claiming transmission."""
        validate = getattr(self._gateway, "validate_pre_dispatch", None)
        if validate is not None:
            if not callable(validate):
                raise FiscalValidationError("Invalid NFS-e pre-dispatch validator")
            validate(request)

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
