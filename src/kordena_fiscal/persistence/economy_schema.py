"""T01 additive Central de Economia Fiscal foundation.

Registered as additive v25 after the MFA v24 reservation.
No DDL is executed on application startup in staging or production.
"""

from __future__ import annotations

import re

ECONOMY_VERSION = 25
ECONOMY_NAME = "economy_t01_scoped_foundation"
SCOPE_COLUMNS = "host_namespace, tenant_id, unit_id, environment"
SCOPE_DDL = """
    host_namespace TEXT NOT NULL CHECK (length(host_namespace) > 0),
    tenant_id TEXT NOT NULL CHECK (length(tenant_id) > 0),
    unit_id TEXT NOT NULL CHECK (length(unit_id) > 0),
    environment TEXT NOT NULL CHECK (environment IN ('homologation', 'production')),
"""
TABLES = (
    "fm_economy_snapshots",
    "fm_economy_benefits",
    "fm_economy_opportunities",
    "fm_economy_credit_entries",
    "fm_economy_dossiers",
)
ECONOMY_INDEXES = (
    "fm_economy_snapshots_period_idx",
    "fm_economy_benefits_jurisdiction_idx",
    "fm_economy_credit_period_idx",
    "fm_economy_opportunities_snapshot_idx",
    "fm_economy_dossiers_opportunity_idx",
)
SCOPE_PREDICATE = " AND ".join(
    f"{column} = current_setting('nfcore.economy_{column}', true)"
    for column in SCOPE_COLUMNS.split(", ")
)
ECONOMY_TABLES = (
    f"""CREATE TABLE fm_economy_snapshots (
        {SCOPE_DDL}
        record_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        competence DATE NOT NULL CHECK (extract(day from competence) = 1),
        issuer_cnpj TEXT NOT NULL CHECK (issuer_cnpj ~ '^[0-9]{{14}}$'),
        content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
        digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{{64}}$'),
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY ({SCOPE_COLUMNS}, record_id, version)
    )""",
    f"""CREATE TABLE fm_economy_benefits (
        {SCOPE_DDL}
        record_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        tax_code TEXT NOT NULL,
        jurisdiction TEXT NOT NULL,
        normative_reference TEXT NOT NULL CHECK (length(trim(normative_reference)) > 0),
        valid_from DATE NOT NULL,
        valid_until DATE,
        CHECK (valid_until IS NULL OR valid_until > valid_from),
        content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
        digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{{64}}$'),
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY ({SCOPE_COLUMNS}, record_id, version)
    )""",
    f"""CREATE TABLE fm_economy_opportunities (
        {SCOPE_DDL}
        record_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        snapshot_id TEXT NOT NULL,
        snapshot_version INTEGER NOT NULL,
        benefit_id TEXT,
        benefit_version INTEGER,
        CHECK ((benefit_id IS NULL) = (benefit_version IS NULL)),
        estimated_cents BIGINT NOT NULL CHECK (estimated_cents >= 0),
        content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
        digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{{64}}$'),
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY ({SCOPE_COLUMNS}, record_id, version),
        FOREIGN KEY ({SCOPE_COLUMNS}, snapshot_id, snapshot_version)
            REFERENCES fm_economy_snapshots ({SCOPE_COLUMNS}, record_id, version),
        FOREIGN KEY ({SCOPE_COLUMNS}, benefit_id, benefit_version)
            REFERENCES fm_economy_benefits ({SCOPE_COLUMNS}, record_id, version)
    )""",
    f"""CREATE TABLE fm_economy_credit_entries (
        {SCOPE_DDL}
        record_id TEXT NOT NULL,
        opportunity_id TEXT NOT NULL,
        opportunity_version INTEGER NOT NULL,
        tax_code TEXT NOT NULL,
        competence DATE NOT NULL CHECK (extract(day from competence) = 1),
        movement TEXT NOT NULL CHECK (movement IN (
            'identified', 'reserved', 'released', 'compensated', 'reversed'
        )),
        amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
        evidence_reference TEXT NOT NULL CHECK (length(trim(evidence_reference)) > 0),
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY ({SCOPE_COLUMNS}, record_id),
        FOREIGN KEY ({SCOPE_COLUMNS}, opportunity_id, opportunity_version)
            REFERENCES fm_economy_opportunities ({SCOPE_COLUMNS}, record_id, version)
    )""",
    f"""CREATE TABLE fm_economy_dossiers (
        {SCOPE_DDL}
        record_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        opportunity_id TEXT NOT NULL,
        opportunity_version INTEGER NOT NULL,
        archive_reference TEXT NOT NULL CHECK (length(trim(archive_reference)) > 0),
        digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{{64}}$'),
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY ({SCOPE_COLUMNS}, record_id, version),
        FOREIGN KEY ({SCOPE_COLUMNS}, opportunity_id, opportunity_version)
            REFERENCES fm_economy_opportunities ({SCOPE_COLUMNS}, record_id, version)
    )""",
    f"""CREATE INDEX fm_economy_snapshots_period_idx ON fm_economy_snapshots
        ({SCOPE_COLUMNS}, competence, issuer_cnpj)""",
    f"""CREATE INDEX fm_economy_benefits_jurisdiction_idx ON fm_economy_benefits
        ({SCOPE_COLUMNS}, jurisdiction, tax_code, valid_from)""",
    f"""CREATE INDEX fm_economy_credit_period_idx ON fm_economy_credit_entries
        ({SCOPE_COLUMNS}, competence, tax_code, created_at)""",
    f"""CREATE INDEX fm_economy_opportunities_snapshot_idx ON fm_economy_opportunities
        ({SCOPE_COLUMNS}, snapshot_id, snapshot_version)""",
    f"""CREATE INDEX fm_economy_dossiers_opportunity_idx ON fm_economy_dossiers
        ({SCOPE_COLUMNS}, opportunity_id, opportunity_version)""",
)

# No UPDATE/DELETE policies: records are immutable for runtime principals.
# FORCE also subjects the owner to RLS, except PostgreSQL privileged bypass roles.
ECONOMY_RLS = tuple(
    statement
    for table in TABLES
    for statement in (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY economy_select ON {table} FOR SELECT USING ({SCOPE_PREDICATE})",
        f"CREATE POLICY economy_insert ON {table} FOR INSERT WITH CHECK ({SCOPE_PREDICATE})",
    )
)
ECONOMY_SCHEMA = ECONOMY_TABLES + ECONOMY_RLS


def is_scope_predicate(expression: object) -> bool:
    """Recognize only the exact predicate emitted by this pinned migration."""
    if not isinstance(expression, str):
        return False

    def normalized(value: str) -> str:
        # Preserve the setting names inside SQL string literals, including
        # whitespace. Ignore only PostgreSQL's grouping and implicit text casts.
        parts = re.split(r"('(?:''|[^'])*')", value)
        return "".join(
            part if index % 2 else re.sub(r"\s+|[()]|::text\b", "", part)
            for index, part in enumerate(parts)
        )

    return normalized(expression) == normalized(SCOPE_PREDICATE)
