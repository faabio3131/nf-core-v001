from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.domain import FiscalEnvironment, FiscalValidationError
from kordena_fiscal.lifecycle import FiscalStateSnapshot, IdempotencyKey
from kordena_fiscal.persistence import SqliteFiscalDatabase
from kordena_fiscal.persistence.ports import PersistenceConflictError
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.persistence.sqlite import _MIGRATIONS
from kordena_fiscal.web.human_auth import CSRF_COOKIE, CSRF_HEADER

spec = importlib.util.spec_from_file_location(
    "p02_fixture", Path(__file__).parents[1] / "support/p02_fiscal_fixture.py"
)
assert spec and spec.loader
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.fixture(params=("sqlite", "postgres"))
def database(request, tmp_path):
    if request.param == "postgres":
        dsn = os.environ.get("NFCORE_TEST_POSTGRES_DSN", "")
        if not dsn:
            pytest.skip("real PostgreSQL DSN required; remote CI supplies it")
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("DROP SCHEMA public CASCADE")
            connection.execute("CREATE SCHEMA public")
        database = PostgresFiscalDatabase(dsn)
    else:
        database = SqliteFiscalDatabase(tmp_path / "p02.sqlite3")
    database.initialize()
    fixture.seed(database)
    try:
        yield database
    finally:
        if isinstance(database, PostgresFiscalDatabase):
            database.close()


def client(database, account="operator"):
    result = TestClient(fixture.app(database), base_url="https://nfcore.test")
    assert (
        result.post(
            "/v1/auth/login", json={"email": account + "@example.com", "password": fixture.PASSWORD}
        ).status_code
        == 200
    )
    return result


@pytest.mark.parametrize(
    "surface", ("documents", "issuances", "errors", "reconciliation", "capabilities")
)
def test_five_surfaces_are_durable_scoped_and_sanitized(database, surface):
    http = client(database)
    response = http.get("/v1/portal/surfaces/" + surface, headers={"X-FM-Tenant-Id": "tenant-b"})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert rows
    assert all(row["unit_id"] == "unit-a" and row["environment"] == "homologation" for row in rows)
    assert fixture.PROTECTED not in response.text
    assert "LEGACY-UNSCOPED" not in response.text
    for forbidden in ("DOC-b", "DOC-other", "DOC-host", "DOC-prod", "ARCHIVE-b", "ARCHIVE-other"):
        assert forbidden not in response.text
    if surface == "capabilities":
        assert {row["document_kind"] for row in rows} == {"nfe", "nfce", "nfse"}
        assert all(row["status"] == "blocked" and "readiness" not in row for row in rows)
    else:
        assert "DOC-a" in response.text
        if surface == "issuances":
            attempt = next(row for row in rows if row.get("document_id") == "DOC-a")
            assert attempt["attempt_status"] == "reserved" and attempt["attempt_generation"] == 1
            assert (
                "request_fingerprint" not in response.text
                and "rejection_reason" not in response.text
            )


def test_selected_scope_reaches_repository_and_cannot_expand_authority(database):
    http = client(database, "owner")
    assert http.get("/v1/portal/surfaces/documents").status_code == 409
    response = http.get("/v1/portal/surfaces/documents?unit_id=unit-b")
    assert response.status_code == 200
    assert "DOC-b" in response.text and "DOC-a" not in response.text
    assert client(database).get("/v1/portal/surfaces/documents?unit_id=unit-b").status_code == 403
    production = http.get("/v1/portal/surfaces/documents?unit_id=unit-a&environment=production")
    assert "DOC-prod" in production.text and "DOC-a" not in production.text
    assert http.get("/v1/portal/surfaces/documents?unit_id=unknown").status_code == 409
    for query in ("limit=101", "limit=0", "limit=no", "offset=-1", "environment=fake"):
        assert http.get("/v1/portal/surfaces/documents?unit_id=unit-a&" + query).status_code == 400


def test_auth_rbac_csrf_and_runtime_blocking_remain_enforced(database):
    http = client(database)
    anonymous = TestClient(fixture.app(database), base_url="https://nfcore.test")
    assert anonymous.get("/v1/portal/surfaces/documents").status_code == 401
    assert client(database, "billing").get("/v1/portal/surfaces/documents").status_code == 403
    assert client(database, "auditor").get("/v1/portal/surfaces/documents").status_code == 200
    body = {"unit_id": "unit-a"}
    endpoint = "/v1/portal/operations/issueFiscalDocument"
    assert http.post(endpoint, json=body).status_code == 403
    csrf = http.cookies.get(CSRF_COOKIE)
    assert http.post(endpoint, json=body, headers={CSRF_HEADER: csrf}).status_code == 400
    result = http.post(
        endpoint, json=body, headers={CSRF_HEADER: csrf, "Idempotency-Key": "synthetic-intent"}
    )
    assert (
        result.status_code == 503 and result.json()["detail"]["code"] == "FISCAL_RUNTIME_NOT_READY"
    )
    assert (
        http.post(
            endpoint,
            json={**body, "tenant_id": "tenant-b"},
            headers={CSRF_HEADER: csrf, "Idempotency-Key": "synthetic-intent"},
        ).status_code
        == 400
    )


def test_scoped_reservation_replays_and_rejects_cross_scope_collision_atomically(database):
    service = FiscalApplicationService(database)
    partition = fixture.scope()
    args = dict(
        scope=partition,
        key=IdempotencyKey(fixture.digest("fresh-scope")),
        request_fingerprint=fixture.digest("new"),
        document_id="SCOPED-NEW",
        created_at=fixture.NOW,
    )
    first = service.reserve_issuance(**args)
    assert not first.reservation.replay
    assert service.reserve_issuance(**args).reservation.replay
    with pytest.raises(PersistenceConflictError, match="scope"):
        service.reserve_issuance(**{**args, "scope": fixture.scope(tenant="tenant-b")})
    with pytest.raises(PersistenceConflictError, match="scope"):
        service.reserve_issuance(
            **{
                **args,
                "key": IdempotencyKey(fixture.digest("conflict")),
                "scope": fixture.scope(unit="unit-b"),
            }
        )
    with pytest.raises(PersistenceConflictError, match="scope"):
        service.reserve_issuance(
            **{
                **args,
                "key": IdempotencyKey(fixture.digest("legacy")),
                "document_id": "LEGACY-UNSCOPED",
            }
        )
    with pytest.raises(PersistenceConflictError, match="document_id"):
        service.reserve_issuance(
            **{**args, "key": IdempotencyKey(fixture.digest("same-doc-new-key"))}
        )
    with database() as uow:
        assert not uow.idempotency.attempts(IdempotencyKey(fixture.digest("same-doc-new-key")))
        assert not uow.idempotency.attempts(IdempotencyKey(fixture.digest("conflict")))
        assert not uow.idempotency.attempts(IdempotencyKey(fixture.digest("legacy")))
        assert {row.document_id for row in uow.lifecycle.list_for_scope(partition)} == {
            "DOC-a",
            "SCOPED-NEW",
        }
        with pytest.raises(FiscalValidationError):
            uow.lifecycle.list_for_scope(partition, limit=101)


def test_bounded_pages_and_exact_partition_ports(database):
    partition = fixture.scope()
    with database() as uow:
        for index in range(105):
            uow.lifecycle.add(
                FiscalStateSnapshot.initial(f"PAGE-{index:03}", fixture.NOW), scope=partition
            )
        uow.commit()
    with database() as uow:
        first = uow.lifecycle.list_for_scope(partition)
        second = uow.lifecycle.list_for_scope(partition, offset=100)
        assert len(first) == 100 and len(second) == 6
        assert not {row.document_id for row in first} & {row.document_id for row in second}
        for scope in (
            fixture.scope(host="wrong"),
            fixture.scope(tenant="missing"),
            fixture.scope(unit="missing"),
        ):
            assert not uow.lifecycle.list_for_scope(scope)
            assert not uow.outbox.list_for_scope(scope)
            assert not uow.archive.list_for_scope(scope)
            assert not uow.reconciliations.list_for_scope(scope)


def test_migration_13_preserves_legacy_without_inventing_scope(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE fm_schema_migrations (version INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        for migration in _MIGRATIONS:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO fm_schema_migrations VALUES (?, ?, ?)",
                (migration.version, migration.name, fixture.NOW.isoformat()),
            )
        connection.execute(
            "INSERT INTO fm_fiscal_lifecycle VALUES (?, ?, ?, ?, ?)",
            ("LEGACY", "draft", 0, fixture.NOW.isoformat(), "[]"),
        )
    database = SqliteFiscalDatabase(path)
    assert database.initialize() == (13, 14, 17, 18, 19)
    assert database.initialize() == ()
    with database() as uow:
        assert uow.lifecycle.get("LEGACY").state.value == "draft"
        assert not uow.lifecycle.list_for_scope(fixture.scope())
        with pytest.raises(PersistenceConflictError):
            uow.lifecycle.assert_scope("LEGACY", fixture.scope())


def test_governed_capability_authority_is_reused_without_promoting_readiness(database):
    from datetime import timedelta

    from kordena_fiscal.compliance import (
        CapabilityReadinessService,
        FiscalActionCapability,
        FiscalCapabilityLevel,
        JurisdictionCapabilityMatrix,
        JurisdictionCapabilityRule,
        TechnicalValidationMode,
    )
    from kordena_fiscal.control_plane import (
        AdminPrincipal,
        ControlPlanePermission,
        DurableControlPlaneService,
    )
    from kordena_fiscal.domain import (
        BrazilianJurisdiction,
        CnaeCode,
        Cnpj,
        FiscalAddress,
        FiscalDocumentKind,
        FiscalProfile,
        StateRegistration,
        TaxRegimeCode,
    )
    from kordena_fiscal.runtime.composition import build_postgres_runtime_composition
    from kordena_fiscal.web import create_app
    from kordena_fiscal.web.portal_runtime import DurableHumanPortalExecutor

    readiness = CapabilityReadinessService(
        JurisdictionCapabilityMatrix(
            (
                JurisdictionCapabilityRule(
                    rule_id="synthetic-contract-only",
                    version=1,
                    state_code="SP",
                    municipality_ibge_code="3550308",
                    document_kind=FiscalDocumentKind.NFE,
                    environment=FiscalEnvironment.HOMOLOGATION,
                    capability_level=FiscalCapabilityLevel.CONTRACT_ONLY,
                    validation_mode=TechnicalValidationMode.STRICT_REJECTION,
                    effective_from=fixture.NOW - timedelta(days=1),
                    source_normative="synthetic test declaration; not official evidence",
                    capabilities=frozenset({FiscalActionCapability.QUERY}),
                ),
            )
        )
    )
    if isinstance(database, PostgresFiscalDatabase):
        fixture.identity(database.human_accounts())
        composition = build_postgres_runtime_composition(database, capability_readiness=readiness)
        assert composition.fiscal_operation_path.configured_operations == (
            "queryArchiveReference",
        )
        application = create_app(
            human_identity=composition.human_identity, portal_executor=composition.portal_executor
        )
    else:
        application = create_app(
            human_identity=fixture.identity(),
            portal_executor=DurableHumanPortalExecutor(database, capability_readiness=readiness),
        )
    http = TestClient(application, base_url="https://nfcore.test")
    assert (
        http.post(
            "/v1/auth/login", json={"email": "operator@example.com", "password": fixture.PASSWORD}
        ).status_code
        == 200
    )
    blocked = http.get("/v1/portal/surfaces/capabilities").json()["rows"]
    assert all(row["status"] == "blocked" for row in blocked)
    profile = FiscalProfile(
        profile_id="synthetic-portal-profile",
        scope=fixture.scope(),
        cnpj=Cnpj("11222333000181"),
        legal_name="Synthetic capability company",
        tax_regime=TaxRegimeCode.SIMPLES_NACIONAL,
        state_registration=StateRegistration(state_code="SP", number="110042490114"),
        primary_cnae=CnaeCode("6202300"),
        address=FiscalAddress(
            street="Synthetic street",
            number="100",
            district="Synthetic district",
            municipality_name="Sao Paulo",
            jurisdiction=BrazilianJurisdiction(state_code="SP", municipality_ibge_code="3550308"),
            postal_code="01001000",
        ),
        effective_from=fixture.NOW - timedelta(days=1),
    )
    actor = AdminPrincipal(
        actor_id="synthetic-profile-admin",
        tenant_ids=frozenset({"tenant-a"}),
        permissions=frozenset({ControlPlanePermission.PROFILE_WRITE}),
    )
    DurableControlPlaneService(database).add_fiscal_profile(actor=actor, profile=profile)
    result = http.get("/v1/portal/surfaces/capabilities")
    assert result.status_code == 200
    rows = result.json()["rows"]
    nfe = next(row for row in rows if row["document_kind"] == "nfe")
    assert nfe["status"] == "declared" and nfe["readiness"] == "CONTRACT_ONLY"
    assert nfe["actions"] == ["query"] and nfe["capability_version"]
    assert "HOMOLOGATION_READY" not in result.text and "PRODUCTION_APPROVED" not in result.text
    assert all(row["status"] == "blocked" for row in rows if row["document_kind"] != "nfe")


def test_error_filtering_occurs_before_pagination(database):
    from kordena_fiscal.lifecycle import FiscalDocumentState

    with database() as uow:
        for index in range(101):
            uow.lifecycle.add(
                FiscalStateSnapshot.initial(f"BEFORE-ERROR-{index}", fixture.NOW),
                scope=fixture.scope(),
            )
        uow.commit()
    response = client(database).get("/v1/portal/surfaces/errors?limit=1")
    assert response.status_code == 200
    assert [
        row["document_id"] for row in response.json()["rows"] if row["record_type"] == "lifecycle"
    ] == ["DOC-a"]
    with database() as uow:
        assert (
            len(
                uow.lifecycle.list_for_scope(
                    fixture.scope(), states=frozenset({FiscalDocumentState.ERROR})
                )
            )
            == 1
        )
        assert not uow.lifecycle.list_for_scope(fixture.scope(), states=frozenset())
        assert not uow.outbox.list_for_scope(fixture.scope(), statuses=frozenset())


def test_concurrent_scoped_issuance_reservation_has_one_fresh_intent(database):
    from concurrent.futures import ThreadPoolExecutor

    service = FiscalApplicationService(database)

    def reserve(_index):
        return service.reserve_issuance(
            scope=fixture.scope(),
            key=IdempotencyKey(fixture.digest("concurrent")),
            request_fingerprint=fixture.digest("concurrent-content"),
            document_id="CONCURRENT-DOC",
            created_at=fixture.NOW,
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = tuple(pool.map(reserve, range(6)))
    assert sum(not result.reservation.replay for result in results) == 1
    assert {result.lifecycle.document_id for result in results} == {"CONCURRENT-DOC"}
    with database() as uow:
        assert len(uow.idempotency.attempts(IdempotencyKey(fixture.digest("concurrent")))) == 1
        uow.lifecycle.assert_scope("CONCURRENT-DOC", fixture.scope())


def test_authenticated_archive_query_through_postgres_portal_is_scoped(database):
    """Exercise login -> canonical portal -> PostgreSQL archive without a provider."""
    if not isinstance(database, PostgresFiscalDatabase):
        pytest.skip("runtime production composition requires PostgreSQL")

    from kordena_fiscal.runtime.composition import build_postgres_runtime_composition
    from kordena_fiscal.web import create_app

    fixture.identity(database.human_accounts())
    composition = build_postgres_runtime_composition(database)
    http = TestClient(
        create_app(
            human_identity=composition.human_identity,
            portal_executor=composition.portal_executor,
        ),
        base_url="https://nfcore.test",
    )
    assert http.post(
        "/v1/auth/login",
        json={"email": "operator@example.com", "password": fixture.PASSWORD},
    ).status_code == 200
    csrf = http.cookies.get(CSRF_COOKIE)
    assert csrf

    own = http.post(
        "/v1/portal/operations/queryArchiveReference",
        headers={CSRF_HEADER: csrf},
        json={"unit_id": "unit-a", "document_reference": "ARCHIVE-a"},
    )
    assert own.status_code == 200, own.text
    assert own.json()["found"] is True
    assert len(own.json()["entries"]) == 1
    assert fixture.PROTECTED not in own.text
    assert "content" not in own.json()["entries"][0]

    cross_unit = http.post(
        "/v1/portal/operations/queryArchiveReference",
        headers={CSRF_HEADER: csrf},
        json={"unit_id": "unit-b", "document_reference": "ARCHIVE-b"},
    )
    assert cross_unit.status_code == 403
    anonymous = TestClient(
        create_app(
            human_identity=composition.human_identity,
            portal_executor=composition.portal_executor,
        ),
        base_url="https://nfcore.test",
    )
    assert anonymous.post(
        "/v1/portal/operations/queryArchiveReference",
        json={"unit_id": "unit-a", "document_reference": "ARCHIVE-a"},
    ).status_code in {401, 403}
