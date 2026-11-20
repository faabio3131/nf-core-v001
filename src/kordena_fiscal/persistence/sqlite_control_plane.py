"""SQLite persistence for the governed V2-11 Control Plane."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from kordena_fiscal.control_plane.models import (
    ControlPlaneAuditAction,
    ControlPlaneAuditEvent,
    FiscalOrganization,
    FiscalUnitRegistration,
    SecretReference,
    SecretReferenceKind,
)
from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    CnaeCode,
    Cnpj,
    ExecutionScope,
    FiscalAddress,
    FiscalEnvironment,
    FiscalProfile,
    FiscalValidationError,
    MunicipalRegistration,
    StateRegistration,
    TaxRegimeCode,
)

from ._sqlite_common import dt, integer, iso, one_row, optional_text, scoped_page, text
from .ports import PersistenceConflictError, PersistenceStateError

_PROFILE_SELECT = """
    profile_id, version, host_namespace, tenant_id, unit_id,
    environment, correlation_id, cnpj, legal_name, tax_regime,
    state_registration_state, state_registration_number,
    state_registration_exempt, primary_cnae, street, address_number,
    district, municipality_name, state_code, municipality_ibge_code,
    postal_code, complement, effective_from, effective_to, trade_name,
    municipal_registration_number
"""


class SqliteControlPlaneStore:
    """Transactional durable repository for Control Plane administrative state."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_organization(self, organization: FiscalOrganization) -> FiscalOrganization:
        if not isinstance(organization, FiscalOrganization):
            raise FiscalValidationError("organization must be FiscalOrganization")
        if self.get_organization(organization.tenant_id) is not None:
            raise PersistenceConflictError(
                f"control-plane organization already exists: {organization.tenant_id}"
            )
        self._connection.execute(
            """
            INSERT INTO fm_control_plane_organizations (tenant_id, legal_name)
            VALUES (?, ?)
            """,
            (organization.tenant_id, organization.legal_name),
        )
        return organization

    def get_organization(self, tenant_id: str) -> FiscalOrganization | None:
        normalized = tenant_id.strip().lower()
        if not normalized:
            raise FiscalValidationError("tenant_id must not be blank")
        row = one_row(
            self._connection.execute(
                """
                SELECT tenant_id, legal_name
                FROM fm_control_plane_organizations
                WHERE tenant_id = ?
                """,
                (normalized,),
            )
        )
        if row is None:
            return None
        return FiscalOrganization(
            tenant_id=text(row[0], "tenant_id"),
            legal_name=text(row[1], "legal_name"),
        )

    def add_unit(self, registration: FiscalUnitRegistration) -> FiscalUnitRegistration:
        if not isinstance(registration, FiscalUnitRegistration):
            raise FiscalValidationError("registration must be FiscalUnitRegistration")
        if self.get_unit(registration.tenant_id, registration.unit_id) is not None:
            raise PersistenceConflictError(
                "control-plane unit already exists: "
                f"{registration.tenant_id}/{registration.unit_id}"
            )
        environments = json.dumps(
            sorted(environment.value for environment in registration.enabled_environments),
            separators=(",", ":"),
        )
        self._connection.execute(
            """
            INSERT INTO fm_control_plane_units (
                tenant_id, unit_id, display_name, enabled_environments_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                registration.tenant_id,
                registration.unit_id,
                registration.display_name,
                environments,
            ),
        )
        return registration

    def get_unit(self, tenant_id: str, unit_id: str) -> FiscalUnitRegistration | None:
        tenant = tenant_id.strip().lower()
        unit = unit_id.strip().lower()
        if not tenant or not unit:
            raise FiscalValidationError("tenant_id and unit_id must not be blank")
        row = one_row(
            self._connection.execute(
                """
                SELECT tenant_id, unit_id, display_name, enabled_environments_json
                FROM fm_control_plane_units
                WHERE tenant_id = ? AND unit_id = ?
                """,
                (tenant, unit),
            )
        )
        if row is None:
            return None
        raw_environments: object = json.loads(text(row[3], "enabled_environments_json"))
        if not isinstance(raw_environments, list) or not all(
            isinstance(item, str) for item in raw_environments
        ):
            raise PersistenceStateError("persisted enabled environments must be a string list")
        return FiscalUnitRegistration(
            tenant_id=text(row[0], "tenant_id"),
            unit_id=text(row[1], "unit_id"),
            display_name=text(row[2], "display_name"),
            enabled_environments=frozenset(FiscalEnvironment(item) for item in raw_environments),
        )

    def add_secret_reference(self, reference: SecretReference) -> SecretReference:
        if not isinstance(reference, SecretReference):
            raise FiscalValidationError("reference must be SecretReference")
        existing = self.get_secret_reference(
            reference.tenant_id,
            reference.unit_id,
            reference.environment,
            reference.kind,
            provider_id=reference.provider_id,
        )
        if existing is not None:
            raise PersistenceConflictError(
                "secret reference kind/provider is already bound for unit/environment"
            )
        self._connection.execute(
            """
            INSERT INTO fm_control_plane_secret_references (
                reference_id, kind, tenant_id, unit_id, environment, provider_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                reference.reference_id,
                reference.kind.value,
                reference.tenant_id,
                reference.unit_id,
                reference.environment.value,
                reference.provider_scope,
            ),
        )
        return reference

    def put_secret_reference(self, reference: SecretReference) -> SecretReference:
        self._connection.execute(
            """INSERT INTO fm_control_plane_secret_references
            (reference_id, kind, tenant_id, unit_id, environment, provider_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, unit_id, environment, kind, provider_id)
            DO UPDATE SET reference_id = excluded.reference_id""",
            (
                reference.reference_id,
                reference.kind.value,
                reference.tenant_id,
                reference.unit_id,
                reference.environment.value,
                reference.provider_scope,
            ),
        )
        return reference

    def get_secret_reference(
        self,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        kind: SecretReferenceKind,
        *,
        provider_id: str | None = None,
    ) -> SecretReference | None:
        if not isinstance(environment, FiscalEnvironment):
            raise FiscalValidationError("environment must be FiscalEnvironment")
        if not isinstance(kind, SecretReferenceKind):
            raise FiscalValidationError("kind must be SecretReferenceKind")
        tenant = tenant_id.strip().lower()
        unit = unit_id.strip().lower()
        provider = "" if provider_id is None else provider_id.strip().lower()
        if not tenant or not unit:
            raise FiscalValidationError("tenant_id and unit_id must not be blank")
        if provider_id is not None and not provider:
            raise FiscalValidationError("provider_id must not be blank")
        row = one_row(
            self._connection.execute(
                """
                SELECT reference_id, kind, tenant_id, unit_id, environment, provider_id
                FROM fm_control_plane_secret_references
                WHERE tenant_id = ? AND unit_id = ? AND environment = ?
                  AND kind = ? AND provider_id = ?
                """,
                (tenant, unit, environment.value, kind.value, provider),
            )
        )
        if row is None:
            return None
        persisted_provider = text(row[5], "provider_id")
        return SecretReference(
            reference_id=text(row[0], "reference_id"),
            kind=SecretReferenceKind(text(row[1], "kind")),
            tenant_id=text(row[2], "tenant_id"),
            unit_id=text(row[3], "unit_id"),
            environment=FiscalEnvironment(text(row[4], "environment")),
            provider_id=persisted_provider or None,
        )

    def list_secret_references(
        self, scope: ExecutionScope, *, limit: int = 100, offset: int = 0
    ) -> tuple[SecretReference, ...]:
        rows = self._connection.execute(
            """
            SELECT reference_id, kind, tenant_id, unit_id, environment, provider_id
            FROM fm_control_plane_secret_references
            WHERE tenant_id = ? AND unit_id = ? AND environment = ?
            ORDER BY kind, provider_id, reference_id
            LIMIT ? OFFSET ?
            """,
            scoped_page(scope, limit, offset)[1:],
        ).fetchall()
        return tuple(
            SecretReference(
                reference_id=text(row[0], "reference_id"),
                kind=SecretReferenceKind(text(row[1], "kind")),
                tenant_id=text(row[2], "tenant_id"),
                unit_id=text(row[3], "unit_id"),
                environment=FiscalEnvironment(text(row[4], "environment")),
                provider_id=text(row[5], "provider_id") or None,
            )
            for row in rows
        )

    def add_profile(self, profile: FiscalProfile) -> FiscalProfile:
        if not isinstance(profile, FiscalProfile):
            raise FiscalValidationError("profile must be FiscalProfile")
        host_namespace = profile.scope.host_namespace
        if host_namespace is None:
            raise FiscalValidationError("durable Control Plane profile requires host_namespace")
        if self.get_profile(profile.profile_id, profile.version) is not None:
            raise PersistenceConflictError("fiscal profile id/version already exists")
        new_end = None if profile.effective_to is None else iso(profile.effective_to)
        overlapping = one_row(
            self._connection.execute(
                """
                SELECT profile_id, version
                FROM fm_control_plane_fiscal_profiles
                WHERE host_namespace = ? AND tenant_id = ? AND unit_id = ?
                  AND environment = ?
                  AND (CAST(? AS TEXT) IS NULL OR effective_from < ?)
                  AND (effective_to IS NULL OR effective_to > ?)
                LIMIT 1
                """,
                (
                    host_namespace,
                    profile.scope.tenant_id,
                    profile.scope.unit_id,
                    profile.scope.environment.value,
                    new_end,
                    new_end,
                    iso(profile.effective_from),
                ),
            )
        )
        if overlapping is not None:
            raise PersistenceConflictError(
                "fiscal profile effective period overlaps an existing profile"
            )
        address = profile.address
        self._connection.execute(
            """
            INSERT INTO fm_control_plane_fiscal_profiles (
                profile_id, version, host_namespace, tenant_id, unit_id, environment,
                correlation_id, cnpj, legal_name, tax_regime,
                state_registration_state, state_registration_number,
                state_registration_exempt, primary_cnae,
                street, address_number, district, municipality_name, state_code,
                municipality_ibge_code, postal_code, complement,
                effective_from, effective_to, trade_name, municipal_registration_number
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                profile.profile_id,
                profile.version,
                host_namespace,
                profile.scope.tenant_id,
                profile.scope.unit_id,
                profile.scope.environment.value,
                profile.scope.correlation_id,
                profile.cnpj.value,
                profile.legal_name,
                int(profile.tax_regime),
                profile.state_registration.state_code,
                profile.state_registration.number,
                1 if profile.state_registration.exempt else 0,
                profile.primary_cnae.value,
                address.street,
                address.number,
                address.district,
                address.municipality_name,
                address.jurisdiction.state_code,
                address.jurisdiction.municipality_ibge_code,
                address.postal_code,
                address.complement,
                iso(profile.effective_from),
                new_end,
                profile.trade_name,
                None
                if profile.municipal_registration is None
                else profile.municipal_registration.number,
            ),
        )
        return profile

    @staticmethod
    def _profile(row: tuple[object, ...]) -> FiscalProfile:
        municipal = optional_text(row[25], "municipal_registration_number")
        return FiscalProfile(
            profile_id=text(row[0], "profile_id"),
            version=integer(row[1], "version"),
            scope=ExecutionScope(
                host_namespace=text(row[2], "host_namespace"),
                tenant_id=text(row[3], "tenant_id"),
                unit_id=text(row[4], "unit_id"),
                environment=FiscalEnvironment(text(row[5], "environment")),
                correlation_id=text(row[6], "correlation_id"),
            ),
            cnpj=Cnpj(text(row[7], "cnpj")),
            legal_name=text(row[8], "legal_name"),
            tax_regime=TaxRegimeCode(integer(row[9], "tax_regime")),
            state_registration=StateRegistration(
                state_code=text(row[10], "state_registration_state"),
                number=optional_text(row[11], "state_registration_number"),
                exempt=bool(integer(row[12], "state_registration_exempt")),
            ),
            primary_cnae=CnaeCode(text(row[13], "primary_cnae")),
            address=FiscalAddress(
                street=text(row[14], "street"),
                number=text(row[15], "address_number"),
                district=text(row[16], "district"),
                municipality_name=text(row[17], "municipality_name"),
                jurisdiction=BrazilianJurisdiction(
                    state_code=text(row[18], "state_code"),
                    municipality_ibge_code=optional_text(row[19], "municipality_ibge_code"),
                ),
                postal_code=text(row[20], "postal_code"),
                complement=optional_text(row[21], "complement"),
            ),
            effective_from=dt(text(row[22], "effective_from")),
            effective_to=(None if row[23] is None else dt(text(row[23], "effective_to"))),
            trade_name=optional_text(row[24], "trade_name"),
            municipal_registration=(
                None if municipal is None else MunicipalRegistration(municipal)
            ),
        )

    def supersede_profile(
        self, previous: FiscalProfile, successor: FiscalProfile,
    ) -> FiscalProfile:
        """Close the open-ended current version at the successor's start, then add it.

        History is never rewritten: only the NULL effective_to of the immediately
        preceding version is set, exactly once, to successor.effective_from.
        """
        if not isinstance(previous, FiscalProfile) or not isinstance(successor, FiscalProfile):
            raise FiscalValidationError("profiles must be FiscalProfile")
        if (
            successor.profile_id != previous.profile_id
            or successor.version != previous.version + 1
            or successor.scope.identity_partition_key != previous.scope.identity_partition_key
            or successor.effective_to is not None
            or successor.effective_from <= previous.effective_from
        ):
            raise FiscalValidationError("successor must be the next open version in the scope")
        stored = self.get_profile(previous.profile_id, previous.version)
        if stored is None or stored.effective_to is not None:
            raise PersistenceConflictError("previous fiscal profile is not the open version")
        cursor = self._connection.execute(
            """
            UPDATE fm_control_plane_fiscal_profiles SET effective_to = ?
            WHERE profile_id = ? AND version = ? AND effective_to IS NULL
            """,
            (iso(successor.effective_from), previous.profile_id, previous.version),
        )
        if cursor.rowcount != 1:
            raise PersistenceConflictError("previous fiscal profile changed concurrently")
        return self.add_profile(successor)

    def get_profile(self, profile_id: str, version: int) -> FiscalProfile | None:
        normalized = profile_id.strip()
        if not normalized:
            raise FiscalValidationError("profile_id must not be blank")
        if version < 1:
            raise FiscalValidationError("version must be >= 1")
        row = one_row(
            self._connection.execute(
                f"""
                SELECT {_PROFILE_SELECT}
                FROM fm_control_plane_fiscal_profiles
                WHERE profile_id = ? AND version = ?
                """,
                (normalized, version),
            )
        )
        return None if row is None else self._profile(row)

    def resolve_profile(
        self,
        *,
        host_namespace: str,
        tenant_id: str,
        unit_id: str,
        environment: FiscalEnvironment,
        instant: datetime,
    ) -> FiscalProfile | None:
        if not isinstance(environment, FiscalEnvironment):
            raise FiscalValidationError("environment must be FiscalEnvironment")
        host = host_namespace.strip().lower()
        tenant = tenant_id.strip().lower()
        unit = unit_id.strip().lower()
        if not host or not tenant or not unit:
            raise FiscalValidationError("host_namespace, tenant_id and unit_id must not be blank")
        instant_iso = iso(instant)
        rows = self._connection.execute(
            f"""
            SELECT {_PROFILE_SELECT}
            FROM fm_control_plane_fiscal_profiles
            WHERE host_namespace = ? AND tenant_id = ? AND unit_id = ?
              AND environment = ? AND effective_from <= ?
              AND (effective_to IS NULL OR effective_to > ?)
            ORDER BY effective_from DESC
            LIMIT 2
            """,
            (
                host,
                tenant,
                unit,
                environment.value,
                instant_iso,
                instant_iso,
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise PersistenceStateError(
                "multiple effective fiscal profiles found for the same partition"
            )
        return self._profile(tuple(rows[0]))

    def append_audit(self, event: ControlPlaneAuditEvent) -> ControlPlaneAuditEvent:
        if not isinstance(event, ControlPlaneAuditEvent):
            raise FiscalValidationError("event must be ControlPlaneAuditEvent")
        existing = one_row(
            self._connection.execute(
                "SELECT event_id FROM fm_control_plane_audit WHERE event_id = ?",
                (event.event_id,),
            )
        )
        if existing is not None:
            raise PersistenceConflictError("control-plane audit event_id already exists")
        self._connection.execute(
            """
            INSERT INTO fm_control_plane_audit (
                event_id, occurred_at, actor_id, action, target_type, target_id,
                correlation_id, tenant_id, unit_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                iso(event.occurred_at),
                event.actor_id,
                event.action.value,
                event.target_type,
                event.target_id,
                event.correlation_id,
                event.tenant_id,
                event.unit_id,
            ),
        )
        return event

    @staticmethod
    def _audit(row: tuple[object, ...]) -> ControlPlaneAuditEvent:
        return ControlPlaneAuditEvent(
            event_id=text(row[0], "event_id"),
            occurred_at=dt(text(row[1], "occurred_at")),
            actor_id=text(row[2], "actor_id"),
            action=ControlPlaneAuditAction(text(row[3], "action")),
            target_type=text(row[4], "target_type"),
            target_id=text(row[5], "target_id"),
            correlation_id=text(row[6], "correlation_id"),
            tenant_id=text(row[7], "tenant_id"),
            unit_id=optional_text(row[8], "unit_id"),
        )

    def list_audit(
        self,
        tenant_id: str | None = None,
    ) -> tuple[ControlPlaneAuditEvent, ...]:
        if tenant_id is None:
            cursor = self._connection.execute(
                """
                SELECT event_id, occurred_at, actor_id, action, target_type, target_id,
                       correlation_id, tenant_id, unit_id
                FROM fm_control_plane_audit
                ORDER BY occurred_at, event_id
                """
            )
        else:
            tenant = tenant_id.strip().lower()
            if not tenant:
                raise FiscalValidationError("tenant_id must not be blank")
            cursor = self._connection.execute(
                """
                SELECT event_id, occurred_at, actor_id, action, target_type, target_id,
                       correlation_id, tenant_id, unit_id
                FROM fm_control_plane_audit
                WHERE tenant_id = ?
                ORDER BY occurred_at, event_id
                """,
                (tenant,),
            )
        return tuple(self._audit(tuple(row)) for row in cursor.fetchall())
