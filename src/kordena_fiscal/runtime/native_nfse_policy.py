"""Resolve deployed, reviewed national service decisions; never infer fiscal treatment."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from kordena_fiscal.domain import ExecutionScope, FiscalDocumentKind, FiscalValidationError
from kordena_fiscal.issuance.nfe_nfse import (
    NfseCanonicalDocument,
    NfseDeductionDocument,
    NfseForeignAddress,
    NfseNationalTaxTreatment,
)

from .native_sale_policy import _serialized_policy_install, sale_policy_key
from .sale_facts import _unique

POLICY_ENV = "NFCORE_NFSE_FISCAL_POLICY_ROOT"
_SELECTOR = frozenset({
    "issuer_profile_id", "issuer_profile_version", "issuer_cnpj", "issuer_tax_regime",
    "issuer_municipality_ibge", "service_state_code", "service_municipality_ibge",
    "national_taxation_code", "municipal_service_code", "taker_country", "iss_withheld",
    "nbs_code", "municipal_taxation_detail", "source_normative", "rule_version",
})
_TREATMENT = frozenset({
    "iss_taxation_code", "special_regime_code", "normative_reference", "rule_version",
    "effective_from", "effective_to", "simples_assessment_code", "result_country_code",
    "immunity_type_code",
})


@dataclass(frozen=True)
class ReviewedNfsePolicy:
    policy_id: str
    version: int
    digest: str
    content: bytes
    treatment: NfseNationalTaxTreatment


def _text(value: object, limit: int = 128) -> bool:
    return isinstance(value, str) and value == value.strip() and 0 < len(value) <= limit


def _treatment(data: Any, identity: str, digest: str) -> NfseNationalTaxTreatment:
    if (
        not isinstance(data, dict)
        or not _TREATMENT <= set(data)
        or not set(data) <= _TREATMENT | {
            "municipal_benefit_id", "iss_rate", "complementary_information",
            "deduction_source_type", "deduction_source_id", "deduction_documents",
        }
    ):
        raise ValueError("national treatment fields")
    converted = dict(data)
    if "deduction_documents" in converted:
        raw_documents = converted["deduction_documents"]
        if not isinstance(raw_documents, list) or not 1 <= len(raw_documents) <= 100:
            raise ValueError("deduction documents")
        converted["deduction_documents"] = tuple(
            NfseDeductionDocument.from_payload(item) for item in raw_documents
        )
    for key in ("effective_from", "effective_to"):
        value = converted[key]
        if key == "effective_to" and value is None:
            continue
        if not isinstance(value, str):
            raise ValueError("decision validity")
        converted[key] = date.fromisoformat(value)
        if converted[key].isoformat() != value:
            raise ValueError("decision validity format")
    if not _text(data["normative_reference"], 512):
        raise ValueError("normative reference")
    return NfseNationalTaxTreatment(**converted, policy_id=identity, policy_sha256=digest)


def _validate_selector(selector: Any) -> None:
    if not isinstance(selector, dict) or set(selector) != _SELECTOR:
        raise ValueError("national selector fields")
    for key, value in selector.items():
        if key in {"issuer_profile_version", "rule_version", "issuer_tax_regime"}:
            if type(value) is not int or value < 1:
                raise ValueError("selector version or regime")
        elif key == "iss_withheld":
            if type(value) is not bool:
                raise ValueError("selector withholding")
        elif key in {"nbs_code", "municipal_taxation_detail"} and value is None:
            continue
        elif not _text(value, 512 if key == "source_normative" else 128):
            raise ValueError("selector text")
    for key, width in (
        ("issuer_cnpj", 14), ("issuer_municipality_ibge", 7),
        ("service_municipality_ibge", 7), ("national_taxation_code", 6),
        ("nbs_code", 9), ("municipal_taxation_detail", 3),
    ):
        value = selector[key]
        if value is not None and not re.fullmatch(rf"[0-9]{{{width}}}", value):
            raise ValueError("selector fiscal code")
    if not re.fullmatch(r"[A-Z]{2}", selector["taker_country"]):
        raise ValueError("selector taker country")


def resolve_national_treatment(
    environ: Mapping[str, str], scope: ExecutionScope, facts: Mapping[str, Any],
    competence: date, *, source_type: str | None = None, source_id: str | None = None,
) -> ReviewedNfsePolicy | None:
    """Only an absent setting permits the existing ordinary-taxable path.

    Every configured file is bounded, pinned and scope-bound. Rules match exact
    reviewed facts with no wildcard or implicit precedence. Multiple matches
    fail, including duplicate identities. Export is never inferred from country.
    """
    if POLICY_ENV not in environ:
        return None
    try:
        root = Path(environ[POLICY_ENV])
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("policy root")
        name = sale_policy_key(scope, FiscalDocumentKind.NFSE)
        source, pin = root / (name + ".json"), root / (name + ".sha256")
        if source.is_symlink() or pin.is_symlink():
            raise ValueError("policy symlink")
        with pin.open("rb") as stream:
            encoded_digest = stream.read(66)
        if not re.fullmatch(rb"[0-9a-f]{64}\n?", encoded_digest):
            raise ValueError("policy pin")
        digest = encoded_digest.decode().strip()
        with source.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("policy integrity")
        data = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "policy_id", "version", "host_namespace", "tenant_id",
            "unit_id", "environment", "document_kind", "rules",
        }:
            raise ValueError("policy fields")
        if (
            type(data["schema_version"]) is not int or data["schema_version"] != 1
            or type(data["version"]) is not int or data["version"] < 1
            or not _text(data["policy_id"], 63)
            or data["host_namespace"] != scope.host_namespace
            or data["tenant_id"] != scope.tenant_id or data["unit_id"] != scope.unit_id
            or data["environment"] != scope.environment.value
            or data["document_kind"] != FiscalDocumentKind.NFSE.value
            or not isinstance(data["rules"], list) or not 1 <= len(data["rules"]) <= 500
        ):
            raise ValueError("policy identity or scope")
        matches = []
        identities = set()
        deduction_keys: set[tuple[str, ...]] = set()
        deduction_hashes: set[str] = set()
        for rule in data["rules"]:
            if not isinstance(rule, dict) or set(rule) != {"rule_id", "selector", "treatment"}:
                raise ValueError("rule fields")
            if not _text(rule["rule_id"], 63) or rule["rule_id"] in identities:
                raise ValueError("rule identity")
            identities.add(rule["rule_id"])
            _validate_selector(rule["selector"])
            treatment = _treatment(
                rule["treatment"], data["policy_id"] + ":" + rule["rule_id"], digest,
            )
            for item in treatment.deduction_documents:
                document_key = item.allocation_identity
                if document_key in deduction_keys or item.evidence_sha256 in deduction_hashes:
                    raise ValueError("Deduction document duplicated in reviewed policy")
                deduction_keys.add(document_key)
                deduction_hashes.add(item.evidence_sha256)
            # PBH BHISS notice (updated 14 Aug 2026) lists only 1,2,4,5,6,9;
            # zero means no special regime. Code 3 is not admitted by BH.
            if (
                rule["selector"]["issuer_municipality_ibge"] == "3106200"
                and treatment.special_regime_code not in {"0", "1", "2", "4", "5", "6", "9"}
            ):
                raise ValueError("Belo Horizonte does not authorize this special regime")
            if (
                rule["selector"] == facts and competence >= treatment.effective_from
                and (treatment.effective_to is None or competence < treatment.effective_to)
            ):
                if not treatment.deduction_documents or (
                    treatment.deduction_source_type == source_type
                    and treatment.deduction_source_id == source_id
                ):
                    matches.append(treatment)
        specific = [item for item in matches if item.deduction_documents]
        if specific:
            matches = specific
        if len(matches) != 1:
            raise ValueError("national decision absent or ambiguous")
        return ReviewedNfsePolicy(data["policy_id"], data["version"], digest, raw, matches[0])
    except (
        OSError, KeyError, TypeError, ValueError, AttributeError, ArithmeticError, RecursionError,
    ):
        raise FiscalValidationError("Scoped national NFS-e policy unavailable or invalid") from None


def require_current_national_treatment_for_live_dispatch(
    environ: Mapping[str, str], document: NfseCanonicalDocument,
) -> ReviewedNfsePolicy:
    """Revalidate the exact installed tax decision before a real SEFIN POST.

    A prepared DPS may be historical. If the policy has been removed, rotated
    or no longer selects its documented service and competence, the operation
    must be reconciled or reviewed, never silently reclassified.
    """
    decision = document.national_tax_treatment
    if decision is None or decision.policy_id is None or decision.policy_sha256 is None:
        raise FiscalValidationError(
            "Live National NFS-e requires a pinned, reviewed tax decision"
        )
    if len(document.services) != 1:
        raise FiscalValidationError("Live National NFS-e requires one service per DPS")
    service = document.services[0]
    taker = document.service_taker
    country = (
        taker.address.country_code
        if taker is not None and isinstance(taker.address, NfseForeignAddress)
        else "BR"
    )
    facts: dict[str, Any] = {
        "issuer_profile_id": document.issuer.profile_id,
        "issuer_profile_version": document.issuer.version,
        "issuer_cnpj": document.issuer.cnpj.value,
        "issuer_tax_regime": int(document.issuer.tax_regime),
        "issuer_municipality_ibge": (
            document.issuer.address.jurisdiction.municipality_ibge_code
        ),
        "service_state_code": document.service_jurisdiction.state_code,
        "service_municipality_ibge": document.service_jurisdiction.municipality_ibge_code,
        "national_taxation_code": service.national_taxation_code,
        "municipal_service_code": service.municipal_service_code,
        "taker_country": country,
        "iss_withheld": service.iss_withheld,
        "nbs_code": service.nbs_code,
        "municipal_taxation_detail": service.municipal_taxation_detail,
        "source_normative": service.source_normative,
        "rule_version": service.rule_version,
    }
    current = resolve_national_treatment(
        environ, document.scope, facts, document.competence_date,
        source_type=document.source.source_type, source_id=document.source.source_id,
    )
    if current is None or current.treatment != decision:
        raise FiscalValidationError(
            "Live National NFS-e decision differs from current pinned policy"
        )
    if document.requires_reviewed_iss_rate and current.treatment.iss_rate is None:
        raise FiscalValidationError("Live National NFS-e requires exact reviewed ISS rate")
    # PBH notice 29/10/2025, updated 14/08/2026: the identified
    # cooperative benefit is specifically the differentiated 3% ISS rate.
    if (
        document.service_jurisdiction.municipality_ibge_code == "3106200"
        and decision.municipal_benefit_id is not None
        and decision.iss_rate != "3.00"
    ):
        raise FiscalValidationError("BH cooperative benefit requires reviewed 3 percent ISS")
    return current


def install_reviewed_policy(source: Path, directory: Path) -> str:
    """Install operator-reviewed national decisions; no rules or rates are invented."""
    import os
    import tempfile
    from uuid import uuid4

    from kordena_fiscal.domain import FiscalEnvironment

    if source.is_symlink() or directory.is_symlink() or not directory.is_absolute():
        raise FiscalValidationError("Policy paths must be explicit and non-symlink")
    with source.open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise FiscalValidationError("National policy exceeds size limit")
    data = json.loads(raw, object_pairs_hook=_unique)
    scope = ExecutionScope(data["tenant_id"], data["unit_id"],
        FiscalEnvironment(data["environment"]), "policy-install", data["host_namespace"])
    name = sale_policy_key(scope, FiscalDocumentKind.NFSE)
    digest = hashlib.sha256(raw).hexdigest()
    if not isinstance(data.get("rules"), list) or not 1 <= len(data["rules"]) <= 500:
        raise FiscalValidationError("Reviewed national rules are required")
    with tempfile.TemporaryDirectory(prefix="nfcore-national-policy-") as work:
        folder = Path(work)
        (folder / (name + ".json")).write_bytes(raw)
        (folder / (name + ".sha256")).write_text(digest, encoding="ascii")
        for rule in data["rules"]:
            resolve_national_treatment(
                {POLICY_ENV: work}, scope, rule["selector"],
                date.fromisoformat(rule["treatment"]["effective_from"]),
                source_type=rule["treatment"].get("deduction_source_type"),
                source_id=rule["treatment"].get("deduction_source_id"),
            )
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise FiscalValidationError("National policy directory cannot be a symlink")
    with _serialized_policy_install(directory, name):
        target, pin = directory / (name + ".json"), directory / (name + ".sha256")
        if target.is_symlink() or pin.is_symlink():
            raise FiscalValidationError("National policy destination cannot be a symlink")
        # A reviewed decision's version is an audit invariant. Reinstalling identical
        # bytes is idempotent; changing any decision, selector or rule at the same
        # version (or rolling back to an older version) is not.
        if target.exists() or pin.exists():
            if not target.is_file() or not pin.is_file():
                raise FiscalValidationError("National policy installation is incomplete")
            with target.open("rb") as stream:
                previous_raw = stream.read(1_048_577)
            with pin.open("rb") as stream:
                previous_pin = stream.read(66)
            if (
                not previous_raw or len(previous_raw) > 1_048_576
                or not re.fullmatch(rb"[0-9a-f]{64}\n?", previous_pin)
                or hashlib.sha256(previous_raw).hexdigest().encode()
                != previous_pin.strip()
            ):
                raise FiscalValidationError("Existing national policy integrity failed")
            try:
                previous = json.loads(previous_raw, object_pairs_hook=_unique)
            except (TypeError, ValueError, RecursionError):
                raise FiscalValidationError("Existing national policy is invalid") from None
            if (
                not isinstance(previous, dict)
                or type(previous.get("version")) is not int
                or type(previous.get("schema_version")) is not int
                or previous["schema_version"] != 1
                or any(previous.get(k) != data.get(k) for k in (
                    "host_namespace", "tenant_id", "unit_id",
                    "environment", "document_kind",
                ))
            ):
                raise FiscalValidationError("Existing national policy scope is invalid")
            if previous_raw == raw:
                return name
            if data["version"] <= previous["version"]:
                raise FiscalValidationError(
                    "National tax policy changes require a higher reviewed version"
                )
        suffix = "." + uuid4().hex + ".tmp"
        staged, staged_pin = directory / (name + suffix), directory / (name + suffix + ".sha256")
        try:
            staged.write_bytes(raw)
            staged_pin.write_text(digest + "\n", encoding="ascii")
            staged.chmod(0o644)
            staged_pin.chmod(0o644)
            os.replace(staged, target)
            os.replace(staged_pin, pin)
        finally:
            staged.unlink(missing_ok=True)
            staged_pin.unlink(missing_ok=True)
        return name


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Install reviewed national NFS-e decisions")
    parser.add_argument("source", type=Path)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        name = install_reviewed_policy(args.source, args.directory)
    except (OSError, FiscalValidationError, KeyError, TypeError, ValueError, AttributeError):
        parser.exit(2, "National policy was not installed: invalid reviewed artifact\n")
    print(f"Validated scoped national policy installed: {name}")


if __name__ == "__main__":
    main()
