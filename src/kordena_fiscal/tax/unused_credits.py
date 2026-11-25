"""T16. Match supplier NF-e lines to reviewed credit rules and bookkeeping evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date
from fractions import Fraction
from typing import Annotated, Any, Literal

from lxml import etree
from pydantic import Field, StringConstraints

from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.tax.historical_audit import (
    NS,
    Cents,
    Day,
    Digest,
    Id,
    IssuerContext,
    Regime,
    Strict,
    _money,
    _required,
    _text,
    closed_months,
    parse_document,
    source_bytes,
)
from kordena_fiscal.tax.simples_nacional import _round_cents
from kordena_fiscal.xml.access_key import NfeAccessKey

CreditTax = Literal["icms", "ipi", "pis", "cofins", "ibs_presumido", "cbs_presumido"]
Purpose = Literal["insumo", "frete", "energia", "ativo_imobilizado"]
ItemNumber = Annotated[int, Field(ge=1, le=990)]
Ncm = Annotated[str, StringConstraints(pattern=r"^[0-9]{8}$")]
Cfop = Annotated[str, StringConstraints(pattern=r"^[56][0-9]{3}$")]


class Evidence(Strict):
    sha256: Digest
    data_b64: Annotated[str, StringConstraints(min_length=4, max_length=524288)]

    def contents(self) -> bytes:
        return source_bytes(self.data_b64, self.sha256)


class Rule(Strict):
    tax: CreditTax
    purpose: Purpose
    regime: Regime
    uf: Id
    cnae: Id
    ncm: Ncm
    supplier_cfop: Cfop
    required_facts: Annotated[dict[Id, bool], Field(min_length=1, max_length=32)]
    method: Literal["highlighted_icms", "highlighted_ipi", "reviewed_base"]
    # Exact fraction includes any legally required apportionment or instalment.
    numerator: Annotated[int, Field(ge=1, le=100000000)]
    denominator: Annotated[int, Field(ge=1, le=100000000)]
    citation: LegalCitation
    legal_source: Evidence


class Use(Strict):
    item: ItemNumber
    purpose: Purpose
    tax: CreditTax
    observed_facts: Annotated[dict[Id, bool], Field(max_length=64)]
    basis_cents: Cents
    # Reviewed allocation and legal conditions, including exceptions, for this line.
    eligibility_evidence: Evidence


class Purchase(Strict):
    xml: Evidence
    status: Literal["active", "cancelled", "unresolved"]
    status_evidence: Evidence
    uses: Annotated[list[Use], Field(max_length=5940)]


class Entry(Strict):
    access_key: str
    item: ItemNumber
    tax: CreditTax
    booked_cents: Cents


class Books(Strict):
    recipient: str
    competence: Day
    checked_through: Day
    complete_taxes: list[CreditTax]
    all_units_and_later_adjustments_reviewed: bool
    entries: list[Entry]
    source: Evidence


class Batch(Strict):
    competence: Day
    rules: Annotated[list[Rule], Field(max_length=1000)]
    purchases: Annotated[list[Purchase], Field(max_length=1000)]
    books: Books | None


def _invoice(raw: bytes, recipient: Cnpj, period: date) -> tuple[str, dict[int, dict[str, Any]]]:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    try:
        root = etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise FiscalValidationError("invalid purchase XML") from exc
    if getattr(root.getroottree().docinfo, "doctype", ""):
        raise FiscalValidationError("purchase XML contains DTD")
    inf = _required(_required(root, "NFe"), "infNFe")
    if _text(_required(inf, "dest"), "CNPJ") != recipient.value:
        raise FiscalValidationError("purchase recipient mismatch")
    emit = _required(inf, "emit")
    supplier = Cnpj(_text(emit, "CNPJ") or "")
    if supplier == recipient:
        raise FiscalValidationError("self-issued purchase requires separate evidence")
    parsed = parse_document(
        raw,
        supplier,
        period,
        _text(_required(emit, "enderEmit"), "UF") or "",
        int(_text(emit, "CRT") or "0"),
        _text(_required(inf, "ide"), "cUF") or "",
    )
    if parsed["model"] != 55:
        raise FiscalValidationError("supplier NF-e model 55 required")
    items = parsed["items"]
    for det in inf.findall(NS + "det"):
        line = items[int(det.get("nItem") or "0")]
        line["product_cents"] = _money(_text(_required(det, "prod"), "vProd"))
        ipi = det.find(NS + "imposto/" + NS + "IPI/" + NS + "IPITrib")
        line["ipi_cents"] = None if ipi is None else _money(_text(ipi, "vIPI", optional=True))
    return parsed["access_key"], items


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise FiscalValidationError("duplicate bookkeeping extract field")
        result[name] = value
    return result


def detect(batch: Batch, recipient: Cnpj, context: IssuerContext, as_of: date) -> dict[str, Any]:
    period = date.fromisoformat(batch.competence)
    closed_months(period, as_of)
    rules = {}
    for reviewed_rule in batch.rules:
        reviewed_rule.legal_source.contents()
        ref = reviewed_rule.citation.review_reference
        if (
            ref in rules
            or reviewed_rule.legal_source.sha256 != reviewed_rule.citation.source_sha256
        ):
            raise FiscalValidationError("ambiguous rule or legal source hash mismatch")
        if reviewed_rule.numerator > reviewed_rule.denominator:
            raise FiscalValidationError("credit fraction exceeds base")
        rules[ref] = reviewed_rule

    books = batch.books
    booked: dict[tuple[str, int, CreditTax], int] = {}
    coverage: set[CreditTax] = set()
    if books is not None:
        # A reviewed extract contains the scope, cutoff, coverage and every booking.
        # Parse the original extract and reject any divergence in the caller projection.
        extract = json.loads(books.source.contents(), object_pairs_hook=_unique_fields)
        expected = books.model_dump(exclude={"source"})
        if json.dumps(extract, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise FiscalValidationError("bookkeeping extract differs from reviewed entries")
        if books.recipient != recipient.value or books.competence != batch.competence:
            raise FiscalValidationError("bookkeeping scope mismatch")
        if (
            books.checked_through == as_of.isoformat()
            and books.all_units_and_later_adjustments_reviewed
        ):
            coverage.update(books.complete_taxes)
        for entry in books.entries:
            if NfeAccessKey(entry.access_key).value != entry.access_key:
                raise FiscalValidationError("noncanonical bookkeeping invoice key")
            key = (entry.access_key, entry.item, entry.tax)
            if key in booked:
                raise FiscalValidationError("duplicate bookkeeping allocation")
            booked[key] = entry.booked_cents

    findings = []
    unassessed_items = 0
    seen_docs = set()
    totals: Counter[str] = Counter()
    for purchase in batch.purchases:
        access, lines = _invoice(purchase.xml.contents(), recipient, period)
        purchase.status_evidence.contents()
        if access in seen_docs:
            raise FiscalValidationError("duplicate purchase document")
        seen_docs.add(access)
        seen = set()
        for use in purchase.uses:
            identity = (access, use.item, use.tax)
            if identity in seen or use.item not in lines:
                raise FiscalValidationError("duplicate or missing purchase item allocation")
            seen.add(identity)
            use.eligibility_evidence.contents()
            line = lines[use.item]
            applicable = [
                candidate
                for candidate in rules.values()
                if candidate.citation.covers(batch.competence)
                and (
                    candidate.tax,
                    candidate.purpose,
                    candidate.regime,
                    candidate.uf,
                    candidate.cnae,
                    candidate.ncm,
                    candidate.supplier_cfop,
                )
                == (
                    use.tax,
                    use.purpose,
                    context.regime,
                    context.uf,
                    context.cnae,
                    line["ncm"],
                    line["cfop"],
                )
            ]
            rule = applicable[0] if len(applicable) == 1 else None
            conditions = rule.required_facts if rule is not None else {}
            observed = use.observed_facts
            contradicted = any(k in observed and observed[k] != v for k, v in conditions.items())
            principal = None
            status = "insufficient_basis"
            if purchase.status == "cancelled" or contradicted:
                status = "excluded"
            elif (
                rule is not None
                and conditions.keys() <= observed.keys()
                and purchase.status == "active"
                and use.tax in coverage
            ):
                limit = line["product_cents"]
                if rule.method == "highlighted_icms":
                    limit = line["taxes"]["icms"]["amount_cents"] if use.tax == "icms" else None
                elif rule.method == "highlighted_ipi":
                    limit = line["ipi_cents"] if use.tax == "ipi" else None
                if limit is not None and use.basis_cents <= limit:
                    possible = _round_cents(
                        Fraction(use.basis_cents * rule.numerator, rule.denominator)
                    )
                    previously = booked.get(identity, 0)
                    if previously <= possible:
                        principal = possible - previously
                        status = "unused_candidate" if principal else "fully_accounted"
                        totals[use.tax] += principal
            findings.append(
                {
                    "identity": hashlib.sha256(
                        f"{recipient.value}/{access}/{use.item}/{use.tax}".encode()
                    ).hexdigest(),
                    "access_key": access,
                    "item": use.item,
                    "tax": use.tax,
                    "purpose": use.purpose,
                    "observed_facts": observed,
                    "required_facts": conditions,
                    "status": status,
                    "candidate_cents": principal,
                    "xml_sha256": purchase.xml.sha256,
                    "basis_cents": use.basis_cents,
                    "booked_cents": booked.get(identity, 0) if use.tax in coverage else None,
                    "fraction": [rule.numerator, rule.denominator] if rule is not None else None,
                    "citation": rule.citation.model_dump() if rule is not None else None,
                    "eligibility_sha256": use.eligibility_evidence.sha256,
                    "status_sha256": purchase.status_evidence.sha256,
                }
            )
        unassessed_items += len(set(lines) - {item for _, item, _ in seen})
    return {
        "unassessed_items": unassessed_items,
        "schema_version": "nfcore.unused-credits/v1",
        "competence": batch.competence,
        "recipient": recipient.value,
        "as_of": as_of.isoformat(),
        "issuer_context": context.model_dump(),
        "bookkeeping_sha256": books.source.sha256 if books else None,
        "findings": findings,
        "partial_totals_cents": dict(totals),
        "credit_recognized": False,
    }
