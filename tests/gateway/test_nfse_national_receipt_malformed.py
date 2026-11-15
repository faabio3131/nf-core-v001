"""Defensive regression: an invalid National NFSe response must not escape as HTTP 500.

These are adversarial provider-response bytes, not simulated approvals,
and no network, certificate, fiscal operation or production endpoint is used.
"""
from __future__ import annotations

import base64
import gzip
import json

import pytest

from kordena_fiscal.gateway.nfse_national_homologation import (
    OfficialNfseTransportError,
    parse_nfse_homologation_response,
)
from kordena_fiscal.gateway.nfse_national_query import _validate_official_nfse
from kordena_fiscal.gateway.nfse_national_receipt import (
    NfseReceiptVerificationError,
    validate_official_nfse_receipt,
)

_KEY = "35" + "0" * 48


def _envelope(gzip_bytes: bytes) -> bytes:
    return json.dumps(
        {
            "chaveAcesso": _KEY,
            "nfseXmlGZipB64": base64.b64encode(gzip_bytes).decode("ascii"),
        }
    ).encode("utf-8")


_GZIP = gzip.compress(b"<untrusted/>", mtime=0)
_CORRUPT_DEFLATE = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03" + b"\xff" * 40
_DEEP_JSON = b"[" * 10_000 + b"]" * 10_000


@pytest.mark.parametrize(
    "untrusted_response",
    [
        b"\xff",  # invalid JSON UTF-8
        b"\xef\xbb\xbf\xff",  # malformed BOM/UTF-8
        _DEEP_JSON,  # recursive JSON nesting must not escape as HTTP 500
        _envelope(_GZIP[:-8]),  # truncated trailer, raises EOFError in gzip
        _envelope(_GZIP[:12]),  # truncated payload
        _envelope(_CORRUPT_DEFLATE),  # invalid deflate, raises zlib.error
    ],
)
def test_common_receipt_verifier_sanitizes_malformed_provider_bytes(
    untrusted_response: bytes,
) -> None:
    with pytest.raises(
        NfseReceiptVerificationError, match="Invalid signed national NFS-e receipt"
    ):
        validate_official_nfse_receipt(untrusted_response, _KEY)


@pytest.mark.parametrize(
    "untrusted_response",
    [_DEEP_JSON, _envelope(_GZIP[:-8]), _envelope(_GZIP[:12]), _envelope(_CORRUPT_DEFLATE)],
)
def test_direct_post_never_authorizes_corrupt_gzip(untrusted_response: bytes) -> None:
    with pytest.raises(
        OfficialNfseTransportError, match="XML retornado pela NFS-e Nacional é inválido"
    ):
        parse_nfse_homologation_response(untrusted_response)


@pytest.mark.parametrize(
    "untrusted_response",
    [
        b"\xff",
        _DEEP_JSON,
        _envelope(_GZIP[:-8]),
        _envelope(_GZIP[:12]),
        _envelope(_CORRUPT_DEFLATE),
    ],
)
def test_recovery_get_never_exposes_transport_exception(
    untrusted_response: bytes,
) -> None:
    with pytest.raises(OfficialNfseTransportError):
        _validate_official_nfse(untrusted_response, _KEY)
