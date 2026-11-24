"""Read-only municipal XML retrieval for Barueri NFS-e return evidence.

Official source: Prefeitura de Barueri Guia para Conversao RPS em Lote
v1.07 (Jan/2026), section 6.1, direct XML URL:
https://testeeiss.barueri.sp.gov.br/nfe/xmlNFe.ashx?
    codigoautenticidade=<COD>&numdoc=<DOC>

This endpoint is not a fiscal authorization service. The returned bytes
must subsequently pass a separately pinned official XSD/provenance verifier,
with issuer, RPS and monetary cross-checks before entering the ledger.
"""
from __future__ import annotations

import ssl
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriConvertedNfseEvidence,
)
from kordena_fiscal.gateway.fiscal_tls import RejectFiscalRedirects

_HOMOLOG = "https://testeeiss.barueri.sp.gov.br/nfe/xmlNFe.ashx"
_LIMIT = 2_097_152


class BarueriOfficialXmlError(FiscalValidationError):
    """Sanitized failure; never disclose taxpayer access or xml contents."""


def _exchange(url: str, timeout: float) -> bytes:
    try:
        req = Request(url, method="GET", headers={"Accept": "application/xml, text/xml"})
        opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context()),
            RejectFiscalRedirects(),
        )
        with opener.open(req, timeout=timeout) as stream:
            raw = stream.read(_LIMIT + 1)
    except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError):
        raise BarueriOfficialXmlError(
            "Municipal original XML unavailable; preserve pending NFS-e"
        ) from None
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
        raise BarueriOfficialXmlError("Municipal original XML length invalid")
    return raw


def retrieve_barueri_original_invoice_xml(
    *,
    evidence: BarueriConvertedNfseEvidence,
    exchange: Callable[[str, float], bytes] | None = None,
    timeout_seconds: float = 15,
) -> bytes:
    """Fetch one original municipal invoice without redirect or arbitrary host."""
    if not isinstance(evidence, BarueriConvertedNfseEvidence):
        raise BarueriOfficialXmlError("Source-correlated Barueri invoice required")
    if not 0 < timeout_seconds <= 30:
        raise BarueriOfficialXmlError("Invalid bounded municipal XML timeout")
    if (
        not evidence.verification_code.isascii()
        or not evidence.verification_code.isalnum()
        or not 1 <= len(evidence.verification_code) <= 24
        or not evidence.note_number.isascii()
        or not evidence.note_number.isdecimal()
        or not 1 <= len(evidence.note_number) <= 7
    ):
        raise BarueriOfficialXmlError("Untrusted municipal invoice retrieval identity")
    params = urlencode({
        "codigoautenticidade": evidence.verification_code,
        "numdoc": evidence.note_number,
    })
    url = _HOMOLOG + "?" + params
    raw = (exchange or _exchange)(url, timeout_seconds)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _LIMIT:
        raise BarueriOfficialXmlError("Invalid bounded municipal XML")
    try:
        root = etree.fromstring(
            raw, parser=etree.XMLParser(
                no_network=True, load_dtd=False, resolve_entities=False, huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise BarueriOfficialXmlError("Municipal retrieval is not valid XML") from None
    if (
        bool(getattr(root.getroottree().docinfo, "doctype", ""))
        or etree.QName(root).localname.lower() in ("html", "error", "fault")
    ):
        raise BarueriOfficialXmlError("No verified original municipal invoice XML")
    return raw
