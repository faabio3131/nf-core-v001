"""Atomic, replayable DPS serial reservations inside the existing fiscal UoW.

SQLite serializes writers with BEGIN IMMEDIATE. PostgreSQL takes advisory
transaction locks in the subclass before using this same repository contract.
This store is never a second tenant or fiscal-authorization authority.
"""
from __future__ import annotations

import sqlite3

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.issuance.nfe_nfse import NfseCanonicalDocument
from kordena_fiscal.numbering.dps import MAX_DPS_NUMBER, DpsNumberReservation

from .ports import PersistenceConflictError


class SqliteDpsNumberingStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def reserve(
        self, document: NfseCanonicalDocument, *, input_fingerprint: str,
    ) -> DpsNumberReservation:
        if not isinstance(document, NfseCanonicalDocument):
            raise FiscalValidationError("DPS numbering requires canonical NFS-e document")
        scope = document.scope
        if scope.host_namespace is None:
            raise FiscalValidationError("DPS issuer counter requires host namespace")
        if (
            not isinstance(input_fingerprint, str)
            or len(input_fingerprint) != 64
            or any(x not in "0123456789abcdef" for x in input_fingerprint)
        ):
            raise FiscalValidationError("DPS input fingerprint must be SHA-256")
        if document.dps_number is not None:
            raise FiscalValidationError("DPS number must be assigned by fiscal UoW")
        issuer = document.issuer
        cnpj = issuer.cnpj.value
        municipality = issuer.address.jurisdiction.municipality_ibge_code
        if (
            not cnpj.isascii() or not cnpj.isdecimal() or len(cnpj) != 14
            or municipality is None or len(municipality) != 7
            or not municipality.isascii() or not municipality.isdecimal()
        ):
            raise FiscalValidationError("DPS counter requires numeric issuer CNPJ and IBGE")
        series = document.dps_series
        owner = (scope.tenant_id, scope.unit_id)
        legal_key = (scope.host_namespace, cnpj, municipality, scope.environment.value, series)
        document_key = (
            scope.host_namespace, scope.tenant_id, scope.unit_id,
            scope.environment.value, document.document_id,
        )
        old = self._connection.execute(
            """
            SELECT issuer_cnpj, issuer_municipality_ibge, series,
                   request_fingerprint, number
            FROM fm_nfse_dps_reservations
            WHERE host_namespace=? AND tenant_id=? AND unit_id=?
              AND environment=? AND document_id=?
            """,
            document_key,
        ).fetchone()
        if old is not None:
            if tuple(old[:4]) != (cnpj, municipality, series, input_fingerprint):
                raise PersistenceConflictError(
                    "DPS reservation replay conflicts with issuer, series or content"
                )
            return DpsNumberReservation(series=series, number=int(old[4]))
        current = self._connection.execute(
            """
            SELECT owner_tenant_id, owner_unit_id, last_number
            FROM fm_nfse_dps_counters
            WHERE host_namespace=? AND issuer_cnpj=? AND issuer_municipality_ibge=?
              AND environment=? AND series=?
            """,
            legal_key,
        ).fetchone()
        if current is None:
            next_number = 1
            self._connection.execute(
                """
                INSERT INTO fm_nfse_dps_counters (
                    host_namespace, issuer_cnpj, issuer_municipality_ibge,
                    environment, series, owner_tenant_id, owner_unit_id, last_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*legal_key, *owner, next_number),
            )
        else:
            if tuple(current[:2]) != owner:
                raise PersistenceConflictError(
                    "DPS legal issuer counter already owned by another fiscal unit"
                )
            next_number = int(current[2]) + 1
            if next_number > MAX_DPS_NUMBER:
                raise FiscalValidationError("DPS legal issuer sequence exhausted")
            self._connection.execute(
                """
                UPDATE fm_nfse_dps_counters SET last_number=?
                WHERE host_namespace=? AND issuer_cnpj=? AND issuer_municipality_ibge=?
                  AND environment=? AND series=?
                """,
                (next_number, *legal_key),
            )
        self._connection.execute(
            """
            INSERT INTO fm_nfse_dps_reservations (
                host_namespace, tenant_id, unit_id, environment, document_id,
                request_fingerprint, issuer_cnpj, issuer_municipality_ibge, series, number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*document_key, input_fingerprint, cnpj, municipality, series, next_number),
        )
        return DpsNumberReservation(series=series, number=next_number)
