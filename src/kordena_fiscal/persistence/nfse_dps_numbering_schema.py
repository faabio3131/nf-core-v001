"""Additive DPS serial authority for NFS-e, separate from NF-e/NFC-e 55/65.

The national DPS identifier contains the issuer municipality, legal CNPJ,
series and serial. Its counters MUST NOT reuse fm_fiscal_sequences keyed only
by tenant/unit/model. No migration is applied by import or service startup.
"""
NFSE_DPS_NUMBERING_VERSION = 22
NFSE_DPS_NUMBERING_NAME = "nat_mg_dps_legal_issuer_sequence"
NFSE_DPS_NUMBERING_SCHEMA = (
    """
    CREATE TABLE fm_nfse_dps_counters (
        host_namespace TEXT NOT NULL,
        issuer_cnpj TEXT NOT NULL,
        issuer_municipality_ibge TEXT NOT NULL,
        environment TEXT NOT NULL,
        series INTEGER NOT NULL,
        owner_tenant_id TEXT NOT NULL,
        owner_unit_id TEXT NOT NULL,
        last_number BIGINT NOT NULL,
        PRIMARY KEY (
            host_namespace, issuer_cnpj, issuer_municipality_ibge, environment, series
        ),
        CHECK (series BETWEEN 1 AND 99999),
        CHECK (last_number BETWEEN 1 AND 999999999999999)
    )
    """,
    """
    CREATE TABLE fm_nfse_dps_reservations (
        host_namespace TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        unit_id TEXT NOT NULL,
        environment TEXT NOT NULL,
        document_id TEXT NOT NULL,
        request_fingerprint TEXT NOT NULL,
        issuer_cnpj TEXT NOT NULL,
        issuer_municipality_ibge TEXT NOT NULL,
        series INTEGER NOT NULL,
        number BIGINT NOT NULL,
        PRIMARY KEY (host_namespace, tenant_id, unit_id, environment, document_id),
        UNIQUE (
            host_namespace, issuer_cnpj, issuer_municipality_ibge,
            environment, series, number
        ),
        CHECK (series BETWEEN 1 AND 99999),
        CHECK (number BETWEEN 1 AND 999999999999999)
    )
    """,
)
