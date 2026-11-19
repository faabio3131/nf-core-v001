"""Adapter for the Receita Federal open-source Simples Nacional RTC calculator.

RTC-RFB-01/03. The official component (github.com/ReceitaFederal/
calculadora-rtc-simples-nacional, MIT) runs as an INTERNAL service; NFCore stays
the only fiscal authority. This module never imports Java code and never calls a
public Receita endpoint: it talks to a pinned local instance over HTTP.

Contract read from the pinned source (commit below):
POST /api/calculadora/observabilidade/simples-nacional always answers HTTP 200,
even when items fail; each object carries ``estadoItem`` in {CALCULADO,
NAO_CALCULADO, NAO_IMPLEMENTADO, INCONSISTENCIA_ENTRADA, FALHA_TECNICA}. A 200
alone is therefore never accepted: every requested item must come back exactly
once, and only CALCULADO items may feed a fiscal document. The component does
not compute the Simples effective rate (PGDAS-D); pIBSSN/pCBSSN come from the
caller's reviewed source or are the component's preloaded first-bracket rates.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from kordena_fiscal.domain import FiscalValidationError


@dataclass(frozen=True, slots=True)
class RfbComponentPin:
    repository: str
    commit: str
    application_version: str
    license: str


# Pinned exactly; changing it is a reviewed change (RTC-RFB-01/10).
SIMPLES_CALCULATOR_PIN = RfbComponentPin(
    repository="https://github.com/ReceitaFederal/calculadora-rtc-simples-nacional",
    commit="c5b0f01c8351c3f0d0795cc617b29d233e9f98df",
    application_version="0.0.6",
    license="MIT",
)

CALCULATE_PATH = "/calculadora/observabilidade/simples-nacional"
VERSION_PATH = "/versao"
_MAX_RESPONSE = 2 * 1024 * 1024
_STATES = frozenset({
    "CALCULADO", "NAO_CALCULADO", "NAO_IMPLEMENTADO",
    "INCONSISTENCIA_ENTRADA", "FALHA_TECNICA",
})
_CLASS_TRIB = re.compile(r"[0-9]{6}\Z")
_ATIV_SN = re.compile(r"[0-9]{2}\Z")
_INTERNAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class RfbCalculatorError(FiscalValidationError):
    """Transport, contract or version failure; never a fiscal value."""


class RfbCalculationRejected(RfbCalculatorError):
    """At least one item is not CALCULADO; nothing may be used for issuance."""

    def __init__(self, rejected: Sequence[tuple[int, str, tuple[str, ...]]]) -> None:
        self.rejected = tuple(rejected)
        summary = ", ".join(
            f"item {n}: {state}" + (f" ({'/'.join(codes)})" if codes else "")
            for n, state, codes in self.rejected
        )
        super().__init__("Official Simples calculation not usable: " + summary)


def _money(value: Decimal | str) -> str:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise RfbCalculatorError("Invalid monetary amount") from None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise RfbCalculatorError("Monetary amounts need exactly two decimal places")
    return f"{amount:.2f}"


def _rate(value: Decimal | str | None) -> str | None:
    if value is None:
        return None
    try:
        rate = Decimal(str(value))
    except InvalidOperation:
        raise RfbCalculatorError("Invalid rate") from None
    if not rate.is_finite() or not Decimal("0") <= rate <= Decimal("100"):
        raise RfbCalculatorError("Rate must be a percentage between 0 and 100")
    return str(rate)


@dataclass(frozen=True, slots=True)
class SimplesItem:
    numero: int
    c_class_trib: str
    base_calculo: Decimal
    c_ativ_sn: str | None = None
    valor_imposto_seletivo: Decimal | None = None
    p_ibs_sn: Decimal | None = None
    p_cbs_sn: Decimal | None = None

    def as_payload(self) -> dict[str, object]:
        if type(self.numero) is not int or not 1 <= self.numero <= 990:
            raise RfbCalculatorError("Item number must be 1..990")
        if not _CLASS_TRIB.fullmatch(self.c_class_trib or ""):
            raise RfbCalculatorError("cClassTrib must have 6 digits")
        if self.c_ativ_sn is not None and not _ATIV_SN.fullmatch(self.c_ativ_sn):
            raise RfbCalculatorError("cAtivSN must have 2 digits")
        payload: dict[str, object] = {
            "numero": self.numero, "cClassTrib": self.c_class_trib,
            "baseCalculo": _money(self.base_calculo),
        }
        if self.c_ativ_sn is not None:
            payload["cAtivSN"] = self.c_ativ_sn
        if self.valor_imposto_seletivo is not None:
            payload["valorImpostoSeletivo"] = _money(self.valor_imposto_seletivo)
        for key, value in (("pIBSSN", self.p_ibs_sn), ("pCBSSN", self.p_cbs_sn)):
            rate = _rate(value)
            if rate is not None:
                payload[key] = rate
        return payload


@dataclass(frozen=True, slots=True)
class SimplesItemResult:
    numero: int
    state: str
    error_codes: tuple[str, ...]
    values: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class SimplesCalculation:
    items: tuple[SimplesItemResult, ...]
    totals: Mapping[str, Decimal]
    component_version: str

    def require_all_calculated(self) -> SimplesCalculation:
        """Fail closed for issuance unless every item is CALCULADO."""
        rejected = [
            (item.numero, item.state, item.error_codes)
            for item in self.items if item.state != "CALCULADO"
        ]
        if rejected:
            raise RfbCalculationRejected(rejected)
        return self


# Contract of the pinned source (OperacaoSimplesInput, NT 2026.005): tpDoc is
# the DF-e model code; the current database load covers only 55 and 65.
SUPPORTED_DOCUMENT_TYPES = frozenset({"55", "65"})


def build_request(
    *, operation_id: str, date: str, document_type: str, crt: str,
    items: Sequence[SimplesItem], government_entity: str | None = None,
    ibs_cbs_regime: str | None = None,
) -> dict[str, object]:
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 120:
        raise RfbCalculatorError("Operation id is required")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date or ""):
        raise RfbCalculatorError("Operation date must be YYYY-MM-DD")
    if document_type not in SUPPORTED_DOCUMENT_TYPES:
        raise RfbCalculatorError("Official Simples calculator covers only NF-e (55) and NFC-e (65)")
    # CRT 4 (MEI) and CRT 3 without tpRegimeIBSCBS=2 are out of the official scope.
    if crt not in {"1", "2", "3"} or (crt == "3") != (ibs_cbs_regime == "2"):
        raise RfbCalculatorError("CRT/tpRegimeIBSCBS outside the official Simples scope")
    if ibs_cbs_regime not in (None, "2"):
        raise RfbCalculatorError("Only tpRegimeIBSCBS=2 is accepted by this endpoint")
    if government_entity not in (None, "1", "2", "3", "4"):
        raise RfbCalculatorError("tpEnteGov must be 1..4")
    if not items or len({item.numero for item in items}) != len(items):
        raise RfbCalculatorError("Items must be present and uniquely numbered")
    request: dict[str, object] = {
        "id": operation_id, "data": date, "tpDoc": document_type, "CRT": crt,
        "itens": [item.as_payload() for item in items],
    }
    if ibs_cbs_regime is not None:
        request["tpRegimeIBSCBS"] = ibs_cbs_regime
    if government_entity is not None:
        request["tpEnteGov"] = government_entity
    return request


def _decimal_map(raw: object) -> dict[str, Decimal]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RfbCalculatorError("Unexpected value block in official reply")
    values: dict[str, Decimal] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, Decimal | int):
            values[key] = Decimal(value)
    return values


def parse_response(
    raw: bytes, *, expected_items: Sequence[int], component_version: str,
) -> SimplesCalculation:
    """Strictly map the official reply; HTTP 200 is not evidence by itself."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_RESPONSE:
        raise RfbCalculatorError("Invalid official reply size")
    try:
        body = json.loads(raw, parse_float=Decimal)
    except (UnicodeDecodeError, ValueError):
        raise RfbCalculatorError("Official reply is not JSON") from None
    objects = body.get("objetos") if isinstance(body, dict) else None
    if not isinstance(objects, list):
        raise RfbCalculatorError("Official reply has no per-item results")
    results: list[SimplesItemResult] = []
    for entry in objects:
        if not isinstance(entry, dict):
            raise RfbCalculatorError("Malformed official item")
        number, state = entry.get("nObj"), entry.get("estadoItem")
        if type(number) is not int or state not in _STATES:
            raise RfbCalculatorError("Official item lacks number or known state")
        errors = entry.get("erros") or []
        if not isinstance(errors, list):
            raise RfbCalculatorError("Malformed official item errors")
        codes = tuple(
            str(error["code"]) for error in errors
            if isinstance(error, dict) and isinstance(error.get("code"), str)
        )
        values = _decimal_map(entry.get("tribCalc"))
        if state == "CALCULADO" and not values:
            raise RfbCalculatorError("CALCULADO item without calculated values")
        results.append(SimplesItemResult(number, str(state), codes, values))
    returned = [item.numero for item in results]
    if sorted(returned) != sorted(expected_items) or len(set(returned)) != len(returned):
        raise RfbCalculatorError("Official reply does not answer exactly the requested items")
    return SimplesCalculation(
        items=tuple(sorted(results, key=lambda item: item.numero)),
        totals=_decimal_map(body.get("total")),
        component_version=component_version,
    )


def _internal_base_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"} or not parts.hostname
        or parts.username or parts.password or parts.query or parts.fragment
        or not parts.path.rstrip("/").endswith("/api")
    ):
        raise RfbCalculatorError("Calculator base URL must be an internal .../api URL")
    host = parts.hostname
    if host not in _INTERNAL_HOSTS and "." in host:
        # Only loopback or a bare container/service name on the private network.
        raise RfbCalculatorError("Calculator must run on the internal network")
    return url.rstrip("/")


def _http(
    method: str, url: str, body: bytes | None, timeout: float,
) -> tuple[bytes, Mapping[str, str]]:
    request = Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - internal URL validated
            data = response.read(_MAX_RESPONSE + 1)
            headers = {key.lower(): value for key, value in response.headers.items()}
    except (HTTPError, URLError, TimeoutError, OSError):
        raise RfbCalculatorError("Official calculator unavailable") from None
    return bytes(data), headers


class RfbSimplesCalculatorClient:
    def __init__(
        self, *, base_url: str, timeout_seconds: float = 10,
        pin: RfbComponentPin = SIMPLES_CALCULATOR_PIN,
        transport: Callable[[str, str, bytes | None, float], tuple[bytes, Mapping[str, str]]]
        | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Invalid calculator timeout")
        self._base = _internal_base_url(base_url)
        self._timeout = timeout_seconds
        self._pin = pin
        self._transport = transport or _http

    def verify_version(self) -> str:
        """Refuse a component whose application version differs from the pin."""
        raw, _ = self._transport("GET", self._base + VERSION_PATH, None, self._timeout)
        try:
            body: Any = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            raise RfbCalculatorError("Calculator version reply is not JSON") from None
        app, database = _find_version(body)
        if app != self._pin.application_version:
            raise RfbCalculatorError(
                f"Calculator version {app!r} differs from pinned "
                f"{self._pin.application_version!r}"
            )
        if not database:
            raise RfbCalculatorError("Calculator did not report its database version")
        # Both versions are evidence for the audit trail of every calculation.
        return f"app={app};db={database}"

    def calculate(self, request: Mapping[str, object]) -> SimplesCalculation:
        version = self.verify_version()
        items = request.get("itens")
        if not isinstance(items, list):
            raise RfbCalculatorError("Request has no items")
        expected = [int(item["numero"]) for item in items if isinstance(item, dict)]
        raw, _ = self._transport(
            "POST", self._base + CALCULATE_PATH,
            json.dumps(request, separators=(",", ":")).encode("utf-8"), self._timeout,
        )
        return parse_response(raw, expected_items=expected, component_version=version)


def _find_version(body: Any) -> tuple[str | None, str | None]:
    """VersaoDomain of the pinned source: versaoApp / versaoDb (strings)."""
    if not isinstance(body, dict):
        return None, None
    app, db = body.get("versaoApp"), body.get("versaoDb")
    return (app if isinstance(app, str) else None, db if isinstance(db, str) else None)


@dataclass(frozen=True, slots=True)
class ShadowDivergence:
    numero: int
    field: str
    nfcore: Decimal | None
    official: Decimal | None


def compare_shadow(
    official: SimplesCalculation, nfcore: Mapping[int, Mapping[str, Decimal]],
    *, fields: Sequence[str] = ("vIBSSN", "vCBSSN", "vBC"),
    tolerance: Decimal = Decimal("0.00"),
) -> tuple[ShadowDivergence, ...]:
    """RTC-RFB-04: record differences only; never changes any fiscal value."""
    divergences: list[ShadowDivergence] = []
    for item in official.items:
        ours = nfcore.get(item.numero, {})
        for field in fields:
            a, b = ours.get(field), item.values.get(field)
            if a is None and b is None:
                continue
            if a is None or b is None or abs(a - b) > tolerance:
                divergences.append(ShadowDivergence(item.numero, field, a, b))
    return tuple(divergences)
