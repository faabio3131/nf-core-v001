"""Barueri PMB004 operator startup on the existing NFCore A1 and fiscal UoW.

One nonsecret, explicitly configured on-host manifest holds taxpayer-specific
reviewed rules and SHA-256-pinned official contracts. This file neither invents
an emitter nor selects a taxpayer. Issuance is always resolved by the durable
control-plane provider binding and original fiscal identity.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lxml import etree

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import Cnpj, FiscalAddress, FiscalValidationError, TaxRegimeCode
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.barueri_pmb004_cancellation_builder import (
    build_barueri_cancellation_remittance,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import BarueriRpsBatch
from kordena_fiscal.gateway.barueri_pmb004_record_builder import (
    BarueriPmb004IssueFields,
    BarueriPmb004Recipient,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .barueri_operational_composition import (
    BarueriTrustedRuntimePorts,
    build_barueri_trusted_transport,
)
from .config import RuntimeConfigurationError
from .sp4_municipal_request_factories import (
    build_barueri_pmb004_issue_remittance_factory,
)

_ENV = "NFCORE_BARUERI_PMB004_CONFIG_PATH"
_LAYOUT = "PMB004-v4.4"
_LIMIT = 2_097_152
_XML_PROOF = frozenset({
    "issuer_cnpj", "invoice_number", "verification_code", "invoice_reference",
    "rps_number", "gross_amount", "invoice_issued_on", "invoice_series",
})
_ISSUER_KEYS = frozenset({
    "tenant_id", "unit_id", "issuer_cnpj", "profile_id", "profile_version",
    "tax_regime", "municipal_registration", "effective_from", "effective_through",
    "canonical_service_code", "pmb004_service_code",
    "service_location_code", "public_way_code", "nbs_code",
    "operation_indicator", "tax_classification", "ibs_cbs_status",
    "simples_assessment", "municipal_note_series", "recipient_emails",
    "personal_use", "recipient_differs",
    "non_base_allowed",
})


def _object(obj: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise RuntimeConfigurationError("Invalid Barueri " + label)
    return obj


def _pinned_file(folder: Path, obj: object) -> bytes:
    spec = _object(obj, frozenset({"file", "sha256"}), "official artifact")
    name, digest = spec["file"], spec["sha256"]
    if (
        not isinstance(name, str) or Path(name).name != name
        or not name or name.startswith(".")
        or not isinstance(digest, str) or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise RuntimeConfigurationError("Unsafe reviewed Barueri artifact reference")
    file = folder / name
    if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= _LIMIT:
        raise RuntimeConfigurationError("Pinned Barueri artifact unavailable")
    content = file.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeConfigurationError("Pinned Barueri contract hash mismatch")
    return content


def _xml(raw: bytes) -> etree._Element:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
        raise FiscalValidationError("Missing official Barueri XML")
    try:
        node = etree.fromstring(
            raw, parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise FiscalValidationError("Malformed official Barueri XML") from None
    if bool(getattr(node.getroottree().docinfo, "doctype", "")):
        raise FiscalValidationError("Official Barueri XML cannot contain DTD")
    return node


@dataclass(frozen=True, slots=True)
class _IssuerReview:
    tenant_id: str
    unit_id: str
    issuer_cnpj: str
    profile_id: str
    profile_version: int
    tax_regime: int
    municipal_registration: str
    effective_from: date
    effective_through: date | None
    canonical_service_code: str
    pmb004_service_code: str
    service_location_code: str
    public_way_code: str
    nbs_code: str
    operation_indicator: str
    tax_classification: str
    ibs_cbs_status: str
    simples_assessment: str
    personal_use: str
    recipient_differs: str
    municipal_note_series: str
    recipient_emails: Mapping[str, str]
    non_base_allowed: bool

    @classmethod
    def load(cls, obj: object) -> _IssuerReview:
        row = _object(obj, _ISSUER_KEYS, "taxpayer reviewed policy")
        try:
            if not all(
                isinstance(row[name], str) and 0 < len(row[name].strip()) <= 128
                and row[name] == row[name].strip()
                for name in ("tenant_id", "unit_id", "issuer_cnpj", "profile_id",
                             "municipal_registration", "canonical_service_code",
                             "pmb004_service_code", "service_location_code",
                             "public_way_code", "nbs_code", "operation_indicator",
                             "tax_classification", "ibs_cbs_status")
            ):
                raise ValueError
            if (
                type(row["profile_version"]) is not int or row["profile_version"] < 1
                or type(row["tax_regime"]) is not int
                or row["tax_regime"] not in {regime.value for regime in TaxRegimeCode}
                or type(row["non_base_allowed"]) is not bool
                or not isinstance(row["recipient_emails"], dict)
                or not isinstance(row["simples_assessment"], str)
                or not isinstance(row["municipal_note_series"], str)
                or row["personal_use"] not in ("0", "1")
                or row["recipient_differs"] not in ("0", "1")
            ):
                raise ValueError
            Cnpj(row["issuer_cnpj"])
            if (
                len(row["municipal_registration"]) != 7
                or not row["municipal_registration"].isascii()
                or not row["municipal_registration"].isalnum()
                or not row["pmb004_service_code"].isascii()
                or len(row["pmb004_service_code"]) != 9
                or not row["pmb004_service_code"].isdigit()
                or not row["nbs_code"].isascii()
                or len(row["nbs_code"]) != 9 or not row["nbs_code"].isdigit()
                or len(row["operation_indicator"]) != 6
                or not row["operation_indicator"].isascii()
                or not row["operation_indicator"].isdigit()
                or len(row["tax_classification"]) != 6
                or not row["tax_classification"].isascii()
                or not row["tax_classification"].isdigit()
                or len(row["ibs_cbs_status"]) != 3
                or row["tax_classification"][:3] != row["ibs_cbs_status"]
                or row["service_location_code"] not in ("1", "2")
                or row["public_way_code"] not in ("1", "2")
                or len(row["municipal_note_series"]) > 5
            ):
                raise ValueError
            for taxid, email in row["recipient_emails"].items():
                if (
                    not isinstance(taxid, str) or not taxid.isascii()
                    or not taxid.isdigit() or len(taxid) not in (11, 14)
                    or not isinstance(email, str) or not 3 <= len(email) <= 152
                    or "@" not in email or any(ord(c) < 32 for c in email)
                ):
                    raise ValueError
            start = date.fromisoformat(row["effective_from"])
            end = (
                date.fromisoformat(row["effective_through"])
                if row["effective_through"] is not None else None
            )
            if end is not None and end < start:
                raise ValueError
        except (KeyError, ValueError, TypeError, FiscalValidationError):
            raise RuntimeConfigurationError("Invalid scoped Barueri taxpayer policy") from None
        return cls(
            **{
                **row,
                "effective_from": start,
                "effective_through": end,
            },
        )

    def applies(self, request: NfseAuthorizationRequest) -> bool:
        doc = request.document
        issuer = doc.issuer
        return (
            doc.scope.tenant_id == self.tenant_id
            and doc.scope.unit_id == self.unit_id
            and issuer.cnpj.value == self.issuer_cnpj
            and issuer.profile_id == self.profile_id
            and issuer.version == self.profile_version
            and issuer.tax_regime.value == self.tax_regime
            and issuer.municipal_registration is not None
            and issuer.municipal_registration.number == self.municipal_registration
            and issuer.address.jurisdiction.municipality_ibge_code == "3505708"
            and self.effective_from <= doc.competence_date
            and (self.effective_through is None
                 or doc.competence_date <= self.effective_through)
        )


@dataclass(frozen=True, slots=True)
class BarueriReviewedStartup:
    """Pinned PMB004 layout 4.4 (28/05/2026) and scoped tax mappings."""

    policies: tuple[_IssuerReview, ...]
    invoice_schema: etree.XMLSchema
    invoice_tags: Mapping[str, str]
    layout_sha256: str
    return_layout_sha256: str

    @classmethod
    def load(cls, manifest_path: str) -> BarueriReviewedStartup:
        file = Path(manifest_path)
        if not file.is_absolute() or not file.is_file() or file.stat().st_size > 131_072:
            raise RuntimeConfigurationError("Barueri config needs existing absolute manifest")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (ValueError, OSError, UnicodeError):
            raise RuntimeConfigurationError("Invalid Barueri operator manifest") from None
        row = _object(data, frozenset({
            "mode", "layout", "rps_layout", "return_layout",
            "invoice_xsd", "invoice_tags", "issuers",
        }), "operator manifest")
        if row["mode"] != "reviewed-homologation" or row["layout"] != _LAYOUT:
            raise RuntimeConfigurationError("Barueri PMB004 reviewed mode mismatch")
        rps = _pinned_file(file.parent, row["rps_layout"])
        ret = _pinned_file(file.parent, row["return_layout"])
        invoice_schema_bytes = _pinned_file(file.parent, row["invoice_xsd"])
        try:
            schema = etree.XMLSchema(_xml(invoice_schema_bytes))
        except (etree.XMLSchemaParseError, FiscalValidationError):
            raise RuntimeConfigurationError("Invalid pinned Barueri invoice schema") from None
        tags = _object(row["invoice_tags"], _XML_PROOF, "invoice XML identifiers")
        if not all(
            isinstance(tag, str) and 0 < len(tag) <= 128
            and tag.replace("_", "").isalnum()
            for tag in tags.values()
        ) or len(set(tags.values())) != len(tags):
            raise RuntimeConfigurationError("Barueri XML proof tags must be unique")
        issuers = row["issuers"]
        if not isinstance(issuers, list) or not issuers:
            raise RuntimeConfigurationError("Barueri needs reviewed issuer policies")
        reviews = tuple(_IssuerReview.load(item) for item in issuers)
        identity = [
            (p.tenant_id, p.unit_id, p.issuer_cnpj, p.profile_id, p.effective_from)
            for p in reviews
        ]
        if len(identity) != len(set(identity)):
            raise RuntimeConfigurationError("Duplicate reviewed Barueri issuer policies")
        return cls(
            reviews, schema, tags,
            hashlib.sha256(rps).hexdigest(), hashlib.sha256(ret).hexdigest(),
        )

    def _review(self, request: NfseAuthorizationRequest) -> _IssuerReview:
        reviews = [p for p in self.policies if p.applies(request)]
        if len(reviews) != 1:
            raise FiscalValidationError("Exactly one reviewed Barueri issuer policy required")
        return reviews[0]

    def build_ports(
        self, application: FiscalApplicationService, vault: EncryptedA1Vault,
    ) -> BarueriTrustedRuntimePorts:
        def fiscal_policy(request: NfseAuthorizationRequest) -> None:
            self._review(request)

        def fields(
            request: NfseAuthorizationRequest, original: Sp4OriginalRps,
        ) -> BarueriPmb004IssueFields:
            policy = self._review(request)
            doc = request.document
            if (
                original.issuer_cnpj != doc.issuer.cnpj
                or original.issuer_ibge != "3505708"
                or doc.service_jurisdiction != doc.issuer.address.jurisdiction
                or len(doc.services) != 1
                or doc.services[0].municipal_service_code != policy.canonical_service_code
                or doc.service_taker is None
                or not isinstance(doc.service_taker.address, FiscalAddress)
                or doc.service_taker.tax_id is None
            ):
                raise FiscalValidationError(
                    "Barueri requires matched approved service, location and recipient"
                )
            taker = doc.service_taker
            if taker is None or taker.tax_id is None:
                raise FiscalValidationError("Barueri taxpayer recipient is missing")
            src = doc.issuer.address
            target = taker.address
            assert isinstance(target, FiscalAddress)
            recipient_email = policy.recipient_emails.get(taker.tax_id.value, "")
            if len(taker.tax_id.value) == 14 and not recipient_email:
                raise FiscalValidationError("Barueri requires reviewed business recipient email")
            deduction = doc.services[0].deduction_amount.amount
            if deduction and not policy.non_base_allowed:
                raise FiscalValidationError("Barueri requires reviewed non-base deduction")
            simples = "3" if doc.issuer.tax_regime in (
                TaxRegimeCode.SIMPLES_NACIONAL,
                TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            ) else "2" if doc.issuer.tax_regime is TaxRegimeCode.MEI else "1"
            return BarueriPmb004IssueFields(
                service_code=policy.pmb004_service_code,
                service_location_code=policy.service_location_code,
                public_way_code=policy.public_way_code,
                street=src.street, street_number=src.number,
                street_complement=src.complement or "",
                district=src.district, city=src.municipality_name,
                state=src.jurisdiction.state_code, postal_code=src.postal_code,
                recipient=BarueriPmb004Recipient(
                    tax_id=taker.tax_id.value, legal_name=taker.legal_name,
                    street=target.street, street_number=target.number,
                    complement=target.complement or "", district=target.district,
                    city=target.municipality_name,
                    state=target.jurisdiction.state_code,
                    postal_code=target.postal_code,
                    city_ibge=target.jurisdiction.municipality_ibge_code or "",
                    email=recipient_email,
                ),
                nbs_code=policy.nbs_code,
                operation_indicator=policy.operation_indicator,
                tax_classification=policy.tax_classification,
                ibs_cbs_status=policy.ibs_cbs_status,
                simples_status=simples,
                simples_assessment=policy.simples_assessment,
                municipal_note_series=policy.municipal_note_series,
                personal_use=policy.personal_use,
                recipient_differs=policy.recipient_differs,
                federal_retentions=(),
                non_base_amount=deduction if deduction else None,
            )

        def validate_fixed_width(data: bytes) -> None:
            if not isinstance(data, bytes) or not 0 < len(data) <= _LIMIT:
                raise FiscalValidationError("Invalid pinned Barueri PMB004 remittance")
            rows = data.split(b"\r\n")
            if rows[-1] != b"" or len(rows) < 5:
                raise FiscalValidationError("Barueri PMB004 requires complete CRLF records")
            expected = {b"1": 25, b"2": 1970, b"3": 18, b"4": 531, b"5": 697, b"9": 38}
            if any(row[:1] not in expected or len(row) != expected[row[:1]]
                   for row in rows[:-1]):
                raise FiscalValidationError("Barueri PMB004 record width differs from layout")
            if rows[0][:1] != b"1" or rows[-2][:1] != b"9":
                raise FiscalValidationError("Barueri PMB004 fiscal batch boundaries invalid")

        def verify_identity(source: Sp4OriginalRps, batch: BarueriRpsBatch) -> None:
            if (
                source.issuer_ibge != "3505708"
                or batch.scope.identity_partition_key
                != source.scope.identity_partition_key
                or batch.issuer_cnpj != source.issuer_cnpj
                or batch.remittance != source.municipal_batch_id
                or batch.rps_bytes.split(b"\r\n")[1][15:25]
                != source.rps_number.zfill(10).encode("ascii")
            ):
                raise FiscalValidationError("Barueri PMB004 RPS identity mismatch")
            validate_fixed_width(batch.rps_bytes)

        def xml_values(raw: bytes) -> dict[str, str]:
            root = _xml(raw)
            if not self.invoice_schema.validate(root):
                raise FiscalValidationError("Barueri original invoice fails pinned official XSD")
            values: dict[str, str] = {}
            for field, tag in self.invoice_tags.items():
                matching = [
                    element.text.strip() for element in root.iter()
                    if isinstance(element.tag, str)
                    and etree.QName(element).localname == tag
                    and element.text is not None
                ]
                if len(matching) != 1:
                    raise FiscalValidationError("Barueri official XML evidence tag ambiguous")
                values[field] = matching[0]
            if not values["invoice_number"].isdigit():
                raise FiscalValidationError("Barueri official invoice number invalid")
            if not values["rps_number"].isdigit():
                raise FiscalValidationError("Barueri official RPS number invalid")
            if len(values["invoice_series"]) > 5:
                raise FiscalValidationError("Barueri official invoice series invalid")
            try:
                date.fromisoformat(values["invoice_issued_on"])
            except ValueError:
                raise FiscalValidationError("Barueri official issue date invalid") from None
            return values

        def official_xml(invoice: Sp4VerifiedInvoice) -> None:
            values = xml_values(invoice.authorized_xml)
            expected = {
                "issuer_cnpj": invoice.issuer_cnpj.value,
                "invoice_number": invoice.invoice_number,
                "verification_code": invoice.verification_code,
                "invoice_reference": invoice.invoice_reference,
                "rps_number": invoice.rps_number,
                "gross_amount": str(invoice.gross_amount),
            }
            for field, value in expected.items():
                if field in ("invoice_number", "rps_number"):
                    if int(values[field]) != int(value):
                        raise FiscalValidationError("Barueri official number differs")
                elif field == "gross_amount":
                    try:
                        amount = Decimal(values[field])
                    except InvalidOperation:
                        raise FiscalValidationError("Invalid Barueri official amount") from None
                    if amount != invoice.gross_amount:
                        raise FiscalValidationError("Barueri official amount differs")
                elif values[field] != value:
                    raise FiscalValidationError("Barueri official invoice identity differs")

        def decode_official_invoice(
            raw: bytes, original: Sp4OriginalRps,
        ) -> Sp4VerifiedInvoice:
            values = xml_values(raw)
            evidence = Sp4VerifiedInvoice(
                issuer_cnpj=original.issuer_cnpj,
                issuer_ibge=original.issuer_ibge,
                competence_date=original.competence_date,
                rps_number=original.rps_number,
                rps_series=original.rps_series,
                gross_amount=original.gross_amount,
                invoice_number=values["invoice_number"],
                verification_code=values["verification_code"],
                invoice_reference=values["invoice_reference"],
                authorized_xml=raw,
            )
            official_xml(evidence)
            return evidence

        transport = build_barueri_trusted_transport(
            application=application, vault=vault, validate_pmb004=validate_fixed_width,
        )
        build_remittance = build_barueri_pmb004_issue_remittance_factory(
            resolve_issue_fields=fields,
            resolve_municipal_registration=lambda scope, cnpj: next(
                (p.municipal_registration for p in self.policies
                 if p.tenant_id == scope.tenant_id
                 and p.unit_id == scope.unit_id and p.issuer_cnpj == cnpj),
                "",
            ),
        )
        def prepare_cancellation_event(
            request: NfseAuthorizationRequest, original: Sp4OriginalRps,
            issued: Sp4VerifiedInvoice, remittance: str,
            reason_code: str, description: str, occurred_at: datetime,
            replacement_number: str | None,
            replacement_request: NfseAuthorizationRequest | None,
            replacement_source: Sp4OriginalRps | None,
            substitution_justification_code: str | None,
        ) -> BarueriRpsBatch:
            issued_values = xml_values(issued.authorized_xml)
            official_xml(issued)
            original_batch = build_remittance(request, original)
            verify_identity(original, original_batch)
            records = original_batch.rps_bytes.split(b"\r\n")
            original_detail = records[1]
            rtc_detail = next(
                (row for row in records if row.startswith(b"4")), None,
            )
            if rtc_detail is None:
                raise FiscalValidationError("Barueri original RTC record is missing")
            replacement_detail: bytes | None = None
            replacement_rtc: bytes | None = None
            replacement_amount: Decimal | None = None
            if reason_code == "03":
                if (
                    replacement_source is None or replacement_request is None
                    or replacement_number != replacement_source.rps_number
                    or replacement_request.document.issuer.cnpj != original.issuer_cnpj
                    or replacement_request.document.competence_date
                    != original.competence_date
                    or replacement_request.document.issuer.tax_regime
                    != request.document.issuer.tax_regime
                ):
                    raise FiscalValidationError("Barueri replacement is not canonical")
                fresh = build_remittance(replacement_request, replacement_source)
                verify_identity(replacement_source, fresh)
                rows = fresh.rps_bytes.split(b"\r\n")
                replacement_detail = rows[1]
                replacement_rtc = next(
                    (row for row in rows if row.startswith(b"4")), None,
                )
                if replacement_rtc is None:
                    raise FiscalValidationError("Barueri replacement RTC is missing")
                replacement_amount = replacement_source.gross_amount
            elif any(value is not None for value in (
                replacement_request, replacement_source, replacement_number,
            )):
                raise FiscalValidationError("Barueri simple cancel cannot replace RPS")
            local = occurred_at.astimezone(ZoneInfo("America/Sao_Paulo"))
            return build_barueri_cancellation_remittance(
                original=original, issued=issued,
                regime=request.document.issuer.tax_regime,
                municipal_registration=original_batch.municipal_registration,
                event_remittance=remittance, event_day=local.date(),
                event_time=local.time().replace(tzinfo=None),
                invoice_issued_on=date.fromisoformat(issued_values["invoice_issued_on"]),
                reason_code=reason_code, description=description,
                original_rps_detail=original_detail,
                reviewed_rtc_record=rtc_detail,
                replacement_rps_number=replacement_number,
                substitution_justification_code=substitution_justification_code,
                replacement_rps_detail=replacement_detail,
                replacement_rtc_record=replacement_rtc,
                replacement_gross_amount=replacement_amount,
                invoice_series=issued_values["invoice_series"],
                human_approved=True,
            )

        def validate_original(source: Sp4OriginalRps) -> None:
            if (
                not isinstance(source, Sp4OriginalRps)
                or source.issuer_ibge != "3505708"
                or source.municipal_batch_id is None
                or len(source.municipal_batch_id) != 11
            ):
                raise FiscalValidationError("Missing durable Barueri original RPS")

        return BarueriTrustedRuntimePorts(
            transport=transport, build_remittance=build_remittance,
            verify_fixed_width_rps_identity=verify_identity,
            fiscal_issuer_policy=fiscal_policy,
            validate_prepared_rps=validate_original,
            verify_official_invoice_xml=official_xml,
            # Interpretation occurs in the asynchronous remittance/return bridge;
            # the first OK200 never promotes an invoice.
            interpret_official_result=lambda receipt, request, source: Sp4ProviderOutcome(
                status=AuthorizationStatus.PENDING,
                provider_request_id=receipt.remittance_protocol,
            ),
            decode_official_invoice=decode_official_invoice,
            prepare_cancellation_event=prepare_cancellation_event,
        )


def build_barueri_port_builder_from_environ(
    environ: Mapping[str, str], *, vault: EncryptedA1Vault | None,
) -> Callable[[FiscalApplicationService], BarueriTrustedRuntimePorts] | None:
    """Provision Barueri only from a reviewed manifest, never from discovery."""
    manifest = environ.get(_ENV, "").strip()
    if not manifest:
        return None
    if vault is None:
        raise RuntimeConfigurationError("Barueri requires the canonical encrypted A1 vault")
    startup = BarueriReviewedStartup.load(manifest)
    return lambda application: startup.build_ports(application, vault)
