"""T15: historical XML/apuracao reconciliation, not a recovery or issuance engine."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import date, datetime
from fractions import Fraction
from typing import Annotated, Any, Literal, Self

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from kordena_fiscal.cognitive.economy_contract import LegalCitation
from kordena_fiscal.domain import Cnpj, FiscalValidationError
from kordena_fiscal.tax.revenue_item_catalog import ReviewedItemCatalog
from kordena_fiscal.tax.simples_nacional import _round_cents
from kordena_fiscal.tax.simples_segregation import FederalTreatment, LocalTreatment
from kordena_fiscal.xml.access_key import NfeAccessKey

SCHEMA = "nfcore.historical-audit/v1"
XML_SCHEMA = "nfcore.historical-audit-xml/v1"
ARTIFACT_SCHEMA = "nfcore.historical-audit-artifact/v1"
NS = "{http://www.portalfiscal.inf.br/nfe}"
Tax = Literal["pis", "cofins", "icms"]
TAXES: tuple[Tax, ...] = ("pis", "cofins", "icms")
Regime = Literal["simples_nacional", "lucro_presumido", "lucro_real"]
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Cents = Annotated[int, Field(ge=0, le=10**12)]
Version = Annotated[int, Field(ge=1, le=2147483647)]
Day = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class IssuerContext(Strict):
    uf: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    state_ibge_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{2}$")]
    crt: Literal[1, 3]
    regime: Regime
    profile_id: Id
    profile_version: Version
    cnae: Annotated[str, StringConstraints(pattern=r"^[0-9]{7}$")]

    @model_validator(mode="after")
    def compatible(self) -> Self:
        if (self.crt == 1) != (self.regime == "simples_nacional"):
            raise ValueError("historical regime differs from CRT")
        return self


class Artifact(Strict):
    reference: Id
    kind: Literal["legal", "assessment", "payment", "status", "coverage"]
    sha256: Digest
    data_b64: Annotated[str, StringConstraints(min_length=4, max_length=524288)]


class ItemRule(Strict):
    ncm: Annotated[str, StringConstraints(pattern=r"^[0-9]{8}$")]
    cest: Annotated[str, StringConstraints(pattern=r"^[0-9]{7}$")] | None
    cfop: Annotated[str, StringConstraints(pattern=r"^[56][0-9]{3}$")]
    uf: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    activity: Literal["commerce", "industry"]
    market: Literal["domestic"]
    regime: Regime
    operation_context: Id
    valid_from: Day
    valid_until: Day
    source_url: str
    rule_reference: Id
    federal: Literal["ordinary", "monophase_downstream", "unknown"]
    local: Literal[
        "ordinary", "icms_substituted", "icms_substitute", "icms_final_advance", "unknown"
    ]


class Allocation(Strict):
    tax: Tax
    declared_cents: Cents
    reviewed_base_cents: Cents | None = None
    base_review_reference: Id | None = None
    base_mode: Literal["reviewed_amount", "xml_base_less_own_icms"] | None = None
    reviewed_rate: Annotated[str, StringConstraints(max_length=8)] | None = None
    # Explicit reviewed allocation of the declaration, not XML tax alone.
    assessment_reference: Id
    treatment_reference: Id


class Item(Strict):
    number: Annotated[int, Field(ge=1, le=990)]
    activity: Literal["commerce", "industry"]
    operation_context: Id
    allocations: Annotated[list[Allocation], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def taxes(self) -> Self:
        if {x.tax for x in self.allocations} != set(TAXES):
            raise ValueError("one reviewed allocation per supported tax required")
        return self


class Document(Strict):
    xml_b64: Annotated[str, StringConstraints(min_length=4, max_length=524288)]
    xml_sha256: Digest
    status_reference: Id
    status: Literal["active", "cancelled", "unresolved"]
    items: Annotated[list[Item], Field(max_length=990)]


class Payment(Strict):
    receipt_id: Id
    issuer_cnpj: Id
    competence: Day
    paid_on: Day
    collection: Literal["direct", "das_components"]
    evidence_reference: Id
    principal_cents: Cents
    allocations: dict[Tax, Cents]
    other_principal_cents: Cents

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if (
            self.principal_cents <= 0
            or sum(self.allocations.values()) + (self.other_principal_cents) != self.principal_cents
        ):
            raise ValueError("receipt principal allocation does not reconcile")
        return self


class TaxControl(Strict):
    tax: Tax
    declared_principal_cents: Cents
    assessment_reference: Id
    # Scope is explicitly limited to the three reviewed principal components.
    payment_history_complete: bool
    payment_history_reference: Id
    # Refunds, offsets, instalment/interest or unsettled events are not equivalent
    # to principal collected; an unresolved adjustment blocks payment classification.
    no_unresolved_adjustments: bool


class Month(Strict):
    competence: Day
    review_status: Literal["reviewed"] = "reviewed"
    review_reference: Id
    coverage_reference: Id
    coverage_complete: bool
    collection: Literal["direct", "das_components"]
    regime: Regime
    citations: Annotated[list[LegalCitation], Field(max_length=64)]
    catalog: Annotated[list[ItemRule], Field(max_length=10000)]
    artifacts: Annotated[list[Artifact], Field(min_length=1, max_length=500)]
    documents: Annotated[list[Document], Field(max_length=1000)]
    controls: Annotated[list[TaxControl], Field(min_length=3, max_length=3)]
    payments: Annotated[list[Payment], Field(max_length=500)]

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if {x.tax for x in self.controls} != set(TAXES):
            raise ValueError("one monthly control per supported tax required")
        if sum(len(d.items) for d in self.documents) > 10000:
            raise ValueError("historical monthly item limit exceeded")
        return self


def closed_months(end: date, today: date) -> tuple[date, ...]:
    """Exactly 60 closed calendar competences, inclusive end."""
    if type(end) is not date or end.day != 1 or end.year < 6 or end >= today.replace(day=1):
        raise FiscalValidationError("historical audit requires a closed competence")
    ordinal = end.year * 12 + end.month - 1
    return tuple(date(i // 12, i % 12 + 1, 1) for i in range(ordinal - 59, ordinal + 1))


def source_bytes(data_b64: str, digest: str) -> bytes:
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise FiscalValidationError("invalid historical source bytes") from exc
    if not raw or len(raw) > 393216 or hashlib.sha256(raw).hexdigest() != digest:
        raise FiscalValidationError("historical source integrity mismatch")
    return raw


def _one(node: etree._Element, tag: str, *, optional: bool = False) -> etree._Element | None:
    found = node.findall(NS + tag)
    if len(found) != 1:
        if not found and optional:
            return None
        raise FiscalValidationError("missing or ambiguous historical XML field")
    return found[0]


def _text(node: etree._Element, tag: str, *, optional: bool = False) -> str | None:
    field = _one(node, tag, optional=optional)
    if field is None:
        return None
    if len(field) or not field.text or field.text.strip() != field.text:
        raise FiscalValidationError("invalid historical XML field")
    return field.text


def _required(node: etree._Element, tag: str) -> etree._Element:
    field = _one(node, tag)
    assert field is not None
    return field


def _money(value: str | None) -> int | None:
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]{1,13}(?:\.[0-9]{1,2})?", value):
        raise FiscalValidationError("invalid historical XML money")
    amount = Fraction(value) * 100
    if amount.denominator != 1 or amount > 10**12:
        raise FiscalValidationError("historical XML money outside supported range")
    return int(amount)


def _rate(value: str | None) -> Fraction | None:
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,4})?", value):
        raise FiscalValidationError("invalid historical XML rate")
    rate = Fraction(value)
    if not 0 <= rate <= 100:
        raise FiscalValidationError("historical XML rate outside supported range")
    return rate / 100


def parse_document(
    raw: bytes, issuer: Cnpj, period: date, uf: str, crt: int, state_ibge_code: str
) -> dict[str, Any]:
    """Read original authorized-protocol XML; authenticity/status require external review."""
    try:
        root = etree.fromstring(
            raw,
            parser=etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise FiscalValidationError("invalid historical XML") from exc
    if (
        getattr(root.getroottree().docinfo, "doctype", "")
        or root.tag != NS + "nfeProc"
        or (root.get("versao") != "4.00")
    ):
        raise FiscalValidationError("historical NF-e/NFC-e 4.00 protocol required")
    inf = _required(_required(root, "NFe"), "infNFe")
    protocol = _required(_required(root, "protNFe"), "infProt")
    ident, emit = _required(inf, "ide"), _required(inf, "emit")
    key = NfeAccessKey((inf.get("Id") or "")[3:])
    if inf.get("Id") != "NFe" + key.value or key.issuer_identifier != issuer.value:
        raise FiscalValidationError("historical XML issuer/key mismatch")
    stamp = _text(ident, "dhEmi")
    assert stamp is not None
    issued = datetime.fromisoformat(stamp)
    if (
        issued.utcoffset() is None
        or issued.date().replace(day=1) != period
        or key.value[2:6] != period.strftime("%y%m")
        or _text(emit, "CNPJ") != issuer.value
        or _text(emit, "CRT") != str(crt)
        or _text(_required(emit, "enderEmit"), "UF") != uf
        or _text(ident, "mod") != str(key.model.value)
        or _text(ident, "cUF") != key.value[:2]
        or key.value[:2] != state_ibge_code
        or _text(ident, "tpNF") != "1"
        or _text(ident, "finNFe") != "1"
        or _text(ident, "tpAmb") != "1"
        or _text(protocol, "tpAmb") != "1"
        or _text(protocol, "chNFe") != key.value
        or _text(protocol, "cStat") not in {"100", "150"}
        or not re.fullmatch(r"[0-9]{15,17}", _text(protocol, "nProt") or "")
        or inf.get("versao") != "4.00"
    ):
        raise FiscalValidationError("historical XML scope or protocol mismatch")
    # Key binds model, issuer and issue month; compare remaining canonical components.
    if (
        int(_text(ident, "serie") or "-1") != key.series
        or int(_text(ident, "nNF") or "-1") != key.invoice_number
        or _text(ident, "tpEmis") != key.value[34]
        or _text(ident, "cNF") != key.value[35:43]
        or _text(ident, "cDV") != key.value[-1]
    ):
        raise FiscalValidationError("historical XML key components mismatch")
    items: dict[int, dict[str, Any]] = {}
    for det in inf.findall(NS + "det"):
        number = int(det.get("nItem") or "0")
        if not 1 <= number <= 990 or number in items:
            raise FiscalValidationError("duplicate or invalid historical XML item")
        prod, tax = _required(det, "prod"), _required(det, "imposto")
        ncm, cfop, cest = (
            _text(prod, "NCM"),
            _text(prod, "CFOP"),
            _text(prod, "CEST", optional=True),
        )
        if not re.fullmatch(r"[0-9]{8}", ncm or "") or not re.fullmatch(
            r"[56][0-9]{3}", cfop or ""
        ):
            raise FiscalValidationError("unsupported historical item classification")
        groups: dict[str, Any] = {}
        for name, tag, amount in (
            ("pis", "PIS", "vPIS"),
            ("cofins", "COFINS", "vCOFINS"),
            ("icms", "ICMS", "vICMS"),
        ):
            outer = _one(tax, tag, optional=True)
            if outer is None:
                groups[name] = {
                    "cst": None,
                    "base_cents": None,
                    "amount_cents": None,
                    "rate": None,
                    "ad_valorem": False,
                }
                continue
            if len(outer) != 1 or not isinstance(outer[0].tag, str):
                raise FiscalValidationError("ambiguous historical XML tax group")
            inner = outer[0]
            if not inner.tag.startswith(NS):
                raise FiscalValidationError("invalid historical XML tax namespace")
            rate_tag = {"pis": "pPIS", "cofins": "pCOFINS", "icms": "pICMS"}[name]
            rate = _rate(_text(inner, rate_tag, optional=True))
            base = _money(_text(inner, "vBC", optional=True))
            amt = _money(_text(inner, amount, optional=True))
            cst = _text(inner, "CST", optional=True)
            csosn = _text(inner, "CSOSN", optional=True)
            if cst is not None and csosn is not None:
                raise FiscalValidationError("ambiguous historical tax code")
            groups[name] = {
                "cst": cst or csosn,
                "base_cents": base,
                "amount_cents": amt,
                "rate": str(rate) if rate is not None else None,
                "ad_valorem": name in {"pis", "cofins"}
                and (
                    inner.tag == NS + ("PISAliq" if name == "pis" else "COFINSAliq")
                    and cst in {"01", "02"}
                    and rate is not None
                    and base is not None
                    and amt is not None
                ),
            }
        items[number] = {"number": number, "ncm": ncm, "cfop": cfop, "cest": cest, "taxes": groups}
    if not items or sorted(items) != list(range(1, len(items) + 1)):
        raise FiscalValidationError("historical XML line sequence invalid")
    return {
        "access_key": key.value,
        "model": key.model.value,
        "issued_on": issued.date().isoformat(),
        "items": items,
    }


def analyze_month(
    facts: Month,
    issuer: Cnpj,
    period: date,
    context: IssuerContext,
    *,
    as_of: date,
) -> dict[str, Any]:
    """Compare item allocations and actual principal receipts without awarding credit."""
    uf, crt = context.uf, context.crt
    if (
        facts.competence != period.isoformat()
        or facts.regime != context.regime
        or (facts.collection != ("direct" if crt == 3 else "das_components"))
    ):
        raise FiscalValidationError("historical competence/regime/collection mismatch")
    artifacts: dict[str, Artifact] = {}
    for artifact in facts.artifacts:
        source_bytes(artifact.data_b64, artifact.sha256)
        if artifact.reference in artifacts:
            raise FiscalValidationError("duplicate historical evidence reference")
        artifacts[artifact.reference] = artifact

    def evidence(reference: str, kind: str) -> Artifact:
        item = artifacts.get(reference)
        if item is None or item.kind != kind:
            raise FiscalValidationError("missing typed historical evidence")
        return item

    evidence(facts.coverage_reference, "coverage")
    citations = {c.review_reference: c for c in facts.citations}
    if len(citations) != len(facts.citations):
        raise FiscalValidationError("ambiguous historical legal reference")
    for c in citations.values():
        if (
            not c.covers(period.isoformat())
            or c.published_on > period.isoformat()
            or evidence(c.review_reference, "legal").sha256 != c.source_sha256
        ):
            raise FiscalValidationError("historical legal evidence does not cover competence")
    for rule in facts.catalog:
        if rule.regime != context.regime:
            raise FiscalValidationError("historical item regime differs from canonical context")
        citation = citations.get(rule.rule_reference)
        if (
            citation is None
            or citation.source_url != rule.source_url
            or (
                date.fromisoformat(rule.valid_from) < date.fromisoformat(citation.valid_from)
                or citation.valid_until is not None
                and rule.valid_until > citation.valid_until
            )
        ):
            raise FiscalValidationError("historical item rule lacks matching legal evidence")
    catalog = (
        ReviewedItemCatalog(
            [r.model_dump() for r in facts.catalog],
            period,
            {c.source_url for c in facts.citations},
        )
        if facts.catalog
        else None
    )
    controls = {c.tax: c for c in facts.controls}
    for control in controls.values():
        evidence(control.assessment_reference, "assessment")
        evidence(control.payment_history_reference, "coverage")
    paid = dict.fromkeys(TAXES, 0)
    receipts: list[dict[str, str]] = []
    receipt_ids: set[str] = set()
    receipt_hashes: set[str] = set()
    for payment in facts.payments:
        artifact = evidence(payment.evidence_reference, "payment")
        if (
            payment.issuer_cnpj != issuer.value
            or payment.competence != period.isoformat()
            or payment.collection != facts.collection
            or not period <= date.fromisoformat(payment.paid_on) <= as_of
        ):
            raise FiscalValidationError("historical receipt scope, date or collection mismatch")
        if payment.receipt_id in receipt_ids or artifact.sha256 in receipt_hashes:
            raise FiscalValidationError("duplicate historical payment")
        receipt_ids.add(payment.receipt_id)
        receipt_hashes.add(artifact.sha256)
        receipts.append(
            {
                "receipt_id": payment.receipt_id,
                "sha256": artifact.sha256,
                "paid_on": payment.paid_on,
            }
        )
        for tax, amount in payment.allocations.items():
            paid[tax] += amount
    documents: list[dict[str, Any]] = []
    keys: set[str] = set()
    declared = dict.fromkeys(TAXES, 0)
    corrected = dict.fromkeys(TAXES, 0)
    unresolved = dict.fromkeys(TAXES, 0)
    positives = dict.fromkeys(TAXES, 0)
    negatives = dict.fromkeys(TAXES, 0)
    document_status_unresolved = False
    count = 0
    for doc in facts.documents:
        evidence(doc.status_reference, "status")
        parsed = parse_document(
            source_bytes(doc.xml_b64, doc.xml_sha256),
            issuer,
            period,
            uf,
            crt,
            context.state_ibge_code,
        )
        key = parsed["access_key"]
        if key in keys:
            raise FiscalValidationError("duplicate historical XML key")
        keys.add(key)
        if doc.status != "active":
            if doc.items:
                raise FiscalValidationError("inactive XML cannot supply assessment allocations")
            document_status_unresolved |= doc.status == "unresolved"
            documents.append(
                {
                    "access_key": key,
                    "xml_sha256": doc.xml_sha256,
                    "status": doc.status,
                    "status_reference": doc.status_reference,
                    "findings": [],
                }
            )
            continue
        if len({i.number for i in doc.items}) != len(doc.items) or (
            {i.number for i in doc.items} != set(parsed["items"])
        ):
            raise FiscalValidationError("historical active XML item coverage mismatch")
        findings: list[dict[str, Any]] = []
        for item in sorted(doc.items, key=lambda i: i.number):
            count += 1
            xml = parsed["items"][item.number]
            attrs = {k: xml[k] for k in ("ncm", "cest", "cfop")} | {
                "activity": item.activity,
                "market": "domestic",
                "operation_context": item.operation_context,
            }
            fed, local, rule_ref, _ = (
                catalog.resolve(attrs, uf)
                if catalog
                else (
                    FederalTreatment.UNKNOWN,
                    LocalTreatment.UNKNOWN,
                    "item_rule_unresolved",
                    None,
                )
            )
            for allocation in sorted(item.allocations, key=lambda a: a.tax):
                tax = allocation.tax
                evidence(allocation.assessment_reference, "assessment")
                if allocation.assessment_reference != controls[tax].assessment_reference:
                    raise FiscalValidationError("item allocation differs from monthly assessment")
                if (
                    allocation.treatment_reference != rule_ref
                    and rule_ref != "item_rule_unresolved"
                ):
                    raise FiscalValidationError("item treatment reference mismatch")
                amount = allocation.declared_cents
                declared[tax] += amount
                due: int | None = None
                reason = "unresolved_treatment"
                xml_tax = xml["taxes"][tax]
                # Exact T06 classification vocabulary; no historical statutory rate extrapolation.
                if tax in {"pis", "cofins"} and fed is FederalTreatment.MONOPHASE:
                    due, reason = 0, "monophase_downstream"
                elif tax == "icms" and local in {
                    LocalTreatment.ICMS_SUBSTITUTED,
                    LocalTreatment.ICMS_FINAL_ADVANCE,
                }:
                    due, reason = 0, local.value
                elif (tax in {"pis", "cofins"} and fed is FederalTreatment.ORDINARY) or (
                    tax == "icms" and local is LocalTreatment.ORDINARY
                ):
                    if allocation.reviewed_base_cents is None:
                        if (
                            crt == 1
                            or xml_tax["amount_cents"] == amount
                            or (amount == 0 and xml_tax["amount_cents"] is None)
                        ):
                            due, reason = amount, "reviewed_no_adjustment"
                        else:
                            reason = "xml_assessment_mismatch"
                    elif (
                        crt == 3
                        and tax in {"pis", "cofins"}
                        and xml_tax["ad_valorem"]
                        and xml_tax["amount_cents"] == amount
                        and _round_cents(Fraction(xml_tax["rate"]) * xml_tax["base_cents"])
                        == amount
                    ):
                        due = _round_cents(
                            Fraction(xml_tax["rate"]) * allocation.reviewed_base_cents
                        )
                        reason = "pis_cofins_base_divergence"
                if allocation.reviewed_base_cents is not None:
                    if (
                        reason != "pis_cofins_base_divergence"
                        or allocation.base_review_reference not in citations
                        or allocation.base_mode is None
                        or _rate(allocation.reviewed_rate) != Fraction(xml_tax["rate"])
                    ):
                        raise FiscalValidationError(
                            "reviewed base unsupported or lacks legal citation"
                        )
                    if allocation.base_mode == "xml_base_less_own_icms":
                        own_icms = xml["taxes"]["icms"]["amount_cents"]
                        if (
                            own_icms is None
                            or own_icms > xml_tax["base_cents"]
                            or allocation.reviewed_base_cents != xml_tax["base_cents"] - own_icms
                        ):
                            raise FiscalValidationError(
                                "reviewed ICMS exclusion does not reconcile"
                            )
                elif any(
                    value is not None
                    for value in (
                        allocation.base_review_reference,
                        allocation.base_mode,
                        allocation.reviewed_rate,
                    )
                ):
                    raise FiscalValidationError("base evidence without reviewed base")
                if due is None:
                    unresolved[tax] += 1
                    delta = None
                else:
                    corrected[tax] += due
                    delta = amount - due
                    positives[tax] += max(delta, 0)
                    negatives[tax] += max(-delta, 0)
                findings.append(
                    {
                        "item_number": item.number,
                        "ncm": xml["ncm"],
                        "cest": xml["cest"],
                        "cfop": xml["cfop"],
                        "tax": tax,
                        "xml_tax": xml_tax,
                        "declared_cents": amount,
                        "reviewed_due_cents": due,
                        "reviewed_base_cents": allocation.reviewed_base_cents,
                        "base_mode": allocation.base_mode,
                        "reviewed_rate": allocation.reviewed_rate,
                        "difference_cents": delta,
                        "reason": reason,
                        "assessment_reference": allocation.assessment_reference,
                        "treatment_reference": rule_ref,
                        "citation": citations[rule_ref].model_dump()
                        if rule_ref in citations
                        else None,
                        "base_citation": (
                            citations[allocation.base_review_reference].model_dump()
                            if allocation.base_review_reference is not None
                            else None
                        ),
                        "xml_assessment_difference_cents": (
                            amount - xml_tax["amount_cents"]
                            if crt == 3 and xml_tax["amount_cents"] is not None
                            else None
                        ),
                    }
                )
        documents.append(
            {
                "access_key": key,
                "xml_sha256": doc.xml_sha256,
                "status": doc.status,
                "status_reference": doc.status_reference,
                "findings": findings,
            }
        )
    if any(
        value > 10**12
        for amounts in (paid, declared, corrected, positives, negatives)
        for value in amounts.values()
    ):
        raise FiscalValidationError("monthly audit totals exceed exact supported range")
    groups: list[dict[str, Any]] = []
    for tax in TAXES:
        control = controls[tax]
        complete = (
            facts.coverage_complete
            and not document_status_unresolved
            and declared[tax] == control.declared_principal_cents
            and not unresolved[tax]
        )
        settled = (
            complete and control.payment_history_complete and control.no_unresolved_adjustments
        )
        # Without full reconciliation and paid declared principal, item attribution is unsafe.
        candidate = (
            positives[tax]
            if (settled and paid[tax] == declared[tax] and not negatives[tax])
            else None
        )
        groups.append(
            {
                "tax": tax,
                "collection": facts.collection,
                "declared_cents": control.declared_principal_cents,
                "allocated_cents": declared[tax],
                "observed_paid_cents": paid[tax],
                "reviewed_due_cents": corrected[tax] if complete else None,
                "positive_difference_cents": positives[tax] if complete else None,
                "negative_difference_cents": negatives[tax] if complete else None,
                "unresolved_items": unresolved[tax],
                "reconciled": complete,
                "payment_history_complete": control.payment_history_complete,
                "no_unresolved_adjustments": control.no_unresolved_adjustments,
                "paid_candidate_cents": candidate,
                "status": (
                    "insufficient_basis"
                    if not complete
                    else "payment_unconfirmed"
                    if not settled or paid[tax] != declared[tax]
                    else "mixed_difference"
                    if negatives[tax]
                    else "potential_undue_payment"
                    if candidate
                    else "no_difference"
                ),
                "assessment_reference": control.assessment_reference,
                "payment_history_reference": control.payment_history_reference,
            }
        )
    by_tax = {group["tax"]: group for group in groups}
    for document in documents:
        for finding in document["findings"]:
            delta = finding["difference_cents"]
            group = by_tax[finding["tax"]]
            finding["status"] = (
                "unresolved"
                if delta is None
                else "no_difference"
                if delta == 0
                else "possible_underassessment"
                if delta < 0
                else "potential_undue_payment"
                if group["paid_candidate_cents"] is not None
                else "assessment_difference_payment_unconfirmed"
            )
            finding["paid_candidate_cents"] = (
                delta
                if delta is not None and delta > 0 and group["paid_candidate_cents"] is not None
                else None
            )
    return {
        "schema_version": SCHEMA,
        "competence": period.isoformat(),
        "review_reference": facts.review_reference,
        "coverage_reference": facts.coverage_reference,
        "coverage_complete": facts.coverage_complete,
        "groups": groups,
        "document_count": len(documents),
        "item_count": count,
        "receipts": receipts,
        "documents": documents,
        "advisory_only": True,
        "credit_recognized": False,
        "realized_cents": None,
    }
