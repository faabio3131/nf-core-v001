"""Atomic, idempotent token reservations backed by canonical commercial subscriptions.

SQL is deliberately portable across the existing SQLite/PostgreSQL persistence
boundaries. PostgreSQL serializes the counter UPDATE; SQLite uses its existing
transaction discipline. No prompts, responses, API keys or fiscal authority.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .commercial_quotas import TokenAllowance, allowance_for_subscription


class QuotaDenied(ValueError):
    """Fail-closed: subscription, period, capacity or idempotency is invalid."""


class _Cursor(Protocol):
    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> Sequence[object] | None: ...


class _Connection(Protocol):
    def execute(self, sql: str, parameters: Sequence[object] = ()) -> _Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TokenReservation:
    tenant_id: str
    request_id: str
    reserved_input: int
    reserved_output: int
    created: bool
    state: str


@dataclass(frozen=True, slots=True)
class TokenBalance:
    used_input: int
    used_output: int
    allowance: TokenAllowance
    period_end: datetime


class DurableTokenQuotaStore:
    """Reservations are unique by tenant and request; repeat calls cannot invoke AI twice.

    `reserve` must be called before the model. The executor may call the model
    ONLY when `created` is True. A failed/unknown model call retains the full
    reservation: partial charges or timeouts never silently refund capacity.
    `settle` releases unused capacity only for confirmed provider accounting.
    """

    def __init__(
        self,
        acquire: Callable[[], AbstractContextManager[_Connection]],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._acquire = acquire
        self._clock = clock

    @staticmethod
    def _identity(tenant_id: str, request_id: str) -> tuple[str, str]:
        tenant, request = tenant_id.strip().lower(), request_id.strip()
        if not tenant or not request or len(tenant) > 256 or len(request) > 128:
            raise QuotaDenied("invalid tenant or idempotency identity")
        return tenant, request

    def _subscription(
        self, connection: _Connection, tenant: str, now: datetime
    ) -> tuple[str, str, TokenAllowance, datetime]:
        row = connection.execute(
            """SELECT plan_id, status, period_start, period_end
               FROM fm_commercial_subscriptions WHERE tenant_id = ?
               ORDER BY last_event_at DESC, subscription_id DESC LIMIT 1""",
            (tenant,),
        ).fetchone()
        if row is None:
            raise QuotaDenied("canonical subscription is unavailable")
        plan_id, status = str(row[0]), str(row[1])
        allowance = allowance_for_subscription(plan_id=plan_id, status=status)
        if allowance is None:
            raise QuotaDenied("subscription cannot consume cognitive AI")
        try:
            start = datetime.fromisoformat(str(row[2]))
            end = datetime.fromisoformat(str(row[3]))
        except ValueError as exc:
            raise QuotaDenied("invalid billing period") from exc
        if start.tzinfo is None or end.tzinfo is None:
            raise QuotaDenied("billing period must be timezone-aware")
        if status.lower() == "trial":
            end = min(end, start + timedelta(days=30))
        if not start <= now < end:
            raise QuotaDenied("billing period expired or not yet active")
        return start.isoformat(), end.isoformat(), allowance, end

    def reserve(
        self, *,
        tenant_id: str,
        request_id: str,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> TokenReservation:
        tenant, request = self._identity(tenant_id, request_id)
        if any(
            not isinstance(n, int) or isinstance(n, bool) or n < 1
            for n in (max_input_tokens, max_output_tokens)
        ):
            raise QuotaDenied("positive finite token reservation is required")
        now = self._clock()
        if now.tzinfo is None:
            raise QuotaDenied("clock must be timezone-aware")
        with self._acquire() as connection:
            start, end, limit, _ = self._subscription(connection, tenant, now)
            existing = connection.execute(
                """SELECT period_start, period_end, reserved_input,
                          reserved_output, state
                   FROM fm_cognitive_token_reservations
                   WHERE tenant_id = ? AND request_id = ?""",
                (tenant, request),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing[0]) != start or str(existing[1]) != end
                    or int(existing[2]) != max_input_tokens
                    or int(existing[3]) != max_output_tokens
                ):
                    raise QuotaDenied("idempotency key reused with different reservation")
                return TokenReservation(
                    tenant, request, max_input_tokens, max_output_tokens,
                    False, str(existing[4]),
                )
            connection.execute(
                """INSERT INTO fm_cognitive_token_counters
                   (tenant_id, period_start, period_end, input_tokens, output_tokens)
                   VALUES (?, ?, ?, 0, 0) ON CONFLICT DO NOTHING""",
                (tenant, start, end),
            )
            updated = connection.execute(
                """UPDATE fm_cognitive_token_counters
                   SET input_tokens = input_tokens + ?,
                       output_tokens = output_tokens + ?
                   WHERE tenant_id = ? AND period_start = ? AND period_end = ?
                     AND input_tokens <= ? - ?
                     AND output_tokens <= ? - ?""",
                (
                    max_input_tokens, max_output_tokens, tenant, start, end,
                    limit.input_tokens, max_input_tokens,
                    limit.output_tokens, max_output_tokens,
                ),
            )
            if updated.rowcount != 1:
                raise QuotaDenied("cognitive token allowance exhausted")
            connection.execute(
                """INSERT INTO fm_cognitive_token_reservations
                   (tenant_id, request_id, period_start, period_end,
                    reserved_input, reserved_output, state, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?)""",
                (
                    tenant, request, start, end,
                    max_input_tokens, max_output_tokens, now.isoformat(),
                ),
            )
            connection.commit()
        return TokenReservation(
            tenant, request, max_input_tokens, max_output_tokens, True, "reserved"
        )

    def settle(
        self, *,
        tenant_id: str,
        request_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> bool:
        tenant, request = self._identity(tenant_id, request_id)
        if any(
            not isinstance(n, int) or isinstance(n, bool) or n < 0
            for n in (input_tokens, output_tokens)
        ):
            raise QuotaDenied("invalid provider token accounting")
        with self._acquire() as connection:
            row = connection.execute(
                """SELECT period_start, period_end, reserved_input,
                          reserved_output, settled_input, settled_output, state
                   FROM fm_cognitive_token_reservations
                   WHERE tenant_id = ? AND request_id = ?""",
                (tenant, request),
            ).fetchone()
            if row is None:
                raise QuotaDenied("missing cognitive token reservation")
            reserved_in, reserved_out = int(row[2]), int(row[3])
            if input_tokens > reserved_in or output_tokens > reserved_out:
                raise QuotaDenied("provider usage exceeded reserved budget")
            if str(row[6]) == "settled":
                if (int(row[4]), int(row[5])) != (input_tokens, output_tokens):
                    raise QuotaDenied("conflicting settlement replay")
                return False
            # UPDATE serializes settlement: duplicate concurrent attempts cannot
            # release the reserved capacity twice.
            updated = connection.execute(
                """UPDATE fm_cognitive_token_reservations
                   SET settled_input = ?, settled_output = ?, state = 'settled'
                   WHERE tenant_id = ? AND request_id = ? AND state = 'reserved'""",
                (input_tokens, output_tokens, tenant, request),
            )
            if updated.rowcount != 1:
                raise QuotaDenied("concurrent settlement rejected")
            counter = connection.execute(
                """UPDATE fm_cognitive_token_counters
                   SET input_tokens = input_tokens - ?,
                       output_tokens = output_tokens - ?
                   WHERE tenant_id = ? AND period_start = ? AND period_end = ?
                     AND input_tokens >= ? AND output_tokens >= ?""",
                (
                    reserved_in - input_tokens,
                    reserved_out - output_tokens, tenant, str(row[0]), str(row[1]),
                    reserved_in - input_tokens, reserved_out - output_tokens,
                ),
            )
            if counter.rowcount != 1:
                raise QuotaDenied("cognitive token ledger is inconsistent")
            connection.commit()
            return True

    def balance(self, *, tenant_id: str) -> TokenBalance:
        tenant, _ = self._identity(tenant_id, "balance")
        now = self._clock()
        with self._acquire() as connection:
            start, end, allowance, expires_at = self._subscription(connection, tenant, now)
            row = connection.execute(
                """SELECT input_tokens, output_tokens
                   FROM fm_cognitive_token_counters
                   WHERE tenant_id = ? AND period_start = ? AND period_end = ?""",
                (tenant, start, end),
            ).fetchone()
            used_input, used_output = (0, 0) if row is None else (int(row[0]), int(row[1]))
            return TokenBalance(used_input, used_output, allowance, expires_at)
