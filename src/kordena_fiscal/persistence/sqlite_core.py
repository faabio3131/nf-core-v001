"""SQLite adapters for numbering, lifecycle and host/fiscal bindings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import cast

from kordena_fiscal.domain import (
    ElectronicInvoiceModel,
    ExecutionScope,
    FiscalAccountBinding,
    FiscalAccountId,
    FiscalUnitId,
    FiscalValidationError,
    HostNamespace,
    HostScope,
)
from kordena_fiscal.lifecycle import (
    FiscalDocumentState,
    FiscalStateSnapshot,
    FiscalStateTransition,
)
from kordena_fiscal.numbering import (
    FiscalNumberReservation,
    FiscalSequenceKey,
    FiscalSequencePolicy,
    SequenceExhaustedError,
    SequenceStateError,
)

from ._sqlite_common import dt, host_key, integer, iso, one_row, scoped_page, text
from .ports import PersistenceConflictError, PersistenceStateError


def _sequence_token(key: FiscalSequenceKey, number: int) -> str:
    return hashlib.sha256(f"{key.canonical_material}|{number}".encode()).hexdigest()


class SqliteFiscalSequenceStore:
    _LEGAL_NAMESPACE = "nfcore-legal-sequence"
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _identity(key: FiscalSequenceKey) -> tuple[object, ...]:
        return (
            host_key(key.host_namespace),
            key.tenant_id,
            key.unit_id,
            key.environment.value,
            key.model.value,
            key.series,
        )

    def _issuer(self, key: FiscalSequenceKey) -> str | None:
        if key.host_namespace == self._LEGAL_NAMESPACE:
            raise SequenceStateError("reserved numbering namespace is internal")
        if not isinstance(key.model, ElectronicInvoiceModel):
            return None
        profiles = self._connection.execute(
            """SELECT DISTINCT cnpj FROM fm_control_plane_fiscal_profiles
               WHERE host_namespace=? AND tenant_id=? AND unit_id=? AND environment=?""",
            self._identity(key)[:4],
        ).fetchall()
        issuers = {text(row[0], "cnpj") for row in profiles}
        if len(issuers) > 1 or (issuers and key.issuer_cnpj and key.issuer_cnpj not in issuers):
            raise SequenceStateError("historical issuer scope requires explicit reconciliation")
        # Explicit CNPJ comes only from the canonical signed-document pipeline.
        # Old unbound counters may be read for reconciliation, never incremented.
        return key.issuer_cnpj or next(iter(issuers), None)

    def authority_lock_material(self, key: FiscalSequenceKey) -> str:
        issuer = self._issuer(key)
        return (f"legal-invoice:{issuer}:{key.environment.value}:{key.model.value}:{key.series}"
                if issuer else key.canonical_material)

    def _authority(
        self, key: FiscalSequenceKey, policy: FiscalSequencePolicy | None = None,
    ) -> tuple[tuple[object, ...], int | None]:
        issuer = self._issuer(key)
        if issuer is None:
            if policy is not None and isinstance(key.model, ElectronicInvoiceModel):
                raise SequenceStateError("invoice numbering requires canonical issuer identity")
            return self._identity(key), None
        identity = (self._LEGAL_NAMESPACE, key.tenant_id, issuer,
                    key.environment.value, key.model.value, key.series)
        owners = self._connection.execute(
            """SELECT tenant_id FROM fm_fiscal_sequences
               WHERE host_namespace=? AND unit_id=? AND environment=? AND model=? AND series=?""",
            (self._LEGAL_NAMESPACE, issuer, key.environment.value, key.model.value, key.series),
        ).fetchall()
        if any(row[0] != key.tenant_id for row in owners):
            raise SequenceStateError("legal numbering stream belongs to another tenant")
        orphan = self._connection.execute(
            """SELECT 1 FROM fm_fiscal_sequences s
               WHERE s.tenant_id=? AND s.environment=? AND s.model=? AND s.series=?
                 AND s.host_namespace<>?
                 AND NOT (s.host_namespace=? AND s.unit_id=?)
                 AND NOT EXISTS (SELECT 1 FROM fm_control_plane_fiscal_profiles p
                     WHERE p.host_namespace=s.host_namespace AND p.tenant_id=s.tenant_id
                       AND p.unit_id=s.unit_id AND p.environment=s.environment)
               LIMIT 1""",
            (key.tenant_id, key.environment.value, key.model.value, key.series,
             self._LEGAL_NAMESPACE, host_key(key.host_namespace), key.unit_id),
        ).fetchone()
        if orphan is not None:
            raise SequenceStateError("unattributed legacy numbering requires reconciliation")
        rows = self._connection.execute(
            """SELECT DISTINCT s.host_namespace,s.tenant_id,s.unit_id,
                              s.first_number,s.max_number,s.last_reserved
               FROM fm_fiscal_sequences s
               LEFT JOIN fm_control_plane_fiscal_profiles p
                 ON p.host_namespace=s.host_namespace AND p.tenant_id=s.tenant_id
                AND p.unit_id=s.unit_id AND p.environment=s.environment
               WHERE s.environment=? AND s.model=? AND s.series=?
                 AND s.host_namespace<>?
                 AND (p.cnpj=? OR (s.host_namespace=? AND s.tenant_id=? AND s.unit_id=?))""",
            (key.environment.value, key.model.value, key.series, self._LEGAL_NAMESPACE,
             issuer, host_key(key.host_namespace), key.tenant_id, key.unit_id),
        ).fetchall()
        high_water = None
        for row in rows:
            if row[1] != key.tenant_id:
                raise SequenceStateError("legacy numbering ownership requires reconciliation")
            # An old unit that changed CNPJ cannot silently donate its history.
            cnpjs = self._connection.execute(
                """SELECT DISTINCT cnpj FROM fm_control_plane_fiscal_profiles
                   WHERE host_namespace=? AND tenant_id=? AND unit_id=? AND environment=?""",
                (*row[:3], key.environment.value),
            ).fetchall()
            if any(p[0] != issuer for p in cnpjs):
                raise SequenceStateError("ambiguous legacy numbering issuer")
            if policy is not None and (
                row[3] != policy.first_number or row[4] != policy.max_number
            ):
                raise SequenceStateError("legacy numbering policies require reconciliation")
            value = integer(row[5], "last_reserved")
            high_water = value if high_water is None else max(high_water, value)
        return identity, high_water

    def reserve_next(
        self,
        key: FiscalSequenceKey,
        policy: FiscalSequencePolicy,
    ) -> FiscalNumberReservation:
        if not isinstance(key, FiscalSequenceKey):
            raise FiscalValidationError("key must be FiscalSequenceKey")
        if not isinstance(policy, FiscalSequencePolicy):
            raise FiscalValidationError("policy must be FiscalSequencePolicy")
        identity, high_water = self._authority(key, policy)
        row = one_row(
            self._connection.execute(
                """
                SELECT first_number, max_number, last_reserved
                FROM fm_fiscal_sequences
                WHERE host_namespace = ? AND tenant_id = ? AND unit_id = ?
                  AND environment = ? AND model = ? AND series = ?
                """,
                identity,
            )
        )
        if row is None:
            candidate = max(policy.first_number, (high_water or 0) + 1)
            if policy.max_number is not None and candidate > policy.max_number:
                raise SequenceExhaustedError("fiscal sequence has reached its configured maximum")
            self._connection.execute(
                """
                INSERT INTO fm_fiscal_sequences (
                    host_namespace, tenant_id, unit_id, environment, model, series,
                    first_number, max_number, last_reserved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*identity, policy.first_number, policy.max_number, candidate),
            )
        else:
            stored_first = integer(row[0], "first_number")
            stored_max = None if row[1] is None else integer(row[1], "max_number")
            if stored_first != policy.first_number or stored_max != policy.max_number:
                raise SequenceStateError("sequence policy cannot change after first reservation")
            candidate = max(integer(row[2], "last_reserved"), high_water or 0) + 1
            if policy.max_number is not None and candidate > policy.max_number:
                raise SequenceExhaustedError("fiscal sequence has reached its configured maximum")
            self._connection.execute(
                """
                UPDATE fm_fiscal_sequences SET last_reserved = ?
                WHERE host_namespace = ? AND tenant_id = ? AND unit_id = ?
                  AND environment = ? AND model = ? AND series = ?
                """,
                (candidate, *identity),
            )
        return FiscalNumberReservation(
            key=key,
            number=candidate,
            reservation_token=_sequence_token(key, candidate),
        )

    def last_reserved(self, key: FiscalSequenceKey) -> int | None:
        if not isinstance(key, FiscalSequenceKey):
            raise FiscalValidationError("key must be FiscalSequenceKey")
        identity, high_water = self._authority(key)
        row = one_row(
            self._connection.execute(
                """
                SELECT last_reserved FROM fm_fiscal_sequences
                WHERE host_namespace = ? AND tenant_id = ? AND unit_id = ?
                  AND environment = ? AND model = ? AND series = ?
                """,
                identity,
            )
        )
        if row is None:
            return high_water
        return max(integer(row[0], "last_reserved"), high_water or 0)


class SqliteLifecycleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _history_json(snapshot: FiscalStateSnapshot) -> str:
        payload = [
            {
                "sequence": item.sequence,
                "from_state": item.from_state.value,
                "to_state": item.to_state.value,
                "occurred_at": item.occurred_at.isoformat(),
                "reason": item.reason,
                "correlation_id": item.correlation_id,
            }
            for item in snapshot.history
        ]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _snapshot(row: tuple[object, ...]) -> FiscalStateSnapshot:
        raw_history: object = json.loads(text(row[4], "history_json"))
        if not isinstance(raw_history, list):
            raise PersistenceStateError("persisted lifecycle history must be a list")
        history: list[FiscalStateTransition] = []
        for item in raw_history:
            if not isinstance(item, dict):
                raise PersistenceStateError("persisted lifecycle transition must be an object")
            history.append(
                FiscalStateTransition(
                    sequence=integer(item.get("sequence"), "transition.sequence"),
                    from_state=FiscalDocumentState(
                        text(item.get("from_state"), "transition.from_state")
                    ),
                    to_state=FiscalDocumentState(text(item.get("to_state"), "transition.to_state")),
                    occurred_at=dt(text(item.get("occurred_at"), "transition.occurred_at")),
                    reason=text(item.get("reason"), "transition.reason"),
                    correlation_id=text(item.get("correlation_id"), "transition.correlation_id"),
                )
            )
        return FiscalStateSnapshot(
            document_id=text(row[0], "document_id"),
            state=FiscalDocumentState(text(row[1], "state")),
            version=integer(row[2], "version"),
            updated_at=dt(text(row[3], "updated_at")),
            history=tuple(history),
        )

    def add(
        self, snapshot: FiscalStateSnapshot, *, scope: ExecutionScope | None = None
    ) -> FiscalStateSnapshot:
        if not isinstance(snapshot, FiscalStateSnapshot):
            raise FiscalValidationError("snapshot must be FiscalStateSnapshot")
        existing = self.get(snapshot.document_id)
        if existing is not None:
            if scope is not None:
                self.assert_scope(snapshot.document_id, scope)
            if existing == snapshot:
                return existing
            raise PersistenceConflictError("lifecycle document_id already exists")
        try:
            self._connection.execute(
                """
                INSERT INTO fm_fiscal_lifecycle (
                    document_id, state, version, updated_at, history_json,
                    host_namespace, tenant_id, unit_id, environment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.document_id,
                    snapshot.state.value,
                    snapshot.version,
                    iso(snapshot.updated_at),
                    self._history_json(snapshot),
                    *(scoped_page(scope, 1, 0)[:4] if scope is not None else (None,) * 4),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PersistenceConflictError("lifecycle document_id already exists") from exc
        return snapshot

    def assert_scope(self, document_id: str, scope: ExecutionScope) -> None:
        partition = scoped_page(scope, 1, 0)[:4]
        row = one_row(
            self._connection.execute(
                """SELECT host_namespace, tenant_id, unit_id, environment
               FROM fm_fiscal_lifecycle WHERE document_id = ?""",
                (document_id,),
            )
        )
        if row is None or row != partition:
            raise PersistenceConflictError("lifecycle scope is missing or conflicts")

    def list_for_scope(
        self,
        scope: ExecutionScope,
        *,
        limit: int = 100,
        offset: int = 0,
        states: frozenset[FiscalDocumentState] | None = None,
    ) -> tuple[FiscalStateSnapshot, ...]:
        page = scoped_page(scope, limit, offset)
        if states is not None and not states:
            return ()
        filtering = (
            "" if states is None else " AND state IN (" + ",".join("?" for _ in states) + ")"
        )
        values = () if states is None else tuple(sorted(item.value for item in states))
        rows = self._connection.execute(
            f"""SELECT document_id, state, version, updated_at, history_json
               FROM fm_fiscal_lifecycle
               WHERE host_namespace = ? AND tenant_id = ? AND unit_id = ?
                 AND environment = ? {filtering}
               ORDER BY updated_at DESC, document_id LIMIT ? OFFSET ?""",
            (*page[:4], *values, *page[4:]),
        ).fetchall()
        return tuple(self._snapshot(cast(tuple[object, ...], row)) for row in rows)

    def get(self, document_id: str) -> FiscalStateSnapshot | None:
        normalized = document_id.strip()
        if not normalized:
            raise FiscalValidationError("document_id must not be blank")
        row = one_row(
            self._connection.execute(
                """
                SELECT document_id, state, version, updated_at, history_json
                FROM fm_fiscal_lifecycle WHERE document_id = ?
                """,
                (normalized,),
            )
        )
        return None if row is None else self._snapshot(row)

    def save(
        self,
        snapshot: FiscalStateSnapshot,
        *,
        expected_version: int,
    ) -> FiscalStateSnapshot:
        if not isinstance(snapshot, FiscalStateSnapshot):
            raise FiscalValidationError("snapshot must be FiscalStateSnapshot")
        if snapshot.version != expected_version + 1:
            raise PersistenceConflictError(
                "lifecycle save requires exactly one transition after expected_version"
            )
        cursor = self._connection.execute(
            """
            UPDATE fm_fiscal_lifecycle
            SET state = ?, version = ?, updated_at = ?, history_json = ?
            WHERE document_id = ? AND version = ?
            """,
            (
                snapshot.state.value,
                snapshot.version,
                iso(snapshot.updated_at),
                self._history_json(snapshot),
                snapshot.document_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise PersistenceConflictError("lifecycle optimistic version conflict")
        return snapshot


class SqliteBindingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _binding(row: tuple[object, ...]) -> FiscalAccountBinding:
        return FiscalAccountBinding(
            binding_id=text(row[0], "binding_id"),
            host_scope=HostScope(
                namespace=HostNamespace(text(row[1], "host_namespace")),
                tenant_id=text(row[2], "external_tenant_id"),
                unit_id=text(row[3], "external_unit_id"),
            ),
            fiscal_account_id=FiscalAccountId(text(row[4], "fiscal_account_id")),
            fiscal_unit_id=FiscalUnitId(text(row[5], "fiscal_unit_id")),
        )

    def add(self, binding: FiscalAccountBinding) -> FiscalAccountBinding:
        if not isinstance(binding, FiscalAccountBinding):
            raise FiscalValidationError("binding must be FiscalAccountBinding")
        existing_id = self.get_by_id(binding.binding_id)
        if existing_id is not None:
            if existing_id == binding:
                return existing_id
            raise PersistenceConflictError("binding_id already maps to another host scope")
        try:
            self._connection.execute(
                """
                INSERT INTO fm_fiscal_bindings (
                    binding_id, host_namespace, external_tenant_id, external_unit_id,
                    fiscal_account_id, fiscal_unit_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.binding_id,
                    binding.host_scope.namespace.value,
                    binding.host_scope.tenant_id,
                    binding.host_scope.unit_id,
                    binding.fiscal_account_id.value,
                    binding.fiscal_unit_id.value,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise PersistenceConflictError(
                "an exact fiscal binding already exists for this host scope"
            ) from exc
        return binding

    def resolve(self, host_scope: HostScope) -> FiscalAccountBinding:
        if not isinstance(host_scope, HostScope):
            raise FiscalValidationError("host_scope must be HostScope")
        row = one_row(
            self._connection.execute(
                """
                SELECT binding_id, host_namespace, external_tenant_id, external_unit_id,
                       fiscal_account_id, fiscal_unit_id
                FROM fm_fiscal_bindings
                WHERE host_namespace = ? AND external_tenant_id = ? AND external_unit_id = ?
                """,
                host_scope.canonical_key,
            )
        )
        if row is None:
            raise PersistenceStateError("no durable fiscal binding exists for exact host scope")
        return self._binding(row)

    def list_for_fiscal_unit(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[FiscalAccountBinding, ...]:
        # Human tenant authority selects internal account/unit, never external claims.
        page = scoped_page(scope, limit, offset)
        rows = self._connection.execute(
            """
            SELECT binding_id, host_namespace, external_tenant_id, external_unit_id,
                   fiscal_account_id, fiscal_unit_id
            FROM fm_fiscal_bindings
            WHERE fiscal_account_id = ? AND fiscal_unit_id = ?
            ORDER BY binding_id
            LIMIT ? OFFSET ?
            """,
            (scope.tenant_id, scope.unit_id, page[-2], page[-1]),
        ).fetchall()
        return tuple(self._binding(tuple(row)) for row in rows)

    def get_by_id(self, binding_id: str) -> FiscalAccountBinding | None:
        normalized = binding_id.strip()
        if not normalized:
            raise FiscalValidationError("binding_id must not be blank")
        row = one_row(
            self._connection.execute(
                """
                SELECT binding_id, host_namespace, external_tenant_id, external_unit_id,
                       fiscal_account_id, fiscal_unit_id
                FROM fm_fiscal_bindings WHERE binding_id = ?
                """,
                (normalized,),
            )
        )
        return None if row is None else self._binding(row)
