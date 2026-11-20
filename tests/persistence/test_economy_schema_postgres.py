"""PostgreSQL T01 schema rehearsal: real SQL, RLS and immutable rows."""
import os
from datetime import date
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from kordena_fiscal.cognitive import CognitiveAdviceService, default_baselines
from kordena_fiscal.cognitive.contracts import AdviceRequest
from kordena_fiscal.cognitive.economy_contract import AGENTS, project_economy
from kordena_fiscal.cognitive.economy_reader import read_economy_evidence
from kordena_fiscal.domain import Cnpj, ExecutionScope, FiscalEnvironment, FiscalValidationError
from kordena_fiscal.persistence.economy_schema import (
    ECONOMY_VERSION,
    SCOPE_PREDICATE,
    TABLES,
    is_scope_predicate,
)
from kordena_fiscal.persistence.economy_store import EconomyStore
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase


def _scope(tenant="tenant-a", unit="unit-a", host="fm-nfcore",
           environment=FiscalEnvironment.HOMOLOGATION):
    return ExecutionScope(tenant, unit, environment, "test", host)


def test_real_postgres_economy_schema_scope_and_immutability(monkeypatch):
    dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("real PostgreSQL required for T01")
    suffix = uuid4().hex
    schema_name = "economy_test_" + suffix
    role_name = "economy_role_" + suffix
    # Existing CI database role is responsible for sandbox DDL only.
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
            sql.Identifier(role_name)
        ))
        database = None
        try:
            uri = urlsplit(dsn)
            query = dict(parse_qsl(uri.query, keep_blank_values=True))
            query["options"] = f"-c search_path={schema_name}"
            database = PostgresFiscalDatabase(
                urlunsplit(uri._replace(query=urlencode(query, quote_via=quote)))
            )
            assert ECONOMY_VERSION not in database.initialize()
            assert database.initialize(
                enable_economy=True, economy_runtime_role=role_name,
            ) == (ECONOMY_VERSION,)
            assert database.initialize(enable_economy=True) == ()
            assert database.applied_migrations()[-1] == ECONOMY_VERSION
            monkeypatch.setenv("NFCORE_ECONOMY_ENABLED", "true")
            monkeypatch.setenv("NFCORE_ECONOMY_RUNTIME_ROLE", role_name)
            with database.economy(_scope(tenant="tenant-migration")) as scoped:
                scoped.append_snapshot(
                    record_id="migration-proof", version=1, competence=date(2026, 11, 1),
                    issuer=Cnpj("12345678000195"), content={"revenue_cents": 10},
                )
            with database.economy(_scope(tenant="tenant-b")) as scoped:
                assert scoped.snapshot("migration-proof", 1) is None
            with database.economy(_scope(tenant="tenant-migration")) as scoped:
                assert scoped.snapshot("migration-proof", 1) == {"revenue_cents": 10}
            with database.economy(_scope(tenant="tenant-c")) as scoped:
                scoped.append_snapshot(
                    record_id="migration-proof", version=1, competence=date(2026, 11, 1),
                    issuer=Cnpj("12345678000195"), content={"revenue_cents": 20},
                )
            _certify_t02_read_only(database)
            _certify_t05(database)
            _certify_t06(database)
            _certify_t07_transition(database)
            _certify_t08_federal(database)
            admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            # Explicitly add DML permissions only in this sandbox to prove
            # that the RLS policies, not solely GRANTs, deny mutation.
            for table in TABLES:
                admin.execute(sql.SQL("GRANT UPDATE, DELETE ON {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(role_name),
                ))
            # Keep the subsequent original tests in a distinct partition.
            with psycopg.connect(dsn, autocommit=True) as runtime:
                runtime.execute(sql.SQL("SET search_path TO {}").format(
                    sql.Identifier(schema_name)
                ))
                with pytest.raises(FiscalValidationError, match="bypass RLS"):
                    with EconomyStore.transaction(runtime, _scope()):
                        pass
                runtime.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role_name)))
                with EconomyStore.transaction(runtime, _scope()) as store:
                    digest = store.append_snapshot(
                        record_id="s", version=1, competence=date(2026, 11, 1),
                        issuer=Cnpj("12345678000195"), content={"revenue_cents": 100},
                    )
                    assert len(digest) == 64
                    assert store.snapshot("s", 1) == {"revenue_cents": 100}
                    store.append_benefit(
                        record_id="b", version=1, tax_code="ICMS", jurisdiction="SP",
                        normative_reference="synthetic-only", valid_from=date(2026, 1, 1),
                        valid_until=date(2027, 1, 1), content={"eligible": False},
                    )
                    store.append_opportunity(
                        record_id="o", version=1, snapshot_id="s", snapshot_version=1,
                        benefit_id="b", benefit_version=1, estimated_cents=10,
                        content={"status": "potential"},
                    )
                    store.append_credit_entry(
                        record_id="credit", opportunity_id="o", opportunity_version=1,
                        tax_code="ICMS", competence=date(2026, 11, 1),
                        movement="identified", amount_cents=10,
                        evidence_reference="synthetic-only",
                    )
                    store.append_dossier(
                        record_id="d", version=1, opportunity_id="o", opportunity_version=1,
                        archive_reference="synthetic-only", digest=digest,
                    )
                    for table in TABLES:
                        assert len(store.records(table)) == 1
                    assert runtime.execute(
                        "UPDATE fm_economy_snapshots SET version=2"
                    ).rowcount == 0
                    assert runtime.execute("DELETE FROM fm_economy_snapshots").rowcount == 0
                with pytest.raises(FiscalValidationError, match="active scoped transaction"):
                    store.records("fm_economy_snapshots")
                with pytest.raises(FiscalValidationError, match="active scoped transaction"):
                    EconomyStore(runtime, _scope()).snapshot("s", 1)
                assert runtime.execute(
                    "SELECT count(*) FROM fm_economy_snapshots"
                ).fetchone() == (0,)
                with pytest.raises(RuntimeError, match="force rollback"):
                    with EconomyStore.transaction(runtime, _scope()) as rollback_store:
                        rollback_store.append_snapshot(
                            record_id="rolled-back", version=1, competence=date(2026, 11, 1),
                            issuer=Cnpj("12345678000195"), content={"revenue_cents": 100},
                        )
                        raise RuntimeError("force rollback")
                with EconomyStore.transaction(runtime, _scope()) as rollback_store:
                    assert rollback_store.snapshot("rolled-back", 1) is None
                for scope in (
                    _scope(tenant="tenant-b"), _scope(unit="unit-b"), _scope(host="other"),
                    _scope(environment=FiscalEnvironment.PRODUCTION),
                ):
                    with EconomyStore.transaction(runtime, scope) as store:
                        assert store.snapshot("s", 1) is None
                        for table in TABLES:
                            assert store.records(table) == ()
                        assert runtime.execute(
                            "SELECT count(*) FROM fm_economy_snapshots"
                        ).fetchone() == (0,)
                with EconomyStore.transaction(runtime, _scope()) as store:
                    assert store.snapshot("s", 1) == {"revenue_cents": 100}
                    with pytest.raises(FiscalValidationError, match="exact values"):
                        store.append_snapshot(
                            record_id="invalid", version=1, competence=date(2026, 11, 1),
                            issuer=Cnpj("12345678000195"), content={"value": 0.1},
                        )
                    with pytest.raises(psycopg.errors.UniqueViolation):
                        with runtime.transaction():
                            store.append_snapshot(
                                record_id="s", version=1, competence=date(2026, 11, 1),
                                issuer=Cnpj("12345678000195"), content={"revenue_cents": 999},
                            )
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    with EconomyStore.transaction(runtime, _scope(tenant="tenant-b")) as store:
                        store.append_opportunity(
                            record_id="foreign", version=1, snapshot_id="s", snapshot_version=1,
                            benefit_id=None, benefit_version=None, estimated_cents=1, content={},
                        )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with EconomyStore.transaction(runtime, _scope()):
                        runtime.execute(
                            """INSERT INTO fm_economy_snapshots
                            SELECT host_namespace, 'tenant-b', unit_id, environment, record_id,
                                version, competence, issuer_cnpj, content, digest, created_at
                            FROM fm_economy_snapshots"""
                        )
        finally:
            if database is not None:
                database.close()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def test_rls_predicate_pin_rejects_tenant_bypass():
    assert is_scope_predicate(SCOPE_PREDICATE)
    assert is_scope_predicate("(" + SCOPE_PREDICATE.replace("',", "'::text,") + ")")
    assert not is_scope_predicate("true")
    assert not is_scope_predicate(SCOPE_PREDICATE.replace(" AND ", " OR ", 1))
    assert not is_scope_predicate(SCOPE_PREDICATE.replace("nfcore.economy_unit_id", "other"))
    assert not is_scope_predicate(SCOPE_PREDICATE.replace(
        "nfcore.economy_unit_id", "nfcore.economy_unit_id "
    ))
    assert not is_scope_predicate(42)


def _certify_t02_read_only(database):
    from functools import partial

    scope = _scope(tenant="economy-t02")
    issuer = Cnpj("12345678000195")
    with database.economy(scope) as store:
        snap_hash = store.append_snapshot(
            record_id="snap-t02", version=1, competence=date(2026, 11, 1),
            issuer=issuer, content={"restricted_detail": "DO_NOT_SEND_TO_MODEL"},
        )
        rule_hash = store.append_benefit(
            record_id="rule-t02", version=1, tax_code="ICMS", jurisdiction="SP",
            normative_reference="synthetic-only", valid_from=date(2026, 1, 1),
            valid_until=date(2027, 1, 1), content={
                "review_status": "reviewed", "review_reference": "fixture-review",
                "legal_citations": [{
                    "act": "Synthetic test act", "provision": "Test article",
                    "source_url": "https://www.gov.br/receitafederal/pt-br",
                    "source_sha256": "c" * 64, "published_on": "2025-01-01",
                    "valid_from": "2026-01-01", "valid_until": "2027-01-01",
                    "review_reference": "fixture-review",
                }],
            },
        )
        for kind in AGENTS.values():
            store.append_opportunity(
                record_id=kind, version=1, snapshot_id="snap-t02", snapshot_version=1,
                benefit_id="rule-t02", benefit_version=1, estimated_cents=12000,
                content={
                    "kind": kind, "rule_digest": rule_hash, "snapshot_digest": snap_hash,
                    "rule_review_reference": "fixture-review",
                    "calculation_status": "deterministic",
                    "engine_version": "test-v1", "calculation_reference": "fixture-calc",
                },
            )
    reader = partial(database.economy, read_only=True)
    for cap, kind in AGENTS.items():
        evidence = read_economy_evidence(reader, scope, cap, kind)
        assert len(evidence) == 2
        assert "DO_NOT_SEND_TO_MODEL" not in repr(evidence)
        request = AdviceRequest(
            scope=scope, request_id=kind, actor_id="synthetic-role",
            granted_capabilities=frozenset({cap}), capability=cap,
            evidence=evidence, subject_id=kind,
        )
        result = CognitiveAdviceService(baselines=default_baselines()).advise(request)
        candidate = project_economy(request, result).candidates[0]
        assert candidate.estimated_cents == 12000
        assert candidate.rule.digest == rule_hash
        assert candidate.snapshot.digest == snap_hash
        for foreign in (
            _scope(tenant="foreign"), _scope(tenant="economy-t02", unit="foreign"),
            _scope(tenant="economy-t02", host="foreign"),
            _scope(tenant="economy-t02", environment=FiscalEnvironment.PRODUCTION),
        ):
            assert read_economy_evidence(reader, foreign, cap, kind) == ()
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with database.economy(scope, read_only=True) as store:
            store.append_snapshot(
                record_id="no-write", version=1, competence=date(2026, 11, 1),
                issuer=issuer, content={},
            )
    with database.economy(scope) as store:
        assert store.snapshot("no-write", 1) is None
        assert len(store.records("fm_economy_opportunities")) == 3


def _certify_t05(database):
    from functools import partial

    from kordena_fiscal.application.simples_diagnostic_service import import_reviewed_inputs
    from kordena_fiscal.tax.simples_nacional import LEGAL_REFERENCES, RULE_DIGEST

    scope = _scope(tenant="economy-t05")
    competence = date(2026, 1, 1)
    content = {
        "schema_version": "nfcore.simples-facts/2026-v1",
        "review_status": "reviewed", "review_reference": "synthetic-fixture-review",
        "opened_month": "2024-01-01", "uf": "SP", "activity": "service_factor_r",
        "company_history_reference": "fixture", "activity_reference": "fixture",
        "optant_reference": "fixture", "ordinary_domestic_base_cents": 100_000,
        "months": [
            {"competence": f"2025-{m:02d}-01", "domestic_cents": 1_500_000,
             "export_cents": 0, "payroll_cents": 0, "evidence_reference": "fixture"}
            for m in range(1, 13)
        ] + [{"competence": "2026-01-01", "domestic_cents": 100_000,
              "export_cents": 0, "payroll_cents": 0, "evidence_reference": "fixture"}],
        "scenario": {
            "next_month": {"competence": "2026-02-01", "domestic_cents": 100_000,
                           "export_cents": 0, "payroll_cents": 0,
                           "evidence_reference": "forecast-fixture"},
            "ordinary_domestic_base_cents": 100_000,
            "additional_pro_labore_cents": 4_648_000,
            "additional_tax_cost_cents": 1000, "cost_reference": "fixture",
        },
    }
    policy = {
        "engine_rule_digest": RULE_DIGEST, "review_status": "reviewed",
        "review_reference": "synthetic-fixture-review",
        "legal_citations": [
            {"act": "Synthetic fixture", "provision": "test", "source_url": url,
             "source_sha256": "c" * 64, "published_on": "2025-01-01",
             "valid_from": "2026-01-01", "valid_until": "2027-01-01",
             "review_reference": "synthetic-fixture-review"} for url in LEGAL_REFERENCES
        ],
    }

    def verify(issuer, facts):
        assert issuer == "12345678000195"
        assert facts.uf == "SP"

    kwargs = dict(
        snapshot_id="t05-snapshot", snapshot_version=1, competence=competence,
        issuer=Cnpj("12345678000195"), content=content, rule_id="t05-rule",
        rule_version=1, rule_content=policy, verify_issuer=verify,
    )
    with database.economy(scope) as store:
        result = import_reviewed_inputs(store, **kwargs)
        assert result == import_reviewed_inputs(store, **kwargs)
        assert len(store.records("fm_economy_opportunities")) == 2
        assert not store.records("fm_economy_credit_entries")
    reader = partial(database.economy, read_only=True)
    for capability, kind in AGENTS.items():
        if kind == "credit":
            continue
        record_id = result["evaluation_ids"][kind]
        evidence = read_economy_evidence(reader, scope, capability, record_id)
        assert len(evidence) == 4
        request = AdviceRequest(
            scope=scope, request_id=kind, actor_id="synthetic-reviewer",
            granted_capabilities=frozenset({capability}), capability=capability,
            evidence=evidence, subject_id=record_id,
        )
        advice = CognitiveAdviceService(baselines=default_baselines()).advise(request)
        candidate = project_economy(request, advice).candidates[0]
        assert candidate.competence == "2026-02-01"
        assert candidate.estimated_cents == result["scenario"]["net_estimated_tax_saving_cents"]
        for foreign in (
            _scope(tenant="foreign"), _scope(tenant="economy-t05", unit="foreign"),
            _scope(tenant="economy-t05", host="foreign"),
            _scope(tenant="economy-t05", environment=FiscalEnvironment.PRODUCTION),
        ):
            assert read_economy_evidence(reader, foreign, capability, record_id) == ()


def _certify_t06(database):
    from copy import deepcopy

    from kordena_fiscal.application.simples_segregation_service import (
        SCHEMA,
        evaluate_segregation,
        import_reviewed_segregation,
    )
    from kordena_fiscal.tax.simples_segregation import SOURCE, VERSION

    scope = _scope(tenant="economy-t06")
    competence = date(2026, 1, 1)
    content = {
        "schema_version": SCHEMA, "review_status": "reviewed",
        "review_reference": "synthetic-fixture-review", "opened_month": "2026-01-01",
        "uf": "SP", "activity": "commerce", "basis": "accrual",
        "company_history_reference": "fixture", "activity_reference": "fixture",
        "optant_reference": "fixture", "domestic_cents": 300, "export_cents": 100,
        "months": [{"competence": "2026-01-01", "domestic_cents": 300,
                    "export_cents": 100, "payroll_cents": 0, "evidence_reference": "fixture"}],
        "lines": [
            {"line_id": key, "cents": 100, "activity": activity, "market": market,
             "federal": federal, "local": local,
             "evidence_reference": "fixture-doc-" + key, "treatment_reference": "fixture-review"}
            for key, activity, market, federal, local in (
                ("a", "commerce", "domestic", "monophase_downstream", "icms_substituted"),
                ("b", "commerce", "domestic", "ordinary", "icms_substitute"),
                ("c", "service_iii", "domestic", "ordinary", "iss_withheld"),
                ("d", "commerce", "export", "ordinary", "ordinary"),
            )
        ],
    }
    policy = {
        "engine_version": VERSION, "review_status": "reviewed",
        "review_reference": "synthetic-fixture-review",
        "legal_citations": [{
            "act": "Synthetic fixture", "provision": "art.25 test", "source_url": SOURCE,
            "source_sha256": "c" * 64, "published_on": "2025-01-01",
            "valid_from": "2026-01-01", "valid_until": "2027-01-01",
            "review_reference": "synthetic-fixture-review",
        }],
    }

    def verify(issuer, facts):
        assert issuer == "12345678000195"
        assert facts.uf == "SP"
        assert facts.competence == competence

    refs = dict(snapshot_id="t06-snapshot", snapshot_version=1, rule_id="t06-rule",
                rule_version=1, verify_issuer=verify)
    kwargs = dict(**refs, competence=competence, issuer=Cnpj("12345678000195"),
                  content=content, rule_content=policy)
    with database.economy(scope) as store:
        result = import_reviewed_segregation(store, **kwargs)
        assert result == import_reviewed_segregation(store, **kwargs)
        assert result["status"] == "classified"
        assert len(result["buckets"]) == 4
        assert sum(b["cents"] for b in result["buckets"]) == 400
        assert len(store.records("fm_economy_snapshots")) == 1
        assert len(store.records("fm_economy_benefits")) == 1
        assert not store.records("fm_economy_opportunities")
        assert not store.records("fm_economy_credit_entries")
        changed = deepcopy(content)
        changed["lines"][0]["treatment_reference"] = "new-reference"
        with pytest.raises(FiscalValidationError, match="immutable"):
            import_reviewed_segregation(store, **{**kwargs, "content": changed})
        invalid = deepcopy(content)
        invalid["domestic_cents"] = 299
        with pytest.raises(FiscalValidationError, match="reconcile"):
            import_reviewed_segregation(
                store, **{**kwargs, "snapshot_id": "invalid", "content": invalid},
            )
        assert store.snapshot("invalid", 1) is None
        assert store.record("fm_economy_benefits", "t06-rule", 1) is not None
    with database.economy(scope, read_only=True) as store:
        assert evaluate_segregation(store, **refs) == result
        assessment = evaluate_segregation(store, **refs, assessment=True)
        assert assessment["status"] == "estimated"
        assert assessment["estimated_das_cents"] == 12
        assert assessment["advisory_only"] is True
        assert assessment == evaluate_segregation(store, **refs, assessment=True)
    # Reference fixtures are synthetic, never evidence of official parity.
    reviewed = deepcopy(content)
    reviewed["pgdas_reference"] = {
        "competence": competence.isoformat(), "review_status": "reviewed",
        "review_reference": "fixture-review", "evidence_reference": "synthetic-pgdas",
        "segregation_digest": assessment["segregation_digest"],
        "assessment_digest": assessment["digest"],
        "tax_cents": assessment["tax_cents"],
        "total_cents": assessment["estimated_das_cents"],
    }
    with database.economy(scope) as store:
        invalid_ref = deepcopy(reviewed)
        invalid_ref["pgdas_reference"]["assessment_digest"] = "stale"
        with pytest.raises(FiscalValidationError, match="scoped"):
            import_reviewed_segregation(store, **{
                **kwargs, "snapshot_id": "invalid-pgdas", "content": invalid_ref,
            })
        assert store.snapshot("invalid-pgdas", 1) is None
        changed_history = deepcopy(reviewed)
        changed_history["company_history_reference"] = "other-reviewed-history"
        with pytest.raises(FiscalValidationError, match="scoped"):
            import_reviewed_segregation(store, **{
                **kwargs, "snapshot_id": "changed-history", "content": changed_history,
            })
        assert store.snapshot("changed-history", 1) is None
        verify_calls = []

        def count_verify(issuer, facts):
            verify_calls.append(issuer)
            return kwargs["verify_issuer"](issuer, facts)

        imported = import_reviewed_segregation(store, **{
            **kwargs, "snapshot_id": "reviewed-pgdas", "content": reviewed,
            "verify_issuer": count_verify,
        })
        assert verify_calls == ["12345678000195"]
        assert imported["status"] == "classified"
        assert "pgdas_comparison" not in imported
        assert imported["buckets"] == result["buckets"]
        # A malformed historical cash record must fail with the domain error,
        # not leak an unhandled KeyError or be treated as an estimate.
        malformed = deepcopy(content)
        malformed["basis"] = "cash"
        store.append_snapshot(
            record_id="invalid-cash-history", version=1, competence=competence,
            issuer=Cnpj("12345678000195"), content=malformed,
        )
    with database.economy(scope, read_only=True) as store:
        comparison = evaluate_segregation(store, **{
            **refs, "snapshot_id": "reviewed-pgdas", "assessment": True,
        })["pgdas_comparison"]
        assert comparison["status"] == "match"
        assert comparison["official_certification"] is False
        with pytest.raises(FiscalValidationError, match="invalid reviewed cash history"):
            evaluate_segregation(store, **{
                **refs, "snapshot_id": "invalid-cash-history", "assessment": True,
            })
    for foreign in (
        _scope(tenant="foreign"), _scope(tenant="economy-t06", unit="foreign"),
        _scope(tenant="economy-t06", host="foreign"),
        _scope(tenant="economy-t06", environment=FiscalEnvironment.PRODUCTION),
    ):
        with database.economy(foreign, read_only=True) as store:
            with pytest.raises(FiscalValidationError, match="unavailable"):
                evaluate_segregation(store, **refs)
    # An identical bundle in another authorized tenant needs its own reference.
    with database.economy(_scope(tenant="economy-t06-other")) as store:
        with pytest.raises(FiscalValidationError, match="scoped"):
            import_reviewed_segregation(store, **{
                **kwargs, "snapshot_id": "cross-scope-pgdas", "content": reviewed,
            })
        assert store.snapshot("cross-scope-pgdas", 1) is None
    blocked = deepcopy(content)
    blocked["lines"][0]["federal"] = "unknown"
    with database.economy(scope) as store:
        outcome = import_reviewed_segregation(
            store, **{**kwargs, "snapshot_version": 2, "content": blocked},
        )
        assert outcome["status"] == "blocked"
        assert outcome["buckets"] == []
    with database.economy(scope, read_only=True) as store:
        assert evaluate_segregation(store, **refs) == result
        assert evaluate_segregation(store, **{**refs, "snapshot_version": 2}) == outcome
        blocked_assessment = evaluate_segregation(
            store, **{**refs, "snapshot_version": 2}, assessment=True,
        )
        assert blocked_assessment["estimated_das_cents"] is None



def _certify_t07_transition(database):
    from copy import deepcopy
    from datetime import UTC, datetime

    from kordena_fiscal.application.simples_segregation_service import (
        TRANSITION_SCHEMA,
        evaluate_segregation,
        import_reviewed_segregation,
    )
    from kordena_fiscal.domain import (
        BrazilianJurisdiction,
        CnaeCode,
        FiscalAddress,
        FiscalProfile,
        StateRegistration,
        TaxRegimeCode,
    )
    from kordena_fiscal.tax.simples_nacional import TRANSITION_PARTITION_DIGEST
    from kordena_fiscal.tax.simples_segregation import SOURCE, TRANSITION_VERSION

    scope = _scope(tenant="economy-t07")
    competence = date(2027, 1, 1)
    profile = FiscalProfile(
        profile_id="t07-test-issuer", scope=scope, cnpj=Cnpj("12345678000195"),
        legal_name="Synthetic T07", tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration("SP", "123456789"),
        primary_cnae=CnaeCode("5611-2/01"),
        address=FiscalAddress(
            street="Rua Exemplo", number="100", district="Centro",
            municipality_name="Sao Paulo", jurisdiction=BrazilianJurisdiction("SP", "3550308"),
            postal_code="01001000",
        ),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    evidence = {
        "scope_identity": list(scope.identity_material),
        "issuer_cnpj": profile.cnpj.value, "profile_id": profile.profile_id,
        "profile_version": profile.version, "crt": int(profile.tax_regime),
        "mode": "simples_unified", "effective_from": "2027-01-01T03:00:00+00:00",
        "source_reference": "synthetic-election", "version": 1,
        "refund_restriction_clear": True,
    }
    content = {
        "schema_version": TRANSITION_SCHEMA, "review_status": "reviewed",
        "review_reference": "synthetic-review", "opened_month": "2027-01-01",
        "uf": "SP", "activity": "commerce", "basis": "accrual",
        "company_history_reference": "fixture", "activity_reference": "fixture",
        "optant_reference": "fixture", "domestic_cents": 100000, "export_cents": 0,
        "months": [{"competence": "2027-01-01", "domestic_cents": 100000,
                    "export_cents": 0, "payroll_cents": 0, "evidence_reference": "fixture"}],
        "lines": [{
            "line_id": "a", "cents": 100000, "activity": "commerce", "market": "domestic",
            "federal": "ordinary", "local": "ordinary", "evidence_reference": "fixture-doc",
            "treatment_reference": "fixture-review",
            "transition_treatments": {
                "cbs": "ordinary", "ibs": "ordinary", "ipi": "non_incident",
                "icms": "ordinary", "iss": "non_incident",
            },
        }],
        "ibs_cbs_election": evidence,
    }
    policy = {
        "engine_version": TRANSITION_VERSION, "review_status": "reviewed",
        "engine_partition_digest": TRANSITION_PARTITION_DIGEST,
        "review_reference": "synthetic-review",
        "legal_citations": [{
            "act": "Synthetic fixture", "provision": "art.22 test", "source_url": SOURCE,
            "source_sha256": "c" * 64, "published_on": "2026-08-04",
            "valid_from": "2027-01-01", "valid_until": "2028-01-01",
            "review_reference": "synthetic-review",
        }],
    }

    def verify(issuer, facts):
        assert issuer == profile.cnpj.value
        assert facts.competence == competence
        return profile

    refs = dict(snapshot_id="t07-snapshot", snapshot_version=1, rule_id="t07-rule",
                rule_version=1, verify_issuer=verify)
    kwargs = dict(**refs, competence=competence, issuer=profile.cnpj,
                  content=content, rule_content=policy)
    with database.economy(scope) as store:
        result = import_reviewed_segregation(store, **kwargs)
        assert result["status"] == "classified"
        assert result == import_reviewed_segregation(store, **kwargs)
        forged = deepcopy(content)
        forged["ibs_cbs_election"]["scope_identity"][0] = "foreign"
        with pytest.raises(FiscalValidationError, match="scope/profile mismatch"):
            import_reviewed_segregation(store, **{
                **kwargs, "snapshot_id": "forged", "content": forged,
            })
        assert store.snapshot("forged", 1) is None
    with database.economy(scope, read_only=True) as store:
        assessment = evaluate_segregation(store, **refs, assessment=True)
        assert assessment["status"] == "estimated"
        assert assessment["estimated_das_cents"] == 4000
        assert assessment["rtc_projection"]["issuance_authorized"] is False
        assert assessment["tax_cents"]["cbs"] == 613
        assert assessment["tax_cents"]["ibs"] == 7
    with database.economy(_scope(tenant="economy-t07-other"), read_only=True) as store:
        with pytest.raises(FiscalValidationError, match="unavailable"):
            evaluate_segregation(store, **refs, assessment=True)



def _certify_t08_federal(database):
    """One real PostgreSQL 16 transaction covers T08 immutable/RLS scope and replay."""
    from kordena_fiscal.application.federal_benefits_service import (
        evaluate_federal_benefit,
        import_reviewed_federal_benefit,
    )
    from kordena_fiscal.tax.federal_benefits import (
        FACTS_SCHEMA, PROGRAMS, RULE_SCHEMA, ReviewedFederalIssuer,
    )
    from kordena_fiscal.tax.regimes import FederalIncomeTaxRegime

    scope = _scope(tenant="economy-t08", unit="unit-a")
    program = PROGRAMS["REIDI"]
    facts = {
        "schema_version": FACTS_SCHEMA, "review_status": "reviewed",
        "review_reference": "t08-review-facts",
        "activity_cnae": "6201501", "operation_ncm": None,
        "operation": program.operation,
        "evidence": {key: "evidence-" + key for key in program.minimum_evidence},
    }
    policy = {
        "schema_version": RULE_SCHEMA, "review_status": "reviewed",
        "review_reference": "t08-review-policy",
        "program_code": program.code, "operation": program.operation,
        "allowed_regimes": ["lucro_real"],
        "cnae_scope": "reviewed_any", "allowed_cnaes": [],
        "ncm_scope": "reviewed_any", "allowed_ncms": [],
        "required_evidence": [], "valid_from": "2026-01-01",
        "valid_until": "2027-01-01",
        "legal_citations": [{
            "act": program.legal_act, "provision": "reviewed-synthetic",
            "source_url": program.official_url, "source_sha256": "b" * 64,
            "published_on": "2025-01-01",
            "valid_from": "2026-01-01", "valid_until": "2027-01-01",
            "review_reference": "t08-review-policy",
        }],
    }

    def verify(cnpj, competence):
        assert cnpj == "12345678000195"
        assert competence == date(2026, 11, 1)
        return ReviewedFederalIssuer(
            cnpj, "6201501", FederalIncomeTaxRegime.LUCRO_REAL,
            scope.identity_material,
        )

    kwargs = dict(
        snapshot_id="t08-snapshot", snapshot_version=1,
        competence=date(2026, 11, 1), issuer=Cnpj("12345678000195"),
        content=facts, benefit_id="t08-benefit",
        benefit_version=1, benefit_content=policy, verify_issuer=verify,
    )
    with database.economy(scope) as store:
        first = import_reviewed_federal_benefit(store, **kwargs)
        assert first["status"] == "potential"
        assert first["advisory_only"] is True
        assert first["issuance_authorized"] is False
        assert first["estimated_cents"] is None
        assert first == import_reviewed_federal_benefit(store, **kwargs)
        assert len(store.records("fm_economy_snapshots")) == 1
        assert len(store.records("fm_economy_benefits")) == 1
        assert not store.records("fm_economy_opportunities")
        incompatible = {**facts, "activity_cnae": "1111111"}
        with pytest.raises(FiscalValidationError, match="canonical"):
            import_reviewed_federal_benefit(store, **{
                **kwargs, "snapshot_id": "t08-forged", "content": incompatible,
            })
        assert store.record("fm_economy_snapshots", "t08-forged", 1) is None
        conflict = {**facts, "evidence": {
            **facts["evidence"], "reidi_habilitation": "replaced",
        }}
        with pytest.raises(FiscalValidationError, match="immutable"):
            import_reviewed_federal_benefit(store, **{**kwargs, "content": conflict})
    with database.economy(scope, read_only=True) as store:
        assert evaluate_federal_benefit(
            store, snapshot_id="t08-snapshot", snapshot_version=1,
            benefit_id="t08-benefit", benefit_version=1, verify_issuer=verify,
        ) == first
    with database.economy(_scope(tenant="economy-t08-foreign"), read_only=True) as store:
        assert store.record("fm_economy_snapshots", "t08-snapshot", 1) is None
        assert store.record("fm_economy_benefits", "t08-benefit", 1) is None
