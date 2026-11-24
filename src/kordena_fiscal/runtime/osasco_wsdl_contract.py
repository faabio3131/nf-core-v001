"""Hash-pinned official Osasco SOAP 1.1 WSDL: no network or inferred SOAPAction.

The operator provides a byte-for-byte official WSDL export and its reviewed
SHA-256 plus the binding name; execution NEVER downloads the contract. The
parsed binding is the single authority for the three municipal operations
used in the canonical NFS-e flow.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lxml import etree

from kordena_fiscal.domain import FiscalValidationError
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoWcfContract,
)

_WSDL = "http://schemas.xmlsoap.org/wsdl/"
_SOAP = "http://schemas.xmlsoap.org/wsdl/soap/"
_HTTP = "http://schemas.xmlsoap.org/soap/http"
_NAMESPACE = "http://tempuri.org/"
_METHODS = frozenset({"RTC_EmitirNFE", "ConsultarNotaCompleta", "Cancelar"})
_LIMIT = 2_097_152


class OsascoWsdlIntegrityError(FiscalValidationError):
    """The actual WSDL differs from the approved fiscal contract."""


@dataclass(frozen=True, slots=True)
class OsascoPinnedWcfWsdl:
    """Immutable, method-indexed actions derived from pinned official bytes."""

    sha256: str
    binding_name: str
    operations: Mapping[str, OsascoWcfContract]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or not all(c in "0123456789abcdef" for c in self.sha256)
            or not isinstance(self.binding_name, str)
            or not self.binding_name
            or set(self.operations) != _METHODS
        ):
            raise OsascoWsdlIntegrityError("Osasco WSDL contract is incomplete")
        object.__setattr__(
            self, "operations", MappingProxyType(dict(self.operations)),
        )

    def contract_for_method(self, method: str) -> OsascoWcfContract:
        if method not in self.operations:
            raise OsascoWsdlIntegrityError("Unverified Osasco operation requested")
        return self.operations[method]


def load_osasco_pinned_wsdl(
    *,
    document: bytes, expected_sha256: str, binding_name: str,
) -> OsascoPinnedWcfWsdl:
    """Verify binding and SOAPAction without guessing a WCF interface name."""
    if (
        not isinstance(document, bytes)
        or not 0 < len(document) <= _LIMIT
        or not isinstance(expected_sha256, str)
        or hashlib.sha256(document).hexdigest() != expected_sha256
        or not isinstance(binding_name, str)
        or not 1 <= len(binding_name) <= 128
    ):
        raise OsascoWsdlIntegrityError("Osasco approved WSDL hash or binding is missing")
    try:
        root = etree.fromstring(
            document,
            parser=etree.XMLParser(
                no_network=True, resolve_entities=False, load_dtd=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError:
        raise OsascoWsdlIntegrityError("Osasco WSDL is malformed") from None
    if (
        root.tag != f"{{{_WSDL}}}definitions"
        or root.get("targetNamespace") != _NAMESPACE
        or bool(getattr(root.getroottree().docinfo, "doctype", ""))
    ):
        raise OsascoWsdlIntegrityError("Osasco WSDL namespace/DTD is not approved")
    bindings = [
        x for x in root.findall(f"{{{_WSDL}}}binding")
        if x.get("name") == binding_name
    ]
    if len(bindings) != 1:
        raise OsascoWsdlIntegrityError("Osasco pinned WCF binding is missing or ambiguous")
    binding = bindings[0]
    binding_profiles = binding.findall(f"{{{_SOAP}}}binding")
    if (
        len(binding_profiles) != 1
        or binding_profiles[0].get("transport") != _HTTP
    ):
        raise OsascoWsdlIntegrityError("Only reviewed SOAP 1.1 HTTP binding is allowed")
    methods: dict[str, OsascoWcfContract] = {}
    for operation in binding.findall(f"{{{_WSDL}}}operation"):
        name = operation.get("name")
        if not isinstance(name, str) or name not in _METHODS:
            continue
        if name in methods:
            raise OsascoWsdlIntegrityError("Duplicate Osasco WCF operation")
        actions = operation.findall(f"{{{_SOAP}}}operation")
        if len(actions) != 1:
            raise OsascoWsdlIntegrityError("Missing unique Osasco WCF SOAPAction")
        action = actions[0].get("soapAction")
        if not isinstance(action, str):
            raise OsascoWsdlIntegrityError("Missing Osasco WCF SOAPAction")
        try:
            methods[name] = OsascoWcfContract(
                action=action, method=name, wsdl_sha256=expected_sha256,
            )
        except FiscalValidationError:
            raise OsascoWsdlIntegrityError("Invalid Osasco official SOAPAction") from None
    if set(methods) != _METHODS or len({
        x.action for x in methods.values()
    }) != len(_METHODS):
        raise OsascoWsdlIntegrityError(
            "Missing official WCF operation for emission/query/cancellation"
        )
    return OsascoPinnedWcfWsdl(
        sha256=expected_sha256, binding_name=binding_name, operations=methods,
    )
