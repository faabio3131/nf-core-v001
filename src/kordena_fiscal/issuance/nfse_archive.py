"""Strict durable codec for provider-neutral prepared NFS-e requests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    Cpf,
    ExecutionScope,
    FiscalAddress,
    FiscalProfile,
    FiscalValidationError,
    Money,
    MunicipalRegistration,
    SourceReference,
    StateRegistration,
    TaxRegimeCode,
)

from .nfe_nfse import (
    NfseAuthorizationRequest,
    NfseCanonicalDocument,
    NfseServiceLine,
    NfseServiceTaker,
)

NFSE_PREPARED_MEDIA_TYPE = "application/vnd.nfcore.prepared-nfse.v1+json"


def encode_prepared_nfse(request: NfseAuthorizationRequest) -> bytes:
    """Encode only validated canonical fields; provider responses never enter the artifact."""
    if not isinstance(request, NfseAuthorizationRequest):
        raise FiscalValidationError("request must be NfseAuthorizationRequest")
    document = request.document
    issuer = document.issuer
    address = issuer.address
    payload = {
        "document_id": document.document_id,
        "source": [document.source.source_type, document.source.source_id],
        "issued_at": document.issued_at.isoformat(),
        "competence_date": document.competence_date.isoformat(),
        "issuer": {
            "profile_id": issuer.profile_id,
            "cnpj": issuer.cnpj.value,
            "legal_name": issuer.legal_name,
            "trade_name": issuer.trade_name,
            "tax_regime": int(issuer.tax_regime),
            "state_registration": {
                "state_code": issuer.state_registration.state_code,
                "number": issuer.state_registration.number,
                "exempt": issuer.state_registration.exempt,
            },
            "municipal_registration": (
                issuer.municipal_registration.number
                if issuer.municipal_registration is not None
                else None
            ),
            "primary_cnae": issuer.primary_cnae.value,
            "address": {
                "street": address.street,
                "number": address.number,
                "district": address.district,
                "municipality_name": address.municipality_name,
                "state_code": address.jurisdiction.state_code,
                "municipality_ibge_code": address.jurisdiction.municipality_ibge_code,
                "postal_code": address.postal_code,
                "complement": address.complement,
            },
            "effective_from": issuer.effective_from.isoformat(),
            "effective_to": issuer.effective_to.isoformat() if issuer.effective_to else None,
            "version": issuer.version,
        },
        "service_jurisdiction": {
            "state_code": document.service_jurisdiction.state_code,
            "municipality_ibge_code": document.service_jurisdiction.municipality_ibge_code,
        },
        "services": [
            {
                "line_number": line.line_number,
                "municipal_service_code": line.municipal_service_code,
                "description": line.description,
                "gross_amount": str(line.gross_amount.amount),
                "deduction_amount": str(line.deduction_amount.amount),
                "iss_amount": str(line.iss_amount.amount),
                "iss_withheld": line.iss_withheld,
                "national_taxation_code": line.national_taxation_code,
                "rule_version": line.rule_version,
                "source_normative": line.source_normative,
            }
            for line in document.services
        ],
        "service_taker_reference": document.service_taker_reference,
        "service_taker": None if document.service_taker is None else {
            "tax_id_type": "cnpj" if isinstance(document.service_taker.tax_id, Cnpj) else "cpf",
            "tax_id": document.service_taker.tax_id.value,
            "legal_name": document.service_taker.legal_name,
            "municipal_registration": document.service_taker.municipal_registration,
            "address": None if document.service_taker.address is None else {
                "street": document.service_taker.address.street,
                "number": document.service_taker.address.number,
                "district": document.service_taker.address.district,
                "municipality_name": document.service_taker.address.municipality_name,
                "state_code": document.service_taker.address.jurisdiction.state_code,
                "municipality_ibge_code": (
                    document.service_taker.address.jurisdiction.municipality_ibge_code
                ),
                "postal_code": document.service_taker.address.postal_code,
                "complement": document.service_taker.address.complement,
            },
        },
        "schema_version": document.schema_version,
        "idempotency_key": request.idempotency_key.value,
        "request_fingerprint": request.request_fingerprint,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise FiscalValidationError(f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise FiscalValidationError(f"{field} must be text")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def decode_prepared_nfse(content: bytes, *, scope: ExecutionScope) -> NfseAuthorizationRequest:
    """Rebuild and revalidate one request under the caller's already authorized scope."""
    if not isinstance(content, bytes) or not content:
        raise FiscalValidationError("prepared NFS-e content must be non-empty bytes")
    if not isinstance(scope, ExecutionScope):
        raise FiscalValidationError("scope must be ExecutionScope")
    try:
        data = json.loads(content)
        root = _mapping(data, "prepared NFS-e")
        issuer_data = _mapping(root["issuer"], "issuer")
        registration = _mapping(issuer_data["state_registration"], "state_registration")
        address_data = _mapping(issuer_data["address"], "address")
        address_jurisdiction = BrazilianJurisdiction(
            _text(address_data["state_code"], "address.state_code"),
            _text(address_data["municipality_ibge_code"], "address.municipality_ibge_code"),
        )
        issuer = FiscalProfile(
            profile_id=_text(issuer_data["profile_id"], "issuer.profile_id"),
            scope=scope,
            cnpj=Cnpj(_text(issuer_data["cnpj"], "issuer.cnpj")),
            legal_name=_text(issuer_data["legal_name"], "issuer.legal_name"),
            trade_name=_optional_text(issuer_data.get("trade_name"), "issuer.trade_name"),
            tax_regime=TaxRegimeCode(issuer_data["tax_regime"]),
            state_registration=StateRegistration(
                _text(registration["state_code"], "state_registration.state_code"),
                _optional_text(registration.get("number"), "state_registration.number"),
                registration["exempt"],
            ),
            municipal_registration=(
                MunicipalRegistration(
                    _text(
                        issuer_data["municipal_registration"],
                        "municipal_registration",
                    )
                )
                if issuer_data.get("municipal_registration") is not None
                else None
            ),
            primary_cnae=CnaeCode(_text(issuer_data["primary_cnae"], "issuer.primary_cnae")),
            address=FiscalAddress(
                street=_text(address_data["street"], "address.street"),
                number=_text(address_data["number"], "address.number"),
                district=_text(address_data["district"], "address.district"),
                municipality_name=_text(
                    address_data["municipality_name"], "address.municipality_name"
                ),
                jurisdiction=address_jurisdiction,
                postal_code=_text(address_data["postal_code"], "address.postal_code"),
                complement=_optional_text(address_data.get("complement"), "address.complement"),
            ),
            effective_from=datetime.fromisoformat(
                _text(issuer_data["effective_from"], "issuer.effective_from")
            ),
            effective_to=(
                datetime.fromisoformat(_text(issuer_data["effective_to"], "issuer.effective_to"))
                if issuer_data.get("effective_to") is not None
                else None
            ),
            version=issuer_data["version"],
        )
        source = root["source"]
        if not isinstance(source, list) or len(source) != 2:
            raise FiscalValidationError("source must contain type and id")
        jurisdiction_data = _mapping(root["service_jurisdiction"], "service_jurisdiction")
        raw_services = root["services"]
        if not isinstance(raw_services, list):
            raise FiscalValidationError("services must be a list")
        services = tuple(
            NfseServiceLine(
                line_number=item["line_number"],
                municipal_service_code=_text(item["municipal_service_code"], "service code"),
                description=_text(item["description"], "service description"),
                gross_amount=Money(Decimal(_text(item["gross_amount"], "gross_amount"))),
                deduction_amount=Money(
                    Decimal(_text(item["deduction_amount"], "deduction_amount"))
                ),
                iss_amount=Money(Decimal(_text(item["iss_amount"], "iss_amount"))),
                iss_withheld=item["iss_withheld"],
                national_taxation_code=_optional_text(
                    item.get("national_taxation_code"), "national_taxation_code"
                ),
                rule_version=item["rule_version"],
                source_normative=_text(item["source_normative"], "source_normative"),
            )
            for raw in raw_services
            for item in (_mapping(raw, "service"),)
        )
        taker = None
        if root.get("service_taker") is not None:
            raw_taker = _mapping(root["service_taker"], "service_taker")
            tax_id_text = _text(raw_taker["tax_id"], "service_taker.tax_id")
            kind = _text(raw_taker["tax_id_type"], "service_taker.tax_id_type")
            if kind not in {"cnpj", "cpf"}:
                raise FiscalValidationError("unsupported NFS-e taker tax ID type")
            raw_taker_address = raw_taker.get("address")
            taker_address = None
            if raw_taker_address is not None:
                ta = _mapping(raw_taker_address, "service_taker.address")
                taker_address = FiscalAddress(
                    street=_text(ta["street"], "taker.street"),
                    number=_text(ta["number"], "taker.number"),
                    district=_text(ta["district"], "taker.district"),
                    municipality_name=_text(ta["municipality_name"], "taker.municipality"),
                    jurisdiction=BrazilianJurisdiction(
                        _text(ta["state_code"], "taker.state_code"),
                        _text(ta["municipality_ibge_code"], "taker.municipality_ibge_code"),
                    ),
                    postal_code=_text(ta["postal_code"], "taker.postal_code"),
                    complement=_optional_text(ta.get("complement"), "taker.complement"),
                )
            taker = NfseServiceTaker(
                tax_id=Cnpj(tax_id_text) if kind == "cnpj" else Cpf(tax_id_text),
                legal_name=_text(raw_taker["legal_name"], "taker.legal_name"),
                address=taker_address,
                municipal_registration=_optional_text(
                    raw_taker.get("municipal_registration"), "taker.municipal_registration"
                ),
            )
        document = NfseCanonicalDocument(
            document_id=_text(root["document_id"], "document_id"),
            scope=scope,
            source=SourceReference(_text(source[0], "source type"), _text(source[1], "source id")),
            issued_at=datetime.fromisoformat(_text(root["issued_at"], "issued_at")),
            competence_date=date.fromisoformat(_text(root["competence_date"], "competence_date")),
            issuer=issuer,
            service_jurisdiction=BrazilianJurisdiction(
                _text(jurisdiction_data["state_code"], "service_jurisdiction.state_code"),
                _text(
                    jurisdiction_data["municipality_ibge_code"],
                    "service_jurisdiction.municipality_ibge_code",
                ),
            ),
            services=services,
            service_taker_reference=_optional_text(
                root.get("service_taker_reference"), "service_taker_reference"
            ),
            schema_version=root["schema_version"],
            service_taker=taker,
        )
        request = NfseAuthorizationRequest.build(document)
        if request.idempotency_key.value != _text(root["idempotency_key"], "idempotency_key"):
            raise FiscalValidationError("archived NFS-e idempotency key does not match")
        if request.request_fingerprint != _text(root["request_fingerprint"], "request_fingerprint"):
            raise FiscalValidationError("archived NFS-e fingerprint does not match")
        return request
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise FiscalValidationError("invalid prepared NFS-e artifact") from exc
