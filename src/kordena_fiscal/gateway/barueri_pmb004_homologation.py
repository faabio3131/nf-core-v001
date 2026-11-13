"""Barueri PMB004: bounded SOAP/mTLS upload, status and return-file recovery.

Official contract: Prefeitura de Barueri XML_RPS_Versao_01.pdf (WebService
v1.05, March/2025) + RPS_Layout-v4.2.pdf (PMB004, January/2026).
The endpoint accepts an ASYNCHRONOUS RPS file. OK200 only acknowledges
a remittance; it is NEVER an authorized NFS-e or signed fiscal receipt.

No municipal RPS is built from browser-supplied content here: a trusted
canonical builder must produce the pinned PMB004 fixed-width file, and its
caller must hold the fiscal idempotency/sequence authority.
"""
from __future__ import annotations

import base64
import binascii
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.domain import (
    BrazilianJurisdiction,
    Cnpj,
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    TaxRegimeCode,
)
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects, build_fiscal_tls_context
from kordena_fiscal.gateway.provider import ProviderSelectionResolver
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.vault.a1_preflight import validate_a1_for_issuer

BARUERI_IBGE = "3505708"
BARUERI_PMB004_PROVIDER = "barueri-pmb004-homologation"
BARUERI_HOMOLOGATION_URL = "https://testeeiss.barueri.sp.gov.br/nfeservice/wsrps.asmx"
_NS = "http://www.barueri.sp.gov.br/nfe"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_LIMIT = 2_097_152
_METHODS = frozenset({
    "NFeLoteEnviarArquivo", "NFeLoteStatusArquivo",
    "NFeLoteBaixarArquivo", "NFeLoteListarArquivos",
})


class BarueriContractError(FiscalValidationError):
    """Safe Barueri contract or transport failure (no token/XML echo)."""


@dataclass(frozen=True, slots=True)
class BarueriRpsBatch:
    """Already canonicalized PMB004, with immutable issuer and remittance ID."""

    scope: ExecutionScope
    issuer_cnpj: Cnpj
    municipal_registration: str
    tax_regime: TaxRegimeCode
    competence_date: date
    remittance: str
    file_name: str
    rps_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ExecutionScope):
            raise BarueriContractError("Issuer scope is required")
        if not isinstance(self.issuer_cnpj, Cnpj):
            raise BarueriContractError("Issuer CNPJ is required")
        if not isinstance(self.tax_regime, TaxRegimeCode) or type(self.competence_date) is not date:
            raise BarueriContractError("Reviewed regime and service competence required")
        if (
            self.scope.environment is not FiscalEnvironment.HOMOLOGATION
            or not self.scope.host_namespace
        ):
            raise BarueriContractError("PMB004 transport requires scoped homologation")
        if self.tax_regime is TaxRegimeCode.MEI and self.competence_date >= date(2023, 9, 1):
            raise BarueriContractError("MEI requires National NFS-e")
        if (
            self.tax_regime in (
                TaxRegimeCode.SIMPLES_NACIONAL,
                TaxRegimeCode.SIMPLES_NACIONAL_EXCESS_SUBLIMIT,
            )
            and self.competence_date >= date(2026, 11, 1)
        ):
            raise BarueriContractError("ME/EPP Simples requires National NFS-e")
        if (
            not isinstance(self.municipal_registration, str)
            or len(self.municipal_registration) != 7
            or not self.municipal_registration.isascii()
            or not self.municipal_registration.isalnum()
            or not isinstance(self.remittance, str)
            or len(self.remittance) != 11
            or not self.remittance.isdecimal()
            or not self.remittance.isascii()
            or not isinstance(self.file_name, str)
            or not 1 <= len(self.file_name) <= 64
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
                   for c in self.file_name)
            or not self.file_name.endswith(".txt")
        ):
            raise BarueriContractError("Invalid PMB004 issuer/remittance filename")
        data = self.rps_bytes
        if not isinstance(data, bytes) or not 26 < len(data) <= _LIMIT:
            raise BarueriContractError("Missing or oversized PMB004 RPS file")
        if b"\n" in data.replace(b"\r\n", b"") or b"\r" in data.replace(b"\r\n", b""):
            raise BarueriContractError("PMB004 requires CRLF records")
        lines = data.split(b"\r\n")
        if lines[-1] != b"":
            raise BarueriContractError("PMB004 must end in CRLF")
        records = lines[:-1]
        if len(records) < 4 or not records[0].isascii():
            raise BarueriContractError("PMB004 missing required fiscal records")
        header = records[0]
        expected = (
            b"1" + self.municipal_registration.encode("ascii")
            + b"PMB004" + self.remittance.encode("ascii")
        )
        if header != expected:
            raise BarueriContractError("PMB004 header/remittance mismatch")
        # Official RPS Layout v4.2 (06/01/2026): field positions are fixed
        # length BEFORE CRLF: records 1=25,2=1970,3=18,4=531,5=697,9=38.
        # A validator supplied by the trusted issuer still verifies ALL fiscal
        # fields (ISS, RTC, withholding and municipality-specific conditions).
        lengths = {b"1": 25, b"2": 1970, b"3": 18, b"4": 531, b"5": 697, b"9": 38}
        counts: dict[bytes, int] = {}
        for i, line in enumerate(records):
            kind = line[:1]
            if kind not in lengths or len(line) != lengths[kind]:
                raise BarueriContractError("PMB004 fixed-width fiscal record mismatch")
            counts[kind] = counts.get(kind, 0) + 1
            if (i == 0) != (kind == b"1"):
                raise BarueriContractError("PMB004 header must be first")
            if (i == len(records) - 1) != (kind == b"9"):
                raise BarueriContractError("PMB004 trailer must be last")
        if (
            counts.get(b"1") != 1 or counts.get(b"9") != 1
            or not counts.get(b"2") or counts.get(b"2") != counts.get(b"4")
        ):
            raise BarueriContractError("PMB004 requires each RPS and its RTC ADN record")
        footer = records[-1]
        if (
            not footer[1:].isascii() or not footer[1:].isdigit()
            or int(footer[1:8]) != len(records)
        ):
            raise BarueriContractError("PMB004 trailer count or monetary totals are invalid")
        # Official RPS_Layout-v4.2, Jan/2026: record 2 positions 16-25
        # identify RPS, 26-39 date/time, 458-463 quantity, 464-478 unit
        # service value in centavos. Type 3 positions 4-18 carry retained
        # amounts. Type 9 positions 9-23 and 24-38 are monetary checksums.
        # These checks bind the remittance to its own physical records. They
        # do NOT replace the pinned field-by-field municipal/RTC validator.
        service_total = 0
        retained_total = 0
        rps_identifiers: set[tuple[bytes, bytes]] = set()
        for record in records[1:-1]:
            if record[:1] == b"2":
                rps_number = record[15:25]
                series = record[6:10]
                quantity = record[457:463]
                value = record[463:478]
                if (
                    record[1:6] != b"RPS  "
                    or not rps_number.isdigit()
                    or not rps_number.startswith(b"000")
                    or not quantity.isdigit()
                    or int(quantity) == 0
                    or not value.isdigit()
                    or int(value) == 0
                    or record[39:40] not in (b"E", b"C", b"R")
                ):
                    raise BarueriContractError("PMB004 invalid RPS identity or service value")
                situation = record[39:40]
                reason = record[40:42]
                target_note = record[42:49]
                # RPS_Layout-v4.2 (06/01/2026), page 2:
                # cancel 01/02 MUST carry zero RPS; substitute 03 MUST
                # carry newly allocated RPS; normal E/R requires an RPS.
                if situation == b"C":
                    if (
                        reason not in (b"01", b"02", b"03")
                        or not target_note.isdigit()
                        or int(target_note) <= 0
                        or (reason == b"03") != (int(rps_number) > 0)
                        or (reason != b"03" and int(rps_number) != 0)
                        or not record[54:62].isdigit()
                        or not record[62:242].strip()
                    ):
                        raise BarueriContractError(
                            "PMB004 cancellation/substitution RPS identity invalid"
                        )
                elif int(rps_number) <= 0:
                    raise BarueriContractError("PMB004 invalid RPS identity or service value")
                # The official Jan/2026 layout sets RPS=0000000000 for
                # every ordinary cancellation. Multiple distinct cancelled
                # invoices in ONE legitimate batch must not collide on 0;
                # use the original NFS-e number as uniqueness identity.
                key = (
                    (b"NFSE", target_note)
                    if situation == b"C" and reason in (b"01", b"02")
                    else (series, rps_number)
                )
                if key in rps_identifiers:
                    raise BarueriContractError("Duplicate PMB004 fiscal RPS event")
                try:
                    datetime.strptime(
                        (record[25:33] + record[33:39]).decode("ascii"), "%Y%m%d%H%M%S",
                    )
                except (ValueError, UnicodeDecodeError):
                    raise BarueriContractError("PMB004 invalid RPS issuance date/time") from None
                rps_identifiers.add(key)
                service_total += int(quantity) * int(value)
            elif record[:1] == b"3":
                if not record[3:18].isdigit():
                    raise BarueriContractError("PMB004 invalid retention amount")
                retained_total += int(record[3:18])
        if (
            int(footer[8:23]) != service_total
            or int(footer[23:38]) != retained_total
        ):
            raise BarueriContractError("PMB004 fiscal monetary checksum mismatch")
        # A trusted external validator must still verify ALL fiscal positions,
        # regime, ISS/RTC, withholding and the taxpayer's municipal profile.



@dataclass(frozen=True, slots=True)
class BarueriListedFile:
    """Taxpayer-scoped official read-only remittance entry."""

    original_file_name: str
    remittance: str
    situation: str
    return_file_name: str | None
    validation_only: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.original_file_name, str)
            or not 1 <= len(self.original_file_name) <= 64
            or not self.original_file_name.endswith(".txt")
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."
                   for c in self.original_file_name)
            or not isinstance(self.remittance, str)
            or len(self.remittance) != 11
            or not self.remittance.isascii()
            or not self.remittance.isdecimal()
            or self.situation not in ("-2", "-1", "0", "1", "2")
            or type(self.validation_only) is not bool
        ):
            raise BarueriContractError("Invalid listed municipal remittance identity")
        if self.return_file_name is not None and (
            not isinstance(self.return_file_name, str)
            or not 1 <= len(self.return_file_name) <= 128
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                   for c in self.return_file_name)
        ):
            raise BarueriContractError("Unsafe Barueri return file identity")


@dataclass(frozen=True, slots=True)
class BarueriReceipt:
    operation: str
    code: str
    remittance_protocol: str | None = None
    situation: str | None = None
    return_file_name: str | None = None
    downloaded_file: bytes | None = field(default=None, repr=False)
    listed_files: tuple[BarueriListedFile, ...] = ()

    @property
    def document_authorized(self) -> bool:
        # Status/returned file MUST be reconciled with original RPS and
        # canonical lifecycle; never infer invoice authorization from OK200.
        return False


def _tag(parent: etree._Element, tag: str, value: str) -> etree._Element:
    child = etree.SubElement(parent, tag)
    child.text = value
    return child


def _build_soap(method: str, fields: tuple[tuple[str, str], ...]) -> tuple[bytes, str]:
    if method not in _METHODS:
        raise BarueriContractError("Unsupported Barueri SOAP operation")
    message = etree.Element(method)
    for name, value in fields:
        _tag(message, name, value)
    root = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soap": _SOAP})
    body = etree.SubElement(root, f"{{{_SOAP}}}Body")
    operation = etree.SubElement(body, f"{{{_NS}}}{method}")
    _tag(operation, f"{{{_NS}}}VersaoSchema", "1")
    # lxml escapes the inner XML safely: no CDATA injection possible.
    _tag(operation, f"{{{_NS}}}MensagemXML", etree.tostring(message, encoding="unicode"))
    return etree.tostring(root, encoding="utf-8", xml_declaration=True), f'"{_NS}/{method}"'


def _exchange(body: bytes, action: str, tls: ssl.SSLContext, timeout: float) -> bytes:
    request = Request(
        BARUERI_HOMOLOGATION_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": action,
            "Accept": "text/xml",
        },
    )
    try:
        opener = build_opener(HTTPSHandler(context=tls), RejectFiscalRedirects())
        with opener.open(request, timeout=timeout) as stream:
            result = stream.read(_LIMIT + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError):
        raise BarueriContractError(
            "Barueri mTLS indisponivel; consultar protocolo antes de retransmitir"
        ) from None
    if not isinstance(result, bytes) or not 0 < len(result) <= _LIMIT:
        raise BarueriContractError("Invalid bounded Barueri SOAP reply")
    return result


def _parse_reply(raw: bytes, method: str) -> BarueriReceipt:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
        raise BarueriContractError("Missing Barueri SOAP response")
    try:
        node = etree.fromstring(
            raw, parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        raise BarueriContractError("Invalid Barueri SOAP XML") from None
    if (
        node.tag != f"{{{_SOAP}}}Envelope"
        or bool(getattr(node.getroottree().docinfo, "doctype", ""))
    ):
        raise BarueriContractError("Barueri SOAP root mismatch")
    body = node.find(f"{{{_SOAP}}}Body")
    if body is None or body.find(f"{{{_SOAP}}}Fault") is not None:
        raise BarueriContractError("Barueri SOAP operation failed")
    result = body.find(f".//{{{_NS}}}{method}Result")
    if result is None:
        raise BarueriContractError("Barueri SOAP result mismatch")
    def official_text(name: str, *, required: bool = False) -> str | None:
        # The official ASMX example uses a DEFAULT municipal XML namespace
        # for its result and descendants; unqualified XML is never assumed.
        nodes = [
            element for element in result.iter()
            if element.tag == f"{{{_NS}}}{name}"
        ]
        if len(nodes) > 1 or (required and len(nodes) != 1):
            raise BarueriContractError("Ambiguous Barueri response field")
        if not nodes:
            return None
        value = nodes[0].text
        if value is not None and len(value) > 256:
            raise BarueriContractError("Barueri response field exceeds limit")
        return value

    code = official_text("Codigo", required=True)
    if code != "OK200":
        raise BarueriContractError("Barueri rejected the request (consult structured audit)")
    if method == "NFeLoteListarArquivos":
        records = result.findall(f".//{{{_NS}}}ListaNfeArquivosRPS")
        if len(records) > 500:
            raise BarueriContractError("Barueri file listing exceeded safe bound")
        listed: list[BarueriListedFile] = []
        for record in records:
            def one(
                name: str, *, required: bool = True, item: etree._Element = record,
            ) -> str | None:
                elements = item.findall(f"{{{_NS}}}{name}")
                if len(elements) > 1 or (required and len(elements) != 1):
                    raise BarueriContractError("Ambiguous Barueri listed file attribute")
                if not elements or not elements[0].text:
                    if required:
                        raise BarueriContractError("Missing Barueri listed file attribute")
                    return None
                value = elements[0].text.strip()
                if len(value) > 128:
                    raise BarueriContractError("Oversized Barueri listed file attribute")
                return value
            original = one("NomeArquivoOriginal", required=False)
            if original is None:
                original = one("NomeArquivoOrginal")
            remittance = one("CodigoRemessa")
            situation = one("SituacaoArq")
            validation = one("ApenasValidaArq")
            filename = one("NomeArqRetorno", required=False)
            if (
                not isinstance(original, str)
                or not isinstance(remittance, str)
                or not isinstance(situation, str)
                or validation not in ("true", "false", "0", "1")
            ):
                raise BarueriContractError("Incomplete Barueri remittance listing")
            listed.append(BarueriListedFile(
                original_file_name=original,
                remittance=remittance,
                situation=situation,
                return_file_name=filename,
                validation_only=validation in ("true", "1"),
            ))
        return BarueriReceipt(
            operation=method, code=code, listed_files=tuple(listed),
        )
    protocol = official_text("ProtocoloRemessa")
    situation = official_text("SituacaoArq")
    return_file = official_text("NomeArqRetorno")
    encoded = official_text("ArquivoRPSBase64")
    decoded: bytes | None = None
    if encoded:
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise BarueriContractError("Invalid Barueri return file Base64") from None
        if len(decoded) > _LIMIT:
            raise BarueriContractError("Barueri return file exceeds limit")
    return BarueriReceipt(
        operation=method,
        code=code,
        remittance_protocol=protocol[:128] if protocol else None,
        situation=situation[:32] if situation else None,
        return_file_name=return_file[:128] if return_file else None,
        downloaded_file=decoded,
    )


class BarueriPmb004HomologationTransport:
    """Mutations gated by exact durable provider, A1, scoped IBGE and XSD port."""

    def __init__(
        self,
        *,
        provider_resolver: ProviderSelectionResolver,
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        validate_pmb004: Callable[[bytes], None],
        exchange: Callable[[bytes, str, ssl.SSLContext, float], bytes] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        if (
            not callable(getattr(provider_resolver, "resolve_provider_id", None))
            or not callable(resolve_certificate)
            or not callable(validate_pmb004)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("Barueri requires canonical resolver, pinned PMB004 and A1")
        self._resolver = provider_resolver
        self._certificate = resolve_certificate
        self._validate = validate_pmb004
        self._exchange = exchange or _exchange
        self._timeout = timeout_seconds

    def _send(
        self, *,
        scope: ExecutionScope, cnpj: Cnpj, method: str,
        fields: tuple[tuple[str, str], ...], operation: str,
    ) -> BarueriReceipt:
        if scope.environment is not FiscalEnvironment.HOMOLOGATION or not scope.host_namespace:
            raise BarueriContractError("Barueri requires governed homologation scope")
        selected = self._resolver.resolve_provider_id(
            scope=scope,
            document_kind=FiscalDocumentKind.NFSE,
            jurisdiction=BrazilianJurisdiction("SP", BARUERI_IBGE),
            operation=operation,
        )
        if selected != BARUERI_PMB004_PROVIDER:
            raise BarueriContractError("Barueri durable provider binding mismatched")
        envelope, action = _build_soap(method, fields)
        material = self._certificate(scope, cnpj.value)
        validate_a1_for_issuer(
            material.pkcs12_bytes, material.password,
            issuer_cnpj=cnpj, at=datetime.now(UTC),
        )
        raw = self._exchange(
            envelope, action, build_fiscal_tls_context(material), self._timeout,
        )
        return _parse_reply(raw, method)

    def submit(self, batch: BarueriRpsBatch) -> BarueriReceipt:
        if not isinstance(batch, BarueriRpsBatch):
            raise BarueriContractError("Trusted PMB004 batch required")
        self._validate(batch.rps_bytes)
        return self._send(
            scope=batch.scope, cnpj=batch.issuer_cnpj,
            method="NFeLoteEnviarArquivo", operation="authorize",
            fields=(
                ("InscricaoMunicipal", batch.municipal_registration),
                ("CPFCNPJContrib", batch.issuer_cnpj.value),
                ("NomeArquivoRPS", batch.file_name),
                ("ApenasValidaArq", "false"),
                ("ArquivoRPSBase64", base64.b64encode(batch.rps_bytes).decode("ascii")),
            ),
        )

    def status(
        self, *, batch: BarueriRpsBatch, protocol: str,
    ) -> BarueriReceipt:
        if not isinstance(batch, BarueriRpsBatch) or not (
            isinstance(protocol, str) and 1 <= len(protocol) <= 128
            and protocol.isascii() and protocol.isalnum()
        ):
            raise BarueriContractError("Barueri status requires remittance protocol")
        return self._send(
            scope=batch.scope, cnpj=batch.issuer_cnpj,
            method="NFeLoteStatusArquivo", operation="query",
            fields=(
                ("InscricaoMunicipal", batch.municipal_registration),
                ("CPFCNPJContrib", batch.issuer_cnpj.value),
                ("ProtocoloRemessa", protocol),
            ),
        )

    def list_on_date(
        self, *, batch: BarueriRpsBatch, situation: str, submitted_on: date,
    ) -> BarueriReceipt:
        """Read-only duplicate detection after an ambiguous original POST.

        Official June/2021 WebService manual: list by submission date
        and five distinct queue states. No second RPS submission occurs.
        """
        if (
            not isinstance(batch, BarueriRpsBatch)
            or type(submitted_on) is not date
            or situation not in ("-2", "-1", "0", "1", "2")
        ):
            raise BarueriContractError("Invalid Barueri remittance listing filter")
        return self._send(
            scope=batch.scope, cnpj=batch.issuer_cnpj,
            method="NFeLoteListarArquivos", operation="query",
            fields=(
                ("InscricaoMunicipal", batch.municipal_registration),
                ("CPFCNPJContrib", batch.issuer_cnpj.value),
                # Submission date is NOT the service competence date.
                ("DataEnvioArq", submitted_on.isoformat()),
                ("SituacaoArq", situation),
            ),
        )

    def download(
        self, *, batch: BarueriRpsBatch, file_name: str,
    ) -> BarueriReceipt:
        if (
            not isinstance(batch, BarueriRpsBatch)
            or not isinstance(file_name, str)
            or not 1 <= len(file_name) <= 128
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                   for c in file_name)
        ):
            raise BarueriContractError("Invalid bounded return filename")
        return self._send(
            scope=batch.scope, cnpj=batch.issuer_cnpj,
            method="NFeLoteBaixarArquivo", operation="query",
            fields=(
                ("InscricaoMunicipal", batch.municipal_registration),
                ("CPFCNPJContrib", batch.issuer_cnpj.value),
                ("NomeArqRetorno", file_name),
            ),
        )
