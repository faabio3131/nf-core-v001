from __future__ import annotations

import os
from datetime import UTC, datetime

import psycopg
import pytest

from kordena_fiscal.control_plane.commercial_release import (
    CommercialReleaseAdministrationService,
)
from kordena_fiscal.control_plane.models import AdminPrincipal, ControlPlanePermission
from kordena_fiscal.persistence.postgres import PostgresFiscalDatabase
from kordena_fiscal.product.commercial_release import (
    CommercialReleaseDecision,
    CommercialReleaseError,
    CommercialReleaseStatus,
)

DSN_ENV = "NFCORE_TEST_POSTGRES_DSN"
NOW = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get(DSN_ENV, "").strip()
    if not value:
        pytest.skip(f"{DSN_ENV} is required for PostgreSQL release certification")
    return value


@pytest.fixture
def database() -> PostgresFiscalDatabase:
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    database = PostgresFiscalDatabase(dsn)
    assert database.initialize() == tuple(range(1, 20))
    try:
        yield database
    finally:
        database.close()


def _actor() -> AdminPrincipal:
    return AdminPrincipal(
        actor_id="fm-release-platform-admin",
        permissions=frozenset({ControlPlanePermission.COMMERCIAL_CONFIG_WRITE}),
        global_scope=True,
    )


def test_commercial_approval_requires_explicit_human_decision_reference() -> None:
    with pytest.raises(CommercialReleaseError, match="human_decision_reference"):
        CommercialReleaseDecision(
            version=1,
            status=CommercialReleaseStatus.COMMERCIAL_APPROVED,
        )


def test_release_catalog_is_durable_versioned_audited_and_revocable(
    database: PostgresFiscalDatabase,
) -> None:
    service = CommercialReleaseAdministrationService(
        database.commercial_release_catalog()
    )
    assert service.current is None

    first = service.publish(
        actor=_actor(),
        decision=CommercialReleaseDecision(
            version=1,
            status=CommercialReleaseStatus.WAITLIST,
            public_message="Cadastro de interesse disponível.",
        ),
        expected_version=None,
        correlation_id="release-v1",
        published_at=NOW,
    )
    assert first.status is CommercialReleaseStatus.WAITLIST

    reloaded = CommercialReleaseAdministrationService(
        database.commercial_release_catalog()
    )
    assert reloaded.current == first
    assert reloaded.history()[0].actor_id == "fm-release-platform-admin"
    assert reloaded.history()[0].correlation_id == "release-v1"

    approved = reloaded.publish(
        actor=_actor(),
        decision=CommercialReleaseDecision(
            version=2,
            status=CommercialReleaseStatus.COMMERCIAL_APPROVED,
            public_message="Oferta aprovada.",
            human_decision_reference="human-go-no-go-2026-09-27",
        ),
        expected_version=1,
        correlation_id="release-v2",
        published_at=NOW,
    )
    assert approved.commercially_approved is True

    revoked = reloaded.publish(
        actor=_actor(),
        decision=CommercialReleaseDecision(
            version=3,
            status=CommercialReleaseStatus.UNAVAILABLE,
            public_message="Oferta temporariamente indisponível.",
        ),
        expected_version=2,
        correlation_id="release-v3",
        published_at=NOW,
    )
    assert revoked.commercially_approved is False
    assert [item.decision.version for item in reloaded.history()] == [3, 2, 1]

    with pytest.raises(CommercialReleaseError, match="version conflict"):
        reloaded.publish(
            actor=_actor(),
            decision=CommercialReleaseDecision(
                version=4,
                status=CommercialReleaseStatus.INTERNAL_ONLY,
            ),
            expected_version=2,
            correlation_id="stale-writer",
            published_at=NOW,
        )
