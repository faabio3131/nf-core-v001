"""T20: scoped accounting dossier, bound to the canonical T15–T19 evidence.

Only the T01 store persists the document and its immutable archive. No credit,
approval, tax calculation, fiscal operation, or external transmission is created.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from kordena_fiscal.application.credit_ledger import (
    VerifiedRecoveryBundle,
    history,
    journal_id,
    verify_recovery_bundle,
)
from kordena_fiscal.application.historical_audit import (
    MAX_INPUT_BYTES,
    TABLE,
    record_id,
    source_bundle,
)
from kordena_fiscal.application.recovery_lifecycle import _canonical_guard, report
from kordena_fiscal.application.unused_credits import verify_credit_unit
from kordena_fiscal.archive.accounting_dossier import (
    MAX_FILES,
    MAX_PACKAGE,
    MAX_TOTAL,
    SCHEMA,
    digest,
    json_bytes,
    render_package,
    verify_package,
)
from kordena_fiscal.cognitive.historical_audit_api import historical_issuer_context
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanIdentityService,
    PortalPermission,
    PortalRole,
)
from kordena_fiscal.tax.historical_audit import IssuerContext, closed_months, source_bytes

LOCAL = ZoneInfo("America/Sao_Paulo")
CHUNK = 384 * 1024
MAX_CANDIDATES = 1000
HASH = re.compile(r"^[0-9a-f]{64}$")
ARCHIVE_SCHEMA = "nfcore.accounting-dossier-archive/v1"
PART_SCHEMA = "nfcore.accounting-dossier-part/v1"


class DossierAuthorityError(FiscalValidationError):
    """A fresh designated-accountant session or canonical unit is required."""


class DossierStepUpRequired(DossierAuthorityError):
    """Prompt for the existing canonical MFA step-up, never a second factor service."""


def _ref(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("record_id", "version", "digest")}


def _source_key(issuer: Cnpj, period: date) -> str:
    return f"tax-recovery-{issuer.value}-{period.isoformat()}"


def _bundle(
    store: EconomyStore, issuer: Cnpj, period: date, context: IssuerContext, today: date,
) -> VerifiedRecoveryBundle:
    closed_months(period, today)
    row = store.record(TABLE, _source_key(issuer, period))
    if row is None:
        raise FiscalValidationError("reviewed T17 source unavailable")
    # The canonical T17 verifier requires the current local date, including
    # its reviewed prescription clock, legal validity and official SELIC cutoff.
    return verify_recovery_bundle(
        store, issuer, period, row["version"], row["digest"], context, today,
    )


def _selected(bundle: VerifiedRecoveryBundle, finding_id: str) -> dict[str, Any]:
    rows = [row for row in bundle.findings if row["finding_id"] == finding_id]
    if len(rows) != 1 or rows[0]["status"] != "potential":
        raise FiscalValidationError("reviewable T17 finding unavailable")
    row = rows[0]
    if row["credit_recognized"] is not False or any(
        type(row[name]) is not int or row[name] < 0
        for name in ("principal_cents", "adjustment_cents", "estimated_cents")
    ):
        raise FiscalValidationError("invalid advisory finding")
    return row


def _original(model: Any, expected: str, *, unicode: bool = False) -> bytes:
    raw = json_bytes(model.model_dump(), unicode=unicode)
    if len(raw) > MAX_INPUT_BYTES or digest(raw) != expected:
        raise FiscalValidationError("dossier original input digest mismatch")
    return raw


def _evidence(
    store: EconomyStore, issuer: Cnpj, period: date, bundle: VerifiedRecoveryBundle,
) -> tuple[dict[str, bytes], dict[str, Any] | None]:
    """Original month-scoped inputs and XMLs needed for independent recomputation."""
    files = {
        "fontes/t17.json": _original(bundle.facts, bundle.index["content"]["input_sha256"]),
        "fontes/t16.json": _original(bundle.batch, bundle.t16_index["input_sha256"]),
    }
    size = sum(map(len, files.values()))

    def add(name: str, raw: bytes) -> None:
        nonlocal size
        if name in files:
            if files[name] != raw:
                raise FiscalValidationError("dossier evidence identity collision")
            return
        size += len(raw)
        if len(files) + 7 > MAX_FILES or size > MAX_TOTAL:
            raise FiscalValidationError("dossier evidence bound exceeded")
        files[name] = raw

    for purchase in bundle.batch.purchases:
        add(f"xml/t16-{purchase.xml.sha256}.xml", purchase.xml.contents())
        add(f"provas/{purchase.status_evidence.sha256}.bin", purchase.status_evidence.contents())
        for use in purchase.uses:
            item = use.eligibility_evidence
            add(f"provas/{item.sha256}.bin", item.contents())
    for rule in bundle.batch.rules:
        add(f"provas/{rule.legal_source.sha256}.bin", rule.legal_source.contents())
    if bundle.batch.books is not None:
        book = bundle.batch.books.source
        add(f"provas/{book.sha256}.bin", book.contents())
    for reviewed in bundle.facts.claims:
        for proof in (reviewed.review, reviewed.legal_source, reviewed.corrected_assessment):
            if proof is not None:
                add(f"provas/{proof.sha256}.bin", proof.contents())
    prior = None
    if bundle.t16_index["historical_digest"] is not None:
        prior = store.record(TABLE, record_id(issuer, period))
        if prior is None or prior["digest"] != bundle.t16_index["historical_digest"]:
            raise FiscalValidationError("dossier historical binding changed")
        original = source_bundle(store, issuer, period, prior)
        add("fontes/t15.json", _original(
            original, prior["content"]["input_sha256"], unicode=True,
        ))
        for doc in original.documents:
            add(f"xml/t15-{doc.xml_sha256}.xml", source_bytes(doc.xml_b64, doc.xml_sha256))
        for artifact in original.artifacts:
            add(f"provas/{artifact.sha256}.bin", source_bytes(
                artifact.data_b64, artifact.sha256,
            ))
    return files, prior


def _history(
    store: EconomyStore, issuer: Cnpj, period: date, finding_id: str, today: date,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    # Reuse the T19 reconciler and T18 replay, never derive balances from export data.
    state = report(store, issuer, today)
    cases = [
        case for case in state["cases"]
        if case["terms"]["finding_id"] == finding_id
        and case["terms"]["competence"] == period.isoformat()
    ]
    ledger = (
        history(store, issuer, period, finding_id)
        if store.record(TABLE, journal_id(issuer, finding_id)) is not None else None
    )
    links = [
        (link["version"], link["digest"])
        for case in cases for event in case["events"]
        for link in event["content"]["ledger_links"]
    ]
    managed = [
        (row["version"], row["digest"])
        for row in (ledger["events"] if ledger is not None else [])
        if row["content"]["reviewed"]["command"]["request_id"].casefold().startswith("t19-")
    ]
    # Extra export completeness check, not a new monetary authority.
    if len(links) != len(set(links)) or sorted(links) != sorted(managed):
        raise FiscalValidationError("dossier case-to-ledger evidence incomplete")
    return ledger, cases


def _load_archive(
    store: EconomyStore, issuer: Cnpj, period: date, dossier: dict[str, Any],
    key: str, basis_digest: str,
) -> bytes:
    version = dossier["version"]
    archive_key = f"{key}-archive"
    archive = store.record(TABLE, archive_key, version)
    if (
        archive is None or dossier["archive_reference"] != f"snapshot:{archive_key}:{version}"
        or archive["issuer_cnpj"] != issuer.value or archive["competence"] != period.isoformat()
    ):
        raise FiscalValidationError("dossier archive reference mismatch")
    index = archive["content"]
    if (
        index["schema_version"] != ARCHIVE_SCHEMA
        or index["basis_digest"] != basis_digest or index["sha256"] != dossier["digest"]
        or not 0 < index["bytes"] <= MAX_PACKAGE
        or not 1 <= len(index["parts"]) <= (MAX_PACKAGE + CHUNK - 1) // CHUNK
    ):
        raise FiscalValidationError("dossier archive index mismatch")
    parts = []
    for number, ref in enumerate(index["parts"]):
        child = store.record(TABLE, f"{archive_key}-{number}", version)
        if (
            child is None or ref != _ref(child)
            or child["issuer_cnpj"] != issuer.value
            or child["competence"] != period.isoformat()
            or child["content"]["schema_version"] != PART_SCHEMA
            or child["content"]["basis_digest"] != basis_digest
        ):
            raise FiscalValidationError("dossier archive part mismatch")
        data = base64.b64decode(child["content"]["data_b64"], validate=True)
        if (
            not 0 < len(data) <= CHUNK or digest(data) != child["content"]["sha256"]
            or (number < len(index["parts"]) - 1 and len(data) != CHUNK)
        ):
            raise FiscalValidationError("dossier archive part digest mismatch")
        parts.append(data)
    raw = b"".join(parts)
    if len(raw) != index["bytes"] or digest(raw) != index["sha256"]:
        raise FiscalValidationError("dossier archive digest mismatch")
    verify_package(raw, basis_digest)
    return raw


def _persist(
    store: EconomyStore, issuer: Cnpj, period: date, key: str, version: int,
    basis: dict[str, Any], basis_digest: str, raw: bytes, estimated: int,
) -> None:
    archive_key = f"{key}-archive"
    opportunity_key = f"{key}-opportunity"
    parts = []
    for number, offset in enumerate(range(0, len(raw), CHUNK)):
        part = raw[offset:offset + CHUNK]
        child = f"{archive_key}-{number}"
        fingerprint = store.append_snapshot(
            record_id=child, version=version, competence=period, issuer=issuer,
            content={
                "schema_version": PART_SCHEMA, "basis_digest": basis_digest,
                "sha256": digest(part), "data_b64": base64.b64encode(part).decode("ascii"),
            },
        )
        parts.append({"record_id": child, "version": version, "digest": fingerprint})
    store.append_snapshot(
        record_id=archive_key, version=version, competence=period, issuer=issuer,
        content={
            "schema_version": ARCHIVE_SCHEMA, "basis_digest": basis_digest,
            "sha256": digest(raw), "bytes": len(raw), "parts": parts,
        },
    )
    # Documentary projection for the existing mandatory T01 opportunity FK.
    store.append_opportunity(
        record_id=opportunity_key, version=version,
        snapshot_id=basis["t17"]["record_id"], snapshot_version=basis["t17"]["version"],
        benefit_id=None, benefit_version=None, estimated_cents=estimated,
        content={
            "schema_version": SCHEMA, "basis": basis, "basis_digest": basis_digest,
            "advisory_only": True, "credit_recognized": False,
            "realized_cents": None, "issuance_authorized": False,
        },
    )
    store.append_dossier(
        record_id=key, version=version, opportunity_id=opportunity_key,
        opportunity_version=version, archive_reference=f"snapshot:{archive_key}:{version}",
        digest=digest(raw),
    )


class AccountingDossierService:
    """Server-owned identity, scope and transactions; no caller-supplied monetary facts."""

    def __init__(
        self, db: PostgresFiscalDatabase, identity: HumanIdentityService,
        step_up: Callable[[str, datetime], bool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db, self.identity, self.step_up, self.clock = db, identity, step_up, clock

    def _authority(
        self, token: str, csrf: str, unit_id: str, now: datetime,
    ) -> AuthenticatedHuman:
        human = self.identity.authenticate_session(session_token=token, now=now)
        self.identity.assert_csrf(human, csrf)
        human.assert_permission(PortalPermission.AUDIT_READ, unit_id=unit_id)
        if (
            human.account.role is not PortalRole.ACCOUNTANT
            or human.account.unit_ids is None or unit_id not in human.account.unit_ids
        ):
            raise DossierAuthorityError("designated accountant required")
        if not self.step_up(human.session_id, now):
            raise DossierStepUpRequired("recent MFA required")
        return human

    @contextmanager
    def _scoped(
        self, token: str, csrf: str, unit_id: str, period: date,
    ) -> Iterator[tuple[EconomyStore, Cnpj, IssuerContext, AuthenticatedHuman, datetime]]:
        now = self.clock()
        human = self._authority(token, csrf, unit_id, now)
        scope = ExecutionScope(
            human.tenant_id, unit_id, FiscalEnvironment.HOMOLOGATION, "t20-dossier", "fm-nfcore",
        )
        with _canonical_guard(self.db):
            issuer, context = historical_issuer_context(self.db, scope, period)
            with self.db() as uow:
                unit = uow.control_plane.get_unit(scope.tenant_id, scope.unit_id)
                active = uow.control_plane.resolve_profile(
                    host_namespace="fm-nfcore", tenant_id=scope.tenant_id,
                    unit_id=scope.unit_id, environment=scope.environment, instant=now,
                )
            if (
                unit is None or scope.environment not in unit.enabled_environments
                or active is None or active.cnpj != issuer
                or active.scope.identity_material != scope.identity_material
            ):
                raise DossierAuthorityError("active canonical accounting unit required")
            verify_credit_unit(self.db, scope, issuer)
            with self.db.economy(scope) as store:
                store.lock_accounting_issuance()
                current = self._authority(token, csrf, unit_id, self.clock())
                if current.account != human.account or current.session_id != human.session_id:
                    raise DossierAuthorityError("accounting authority changed")
                yield store, issuer, context, human, now
                finished = self.clock()
                if finished.astimezone(LOCAL).date() != now.astimezone(LOCAL).date():
                    raise FiscalValidationError("dossier source cutoff changed during export")
                current = self._authority(token, csrf, unit_id, finished)
                if current.account != human.account or current.session_id != human.session_id:
                    raise DossierAuthorityError("accounting authority changed")

    def candidates(self, token: str, csrf: str, unit_id: str, period: date) -> dict[str, Any]:
        with self._scoped(token, csrf, unit_id, period) as (store, issuer, context, _, now):
            bundle = _bundle(store, issuer, period, context, now.astimezone(LOCAL).date())
            items = [
                {
                    "finding_id": row["finding_id"], "tax": row["tax"],
                    "modality": row["modality"], "estimated_cents": str(row["estimated_cents"]),
                }
                for row in bundle.findings if row["status"] == "potential"
            ]
            if len(items) > MAX_CANDIDATES:
                raise FiscalValidationError("dossier candidate bound exceeded")
            return {
                "source": _ref(bundle.index), "as_of": bundle.index["content"]["as_of"],
                "candidates": items, "simulation_only": True, "credit_recognized": False,
            }

    def export(
        self, token: str, csrf: str, unit_id: str, period: date,
        finding_id: str, source_version: int, source_digest: str,
    ) -> bytes:
        if (
            not isinstance(finding_id, str) or not HASH.fullmatch(finding_id)
            or type(source_version) is not int or not 1 <= source_version <= 2147483647
            or not isinstance(source_digest, str) or not HASH.fullmatch(source_digest)
        ):
            raise FiscalValidationError("invalid dossier selection")
        with self._scoped(token, csrf, unit_id, period) as (store, issuer, context, human, now):
            today = now.astimezone(LOCAL).date()
            bundle = _bundle(store, issuer, period, context, today)
            if bundle.index["version"] != source_version or bundle.index["digest"] != source_digest:
                raise FiscalValidationError("dossier selection changed; refresh candidates")
            finding = _selected(bundle, finding_id)
            matches = [row for row in bundle.t16_findings if row["identity"] == finding_id]
            if len(matches) != 1:
                raise FiscalValidationError("dossier T16 finding missing")
            t16 = matches[0]
            files, prior = _evidence(store, issuer, period, bundle)
            ledger, cases = _history(store, issuer, period, finding_id, today)
            case_summary = [
                {
                    "case_id": case["terms"]["case_id"], "status": case["status"],
                    "version": case["version"], "digest": case["digest"], "terms": case["terms"],
                }
                for case in cases
            ]
            ledger_refs = [_ref(row) for row in ledger["events"]] if ledger else []
            basis = {
                "scope": list(store.scope_identity), "issuer": issuer.value,
                "competence": period.isoformat(), "finding_id": finding_id,
                "actor_id": human.account.account_id, "t17": _ref(bundle.index),
                "t16": {
                    "version": bundle.facts.t16_version, "digest": bundle.facts.t16_digest,
                },
                "t15": _ref(prior) if prior is not None else None,
                "ledger": ledger_refs,
                "cases": case_summary,
            }
            basis_digest = digest(json_bytes(basis))
            key = "t20-dossier-" + digest(json_bytes({
                "scope": basis["scope"], "issuer": issuer.value, "period": period.isoformat(),
                "finding_id": finding_id, "actor": human.account.account_id,
            }))
            previous = store.record("fm_economy_dossiers", key)
            version = previous["version"] + 1 if previous is not None else 1
            if previous is not None:
                opportunity = store.record(
                    "fm_economy_opportunities", f"{key}-opportunity", previous["version"],
                )
                if (
                    opportunity is None or previous["opportunity_id"] != f"{key}-opportunity"
                    or previous["opportunity_version"] != previous["version"]
                    or opportunity["content"]["schema_version"] != SCHEMA
                    or opportunity["content"]["basis_digest"]
                    != digest(json_bytes(opportunity["content"]["basis"]))
                ):
                    raise FiscalValidationError("dossier opportunity binding mismatch")
                if opportunity["content"]["basis_digest"] == basis_digest:
                    if (
                        opportunity["snapshot_id"] != bundle.index["record_id"]
                        or opportunity["snapshot_version"] != source_version
                        or opportunity["estimated_cents"] != finding["estimated_cents"]
                        or opportunity["benefit_id"] is not None
                        or opportunity["content"]["basis"] != basis
                        or opportunity["content"]["advisory_only"] is not True
                        or opportunity["content"]["credit_recognized"] is not False
                        or opportunity["content"]["realized_cents"] is not None
                        or opportunity["content"]["issuance_authorized"] is not False
                    ):
                        raise FiscalValidationError("dossier replay evidence mismatch")
                    return _load_archive(store, issuer, period, previous, key, basis_digest)
            files["fontes/ledger-t18.json"] = json_bytes(ledger)
            files["fontes/casos-t19.json"] = json_bytes([
                {k: v for k, v in case.items() if k != "alert"} for case in cases
            ])
            identification = {
                **{k: v for k, v in basis.items() if k not in {"ledger", "cases"}},
                "ledger_events": len(ledger_refs), "case_count": len(case_summary),
                "basis_digest": basis_digest, "dossier_id": key,
                "dossier_version": version, "generated_at": now.isoformat(),
                "source_cutoff": bundle.index["content"]["as_of"],
                "issuer_context": context.model_dump(),
            }
            # The review is preparatory; T13 approves benefit/comparison, not this claim.
            opinion = {
                "status": "PENDENTE DE REVISÃO E ASSINATURA HUMANA",
                "basis": "Candidato T17 revalidado no corte atual; provas do mês anexadas.",
                "evidence_scope": (
                    "XMLs T15/T16 incluem contexto mensal para recomputação; "
                    "nem todo anexo é prova direta do achado selecionado."
                ),
                "limits": "Sem reconhecimento, liquidação ou autorização fiscal real.",
                "t13": "Não aplicável a achado de recuperação; nenhuma aprovação presumida.",
                "action": (
                    "Conferir base legal, provas, memória, vigência e histórico antes de assinar."
                ),
                "residual_gate": "Refinamentos #625 obrigatórios antes de T21/Portal/produção.",
            }
            payload = {
                "identification": identification, "basis": basis, "t16": t16, "t17": finding,
                "simulation_only": True, "credit_recognized": False,
                "legal": {"t16": t16["citation"], "t17": finding["citation"],
                          "policy": finding["policy"], "selic": bundle.index["content"]["selic"]},
                "ledger_summary": ledger["balances"] if ledger else None,
                "cases": case_summary, "opinion": opinion,
            }
            raw = render_package(payload, files)
            _persist(store, issuer, period, key, version, basis, basis_digest, raw,
                     finding["estimated_cents"])
            return raw
