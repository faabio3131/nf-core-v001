"""Domain exceptions for the fiscal engine."""


class FiscalDomainError(Exception):
    """Base exception for deterministic fiscal-domain failures."""


class FiscalValidationError(FiscalDomainError, ValueError):
    """Raised when a fiscal value object violates a domain invariant."""


class FiscalPreDispatchError(FiscalValidationError):
    """Failure certain to have happened BEFORE any external fiscal request.

    Raised only when no HTTP/SOAP intent left the process. Callers may then
    close the claimed attempt without reconciliation, because the provider
    cannot hold a document for it. Never raise this after a send began.
    """
