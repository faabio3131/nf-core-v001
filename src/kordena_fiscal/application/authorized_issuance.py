"""T14: revalidate T13 and signed T09 terms at preparation and dispatch claim.

Only the existing homologation NF-e path may consume these opt-in ICMS
terms. No calculation or transmission authority is introduced here.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from lxml import etree

from kordena_fiscal.application.accounting_review import ReviewTarget, project_review
from kordena_fiscal.application.issuance_terms import reviewed_issuance_terms
from kordena_fiscal.documents.serialization import _issuer, _product, _tax_decision
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalEnvironment,
    FiscalValidationError,
)
from kordena_fiscal.gateway import AuthorizationRequest
from kordena_fiscal.persistence.economy_store import EconomyStore, _digest
from kordena_fiscal.persistence.ports import (
    FiscalUnitOfWork,
    FiscalUnitOfWorkFactory,
    PersistenceStateError,
)
from kordena_fiscal.security.human_identity import HumanAccount, PortalRole
from kordena_fiscal.tax import TaxDecision

MEDIA_TYPE = "application/vnd.nfcore.t14-issuance-approval.v1+json"
INPUT_MEDIA_TYPE = "application/vnd.nfcore.preparation-input.v1+json"
SCHEMA = "nfcore.t14-issuance-approval/v1"
LOCAL = ZoneInfo("America/Sao_Paulo")


class IssuanceApprovalRequired(FiscalValidationError):
    """No current, operation-specific accounting authorization."""


def _month(instant: datetime) -> date:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise IssuanceApprovalRequired("aware issuance instant required")
    return instant.astimezone(LOCAL).date().replace(day=1)


def _benefit_lines(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        line
        for line in document["items"]
        if (line["tax_decision"]["outcome"].get("nfe_rates") or {}).get("icms_benefit") is not None
    ]


def _active_accountant(factory: FiscalUnitOfWorkFactory, scope: ExecutionScope, actor: str) -> None:
    accounts = getattr(factory, "human_accounts", None)
    account = accounts().by_id(actor) if callable(accounts) else None
    if (
        not isinstance(account, HumanAccount)
        or not account.enabled
        or account.role is not PortalRole.ACCOUNTANT
        or account.platform_admin
        or account.tenant_id != scope.tenant_id
        or account.unit_ids is None
        or scope.unit_id not in account.unit_ids
    ):
        raise IssuanceApprovalRequired("accounting approval actor is no longer designated")


def _current_profiles(
    factory: FiscalUnitOfWorkFactory,
    scope: ExecutionScope,
    document: dict[str, Any],
    lines: list[dict[str, Any]],
    issued: datetime,
    now: datetime,
) -> None:
    host = scope.host_namespace
    if not host:
        raise IssuanceApprovalRequired("canonical host scope required")
    with factory() as uow:
        registration = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
        if registration is None or scope.environment not in registration.enabled_environments:
            raise IssuanceApprovalRequired("issuance unit is not enabled")
        for instant in (issued, now):
            issuer = uow.control_plane.resolve_profile(
                host_namespace=host,
                tenant_id=scope.tenant_id,
                unit_id=scope.unit_id,
                environment=scope.environment,
                instant=instant,
            )
            if (
                issuer is None
                or issuer.scope.identity_material != scope.identity_material
                or _issuer(issuer) != document["issuer"]
            ):
                raise IssuanceApprovalRequired("canonical issuer changed")
            for line in lines:
                product = uow.commercial.resolve_product_profile(
                    tenant_id=scope.tenant_id,
                    unit_id=scope.unit_id,
                    environment=scope.environment,
                    product_id=line["product"]["product_id"],
                    instant=instant,
                )
                if (
                    product is None
                    or product.scope.identity_material != scope.identity_material
                    or _product(product) != line["product"]
                ):
                    raise IssuanceApprovalRequired("canonical product changed")


def _claim_line(
    store: EconomyStore,
    factory: FiscalUnitOfWorkFactory,
    scope: ExecutionScope,
    document: dict[str, Any],
    line: dict[str, Any],
    issued: datetime,
    now: datetime,
) -> dict[str, Any]:
    # Reuse the exact T13 subject builder. A different digest is never treated
    # as equivalent authorization, even if the financial result is unchanged.
    from kordena_fiscal.cognitive.accounting_review_api import _current_subject

    period = _month(issued)
    decision = line["tax_decision"]
    rates = decision["outcome"]["nfe_rates"]
    benefit = rates["icms_benefit"]
    target = ReviewTarget(kind="benefit", source="state", benefit_id=benefit["benefit_id"])
    issuer, subject = _current_subject(store, factory, scope, period, target)
    if issuer.value != document["issuer"]["cnpj"]:
        raise IssuanceApprovalRequired("accounting issuer mismatch")
    report = project_review(store, issuer, period, target, subject)
    event = report["latest"]
    if report["status"] != "approved" or event is None:
        raise IssuanceApprovalRequired("current accounting approval required")
    if datetime.fromisoformat(event["recorded_at"]) > issued:
        raise IssuanceApprovalRequired("approval cannot authorize earlier issuance")
    _active_accountant(factory, scope, event["actor_id"])
    state = store.record("fm_economy_benefits", subject["benefit_id"], subject["benefit_version"])
    facts = store.record(
        "fm_economy_snapshots", subject["snapshot_id"], subject["snapshot_version"]
    )
    if (
        state is None
        or facts is None
        or state["digest"] != subject["benefit_digest"]
        or facts["digest"] != subject["snapshot_digest"]
    ):
        raise IssuanceApprovalRequired("reviewed issuance evidence unavailable")
    application = reviewed_issuance_terms(
        state["content"],
        facts["content"],
        subject["benefit_id"],
        subject["benefit_version"],
    )
    if application is None:
        raise IssuanceApprovalRequired("signed operation-specific issuance terms required")
    terms, rule = application
    if subject["candidate"].get("issuance_application") != terms:
        raise IssuanceApprovalRequired("accounting approval does not cover issuance terms")
    receipt = state["content"]["internal_review_approval"]
    if datetime.fromisoformat(receipt["approved_at"]) > issued:
        raise IssuanceApprovalRequired("curatorial review cannot authorize earlier issuance")
    recipient = document.get("recipient")
    if not isinstance(recipient, dict):
        raise IssuanceApprovalRequired("reviewed NF-e recipient required")
    recipient_profile = (
        "consumer_final"
        if recipient["final_consumer"]
        else "taxpayer"
        if recipient["ie_indicator"] in {1, 2}
        else "non_taxpayer"
    )
    product, canonical_issuer = line["product"], document["issuer"]
    if (
        canonical_issuer["profile_id"] != terms["issuer_profile_id"]
        or canonical_issuer["version"] != terms["issuer_profile_version"]
        or canonical_issuer["tax_regime"] != 3
        or canonical_issuer["address"]["state_code"] != rule.selector.state_code
        or recipient["address"]["state_code"] != rule.selector.destination_state_code
        or rule.selector.recipient_profile is None
        or recipient_profile != rule.selector.recipient_profile.value
        or product["product_id"] != terms["product_id"]
        or product["profile_id"] != terms["product_profile_id"]
        or product["version"] != terms["product_profile_version"]
        or product["origin"] != terms["product_origin"]
        or product["ncm"] != rule.selector.ncm_prefix
        or not rule.is_effective_at(issued)
        or not rule.is_effective_at(now)
    ):
        raise IssuanceApprovalRequired("operation differs from reviewed issuance terms")
    expected = TaxDecision(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        source_normative=rule.source_normative,
        outcome=rule.outcome,
        rank=rule.rank,
    )
    if _tax_decision(expected) != decision:
        raise IssuanceApprovalRequired("fiscal decision differs from reviewed issuance rule")
    return {
        "line_number": line["line_number"],
        "benefit_code": benefit["code"],
        "benefit_id": subject["benefit_id"],
        "benefit_version": subject["benefit_version"],
        "benefit_digest": subject["benefit_digest"],
        "snapshot_id": subject["snapshot_id"],
        "snapshot_version": subject["snapshot_version"],
        "snapshot_digest": subject["snapshot_digest"],
        "subject_digest": report["subject_digest"],
        "review_record_id": report["record_id"],
        "review_version": report["current_version"],
        "review_event_digest": event["event_digest"],
        "actor_id": event["actor_id"],
        "opinion_reference": event["opinion_reference"],
        "competence": period.isoformat(),
        "terms_digest": _digest(terms)[1],
        "rule_id": rule.rule_id,
        "rule_version": rule.version,
        "product_profile_id": product["profile_id"],
        "product_profile_version": product["version"],
        "line_digest": _digest(line)[1],
    }


@contextmanager
def current_issuance_claims(
    factory: FiscalUnitOfWorkFactory,
    scope: ExecutionScope,
    document: dict[str, Any],
    now: datetime,
) -> Iterator[list[dict[str, Any]]]:
    """Hold the scoped economy lock through the caller's durable local commit."""
    lines = _benefit_lines(document)
    if not lines:
        yield []
        return
    economy = getattr(factory, "economy", None)
    if (
        not callable(economy)
        or os.environ.get("NFCORE_ECONOMY_ENABLED") != "true"
        or scope.environment is not FiscalEnvironment.HOMOLOGATION
        or document["document_kind"] != "nfe"
    ):
        raise IssuanceApprovalRequired("T14 issuance authority unavailable or unsupported")
    with economy(scope) as store:
        try:
            issued = datetime.fromisoformat(document["issued_at"])
            if issued > now or _month(issued) != _month(now):
                raise IssuanceApprovalRequired("T14 requires current issuance competence")
            expected_scope = document["scope"]
            if (
                expected_scope.get("host_namespace") != scope.host_namespace
                or expected_scope["tenant_id"] != scope.tenant_id
                or expected_scope["unit_id"] != scope.unit_id
                or expected_scope["environment"] != scope.environment.value
            ):
                raise IssuanceApprovalRequired("T14 issuance scope mismatch")
            store.lock_accounting_issuance()
            _current_profiles(factory, scope, document, lines, issued, now)
            claims = [
                _claim_line(store, factory, scope, document, line, issued, now) for line in lines
            ]
        except IssuanceApprovalRequired:
            raise
        except (
            FiscalValidationError,
            PersistenceStateError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise IssuanceApprovalRequired("current fiscal application evidence invalid") from exc
        yield claims


def xml_benefit_codes(xml: bytes) -> list[tuple[int, str]]:
    """Extract all benefit codes from the signed document, not browser fields."""
    try:
        root = etree.fromstring(
            xml,
            parser=etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
            ),
        )
    except etree.XMLSyntaxError:
        if b"cBenef" in xml:
            raise IssuanceApprovalRequired("invalid benefit-bearing XML") from None
        # Existing gateway remains responsible for ordinary XML validation.
        return []
    result: list[tuple[int, str]] = []
    for node in root.iter("{*}cBenef"):
        parent = node.getparent()
        det = parent.getparent() if parent is not None else None
        value = node.text
        if (
            parent is None
            or det is None
            or etree.QName(parent).localname != "prod"
            or etree.QName(det).localname != "det"
            or not value
        ):
            raise IssuanceApprovalRequired("invalid benefit XML location")
        try:
            number = int(det.get("nItem", ""))
        except ValueError as exc:
            raise IssuanceApprovalRequired("invalid benefit XML line") from exc
        result.append((number, value))
    if len({number for number, _ in result}) != len(result):
        raise IssuanceApprovalRequired("ambiguous benefit XML line")
    return result


def proof_bytes(claims: list[dict[str, Any]], fingerprint: str, signed: bytes) -> bytes:
    codes = [(item["line_number"], item["benefit_code"]) for item in claims]
    if xml_benefit_codes(signed) != codes:
        raise IssuanceApprovalRequired("signed XML differs from approved benefit lines")
    return json.dumps(
        {
            "schema_version": SCHEMA,
            "request_fingerprint": fingerprint,
            "signed_xml_sha256": hashlib.sha256(signed).hexdigest(),
            "claims": claims,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@contextmanager
def revalidate_dispatch(
    factory: FiscalUnitOfWorkFactory,
    uow: FiscalUnitOfWork,
    document_id: str,
    request: AuthorizationRequest,
    now: datetime,
) -> Iterator[None]:
    """Guard only a NEW dispatch claim, not reconciliation or durable replay."""
    entries = uow.archive.list_for_document(request.scope, document_id)
    proofs = [entry for entry in entries if entry.media_type == MEDIA_TYPE]
    codes = xml_benefit_codes(request.signed_xml)
    if not proofs and not codes:
        yield
        return
    inputs = [entry for entry in entries if entry.media_type == INPUT_MEDIA_TYPE]
    if len(proofs) != 1 or len(inputs) != 1 or not codes:
        raise IssuanceApprovalRequired("benefit XML lacks unique durable approval evidence")
    try:
        raw = inputs[0].content
        if hashlib.sha256(raw).hexdigest() != request.request_fingerprint:
            raise IssuanceApprovalRequired("prepared benefit fingerprint mismatch")
        document = json.loads(raw)["document"]
        if document["document_id"] != document_id:
            raise IssuanceApprovalRequired("prepared benefit document mismatch")
    except (ValueError, KeyError, TypeError) as exc:
        raise IssuanceApprovalRequired("invalid durable issuance evidence") from exc
    with current_issuance_claims(factory, request.scope, document, now) as claims:
        if (
            not claims
            or proof_bytes(claims, request.request_fingerprint, request.signed_xml)
            != proofs[0].content
        ):
            raise IssuanceApprovalRequired("accounting approval or signed fiscal evidence changed")
        yield
