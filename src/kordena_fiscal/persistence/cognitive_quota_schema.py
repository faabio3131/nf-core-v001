"""Additive COG-02 counters and idempotent reservations (migration 19).

Only consumption evidence lives here; the plan, subscription state and period
continue to come from the canonical commercial subscription authority.
No prompts, responses, secrets, or customer PII are stored.
Migration is never applied implicitly in staging/production.
"""

COGNITIVE_QUOTA_VERSION = 19
COGNITIVE_QUOTA_NAME = "cognitive_token_reservations"
COGNITIVE_QUOTA_SCHEMA = (
    """CREATE TABLE fm_cognitive_token_counters (
        tenant_id TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        input_tokens BIGINT NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
        output_tokens BIGINT NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
        PRIMARY KEY (tenant_id, period_start, period_end)
    )""",
    """CREATE TABLE fm_cognitive_token_reservations (
        tenant_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        reserved_input BIGINT NOT NULL CHECK (reserved_input >= 0),
        reserved_output BIGINT NOT NULL CHECK (reserved_output >= 0),
        settled_input BIGINT,
        settled_output BIGINT,
        state TEXT NOT NULL CHECK (state IN ('reserved', 'settled')),
        created_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, request_id),
        CHECK (settled_input IS NULL OR
               (settled_input >= 0 AND settled_input <= reserved_input)),
        CHECK (settled_output IS NULL OR
               (settled_output >= 0 AND settled_output <= reserved_output)),
        FOREIGN KEY (tenant_id, period_start, period_end)
            REFERENCES fm_cognitive_token_counters (tenant_id, period_start, period_end)
    )""",
)
