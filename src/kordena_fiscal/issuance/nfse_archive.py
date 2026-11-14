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
    NfseForeignAddress,
    NfseNationalTaxTreatment,
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
            "tax_id_type": (
                "cnpj" if isinstance(document.service_taker.tax_id, Cnpj)
                else "cpf" if isinstance(document.service_taker.tax_id, Cpf)
                else "nif" if document.service_taker.nif is not None else "cNaoNIF"
            ),
            "tax_id": (
                document.service_taker.tax_id.value
                if document.service_taker.tax_id is not None else None
            ),
            "nif": document.service_taker.nif,
            "no_nif_reason": document.service_taker.no_nif_reason,
            "legal_name": document.service_taker.legal_name,
            "municipal_registration": document.service_taker.municipal_registration,
            "address": (
                None if document.service_taker.address is None else (
                    {
                        "type": "foreign",
                        "country_code": document.service_taker.address.country_code,
                        "postal_code": document.service_taker.address.postal_code,
                        "city": document.service_taker.address.city,
                        "region": document.service_taker.address.region,
                        "street": document.service_taker.address.street,
                        "number": document.service_taker.address.number,
                        "district": document.service_taker.address.district,
                        "complement": document.service_taker.address.complement,
                    } if isinstance(document.service_taker.address, NfseForeignAddress) else {
                        "type": "national",
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
                    }
                )
            ),
        },
        "schema_version": document.schema_version,
        "national_tax_treatment": (
            None if document.national_tax_treatment is None else {
                "iss_taxation_code": document.national_tax_treatment.iss_taxation_code,
                "special_regime_code": document.national_tax_treatment.special_regime_code,
                "simples_assessment_code": (
                    document.national_tax_treatment.simples_assessment_code
                ),
                "result_country_code": document.national_tax_treatment.result_country_code,
                "immunity_type_code": document.national_tax_treatment.immunity_type_code,
                "normative_reference": document.national_tax_treatment.normative_reference,
                "rule_version": document.national_tax_treatment.rule_version,
                "effective_from": document.national_tax_treatment.effective_from.isoformat(),
                "effective_to": (
                    document.national_tax_treatment.effective_to.isoformat()
                    if document.national_tax_treatment.effective_to else None
                ),
            }
        ),
        "dps_series": document.dps_series,
        "dps_number": document.dps_number,
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
            kind = _text(raw_taker["tax_id_type"], "service_taker.tax_id_type")
            tax_id: Cnpj | Cpf | None = None
            nif = None
            no_nif_reason = None
            if kind == "cnpj":
                tax_id = Cnpj(_text(raw_taker["tax_id"], "service_taker.tax_id"))
            elif kind == "cpf":
                tax_id = Cpf(_text(raw_taker["tax_id"], "service_taker.tax_id"))
            elif kind == "nif":
                nif = _text(raw_taker["nif"], "service_taker.nif")
            elif kind == "cNaoNIF":
                no_nif_reason = _text(raw_taker["no_nif_reason"], "service_taker.no_nif_reason")
            else:
                raise FiscalValidationError("Unsupported NFS-e taker tax identity")
            taker_address: FiscalAddress | NfseForeignAddress | None = None
            if raw_taker.get("address") is not None:
                ta = _mapping(raw_taker["address"], "service_taker.address")
                address_type = _text(ta["type"], "taker.address.type")
                if address_type == "foreign":
                    taker_address = NfseForeignAddress(
                        country_code=_text(ta["country_code"], "taker.country_code"),
                        postal_code=_text(ta["postal_code"], "taker.postal_code"),
                        city=_text(ta["city"], "taker.city"),
                        region=_text(ta["region"], "taker.region"),
                        street=_text(ta["street"], "taker.street"),
                        number=_text(ta["number"], "taker.number"),
                        district=_text(ta["district"], "taker.district"),
                        complement=_optional_text(ta.get("complement"), "taker.complement"),
                    )
                elif address_type == "national":
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
                else:
                    raise FiscalValidationError("Unsupported NFS-e taker address type")
            taker = NfseServiceTaker(
                tax_id=tax_id,
                legal_name=_text(raw_taker["legal_name"], "taker.legal_name"),
                address=taker_address,
                municipal_registration=_optional_text(
                    raw_taker.get("municipal_registration"), "taker.municipal_registration"
                ),
                nif=nif,
                no_nif_reason=no_nif_reason,
            )
        treatment = None
        if root.get("national_tax_treatment") is not None:
            decision = _mapping(root["national_tax_treatment"], "national_tax_treatment")
            treatment = NfseNationalTaxTreatment(
                iss_taxation_code=_text(
                    decision["iss_taxation_code"], "tax_treatment.iss_taxation_code"
                ),
                special_regime_code=_text(
                    decision["special_regime_code"], "tax_treatment.special_regime_code"
                ),
                normative_reference=_text(
                    decision["normative_reference"], "tax_treatment.normative_reference"
                ),
                rule_version=decision["rule_version"],
                effective_from=date.fromisoformat(_text(
                    decision["effective_from"], "tax_treatment.effective_from"
                )),
                effective_to=(
                    date.fromisoformat(_text(
                        decision["effective_to"], "tax_treatment.effective_to"
                    )) if decision.get("effective_to") is not None else None
                ),
                simples_assessment_code=_optional_text(
                    decision.get("simples_assessment_code"),
                    "tax_treatment.simples_assessment_code",
                ),
                result_country_code=_optional_text(
                    decision.get("result_country_code"), "tax_treatment.result_country_code",
                ),
                immunity_type_code=_optional_text(
                    decision.get("immunity_type_code"), "tax_treatment.immunity_type_code",
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
            dps_series=root.get("dps_series", 1),
            dps_number=root.get("dps_number"),
            national_tax_treatment=treatment,
        )
        request = NfseAuthorizationRequest.build(document)
        if request.idempotency_key.value != _text(root["idempotency_key"], "idempotency_key"):
            raise FiscalValidationError("archived NFS-e idempotency key does not match")
        if request.request_fingerprint != _text(root["request_fingerprint"], "request_fingerprint"):
            raise FiscalValidationError("archived NFS-e fingerprint does not match")
        return request
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise FiscalValidationError("invalid prepared NFS-e artifact") from exc
