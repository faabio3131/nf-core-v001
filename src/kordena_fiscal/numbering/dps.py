"""Issuer-scoped NFS-e DPS numbering contract, under the fiscal Unit of Work."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from kordena_fiscal.domain import FiscalValidationError

if TYPE_CHECKING:
    from kordena_fiscal.issuance.nfe_nfse import NfseCanonicalDocument

MAX_DPS_NUMBER = 999_999_999_999_999


@dataclass(frozen=True, slots=True)
class DpsNumberReservation:
    series: int
    number: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.series, int)
            or isinstance(self.series, bool)
            or not 1 <= self.series <= 99_999
        ):
            raise FiscalValidationError("DPS series must be within 1..99999")
        if (
            not isinstance(self.number, int)
            or isinstance(self.number, bool)
            or not 1 <= self.number <= MAX_DPS_NUMBER
        ):
            raise FiscalValidationError("DPS number must be within 1..999999999999999")


class DpsNumberingStore(Protocol):
    """One legal issuer/municipality/environment/series -> one serial sequence.

    Idempotent document reservations are committed atomically with the
    canonical fiscal preparation record; never use SELECT MAX(number)+1.
    """

    def reserve(
        self, document: NfseCanonicalDocument, *, input_fingerprint: str,
    ) -> DpsNumberReservation: ...
