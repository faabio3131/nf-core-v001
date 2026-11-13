"""Distinct municipal transports mapped into the governed SP4 canonical lifecycle.

Each bridge requires a trusted RPS/DPS builder and a source-identity validator;
it does not accept raw front-end XML. The municipality-specific interpreter
cannot confer final tax authority: Sp4MunicipalCanonicalGateway independently
checks original RPS, fiscal amount and signed official XML provenance.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol, TypeVar

from lxml import etree

from kordena_fiscal.domain import Cnpj, ExecutionScope, TaxRegimeCode
from kordena_fiscal.gateway.authorization import AuthorizationStatus
from kordena_fiscal.gateway.barueri_official_return_file import (
    BarueriConvertedNfseEvidence,
    parse_barueri_official_return_file,
)
from kordena_fiscal.gateway.barueri_pmb004_homologation import (
    BarueriPmb004HomologationTransport,
    BarueriReceipt,
    BarueriRpsBatch,
)
from kordena_fiscal.gateway.cajamar_geisweb_homologation import (
    CajamarGeiswebHomologationTransport,
    CajamarGeiswebResult,
    CajamarPreparedNfse,
)
from kordena_fiscal.gateway.cajamar_geisweb_invoice_interpreter import (
    interpret_cajamar_geisweb_result,
)
from kordena_fiscal.gateway.jundiai_giss_homologation import (
    JundiaiGissHomologationTransport,
    JundiaiGissReceipt,
    JundiaiSignedOperation,
)
from kordena_fiscal.gateway.jundiai_giss_invoice_interpreter import (
    interpret_jundiai_giss_result,
)
from kordena_fiscal.gateway.osasco_rtc_homologation import (
    OsascoOperationReceipt,
    OsascoPreparedOperation,
    OsascoRtcHomologationTransport,
)
from kordena_fiscal.gateway.osasco_rtc_request_builder import (
    build_osasco_original_note_query,
)
from kordena_fiscal.gateway.sp4_municipal_canonical import (
    Sp4CanonicalMunicipalError,
    Sp4OriginalRps,
    Sp4ProviderOutcome,
    Sp4VerifiedInvoice,
)
from kordena_fiscal.issuance.nfe_nfse import NfseAuthorizationRequest

from .sp4_municipal_canonical_composition import Sp4ReviewedMunicipalPorts


class _PreparedSp4Operation(Protocol):
    """Read-only contract for distinct signed, frozen municipal operation DTOs."""

    @property
    def scope(self) -> ExecutionScope: ...

    @property
    def issuer_cnpj(self) -> Cnpj: ...

    @property
    def tax_regime(self) -> TaxRegimeCode: ...

    @property
    def competence_date(self) -> date: ...

    @property
    def method(self) -> str: ...


P = TypeVar("P", bound=_PreparedSp4Operation)


@dataclass(frozen=True, slots=True)
class Sp4BridgeAuthority:
    """Canonical persisted RPS and legal checks, never extracted from a browser."""

    load_original_rps: Callable[[ExecutionScope, str], Sp4OriginalRps]
    fiscal_issuer_policy: Callable[[NfseAuthorizationRequest], None]
    validate_prepared_rps: Callable[[Sp4OriginalRps], None]
    verify_official_invoice_xml: Callable[[Sp4VerifiedInvoice], None]

    def wrap(
        self,
        submit: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps], Sp4ProviderOutcome
        ],
        query: Callable[
            [NfseAuthorizationRequest, Sp4OriginalRps], Sp4ProviderOutcome
        ],
    ) -> Sp4ReviewedMunicipalPorts:
        if not callable(submit) or not callable(query):
            raise Sp4CanonicalMunicipalError("SP4 municipal bridge operations required")
        return Sp4ReviewedMunicipalPorts(
            load_original_rps=self.load_original_rps,
            fiscal_issuer_policy=self.fiscal_issuer_policy,
            validate_prepared_rps=self.validate_prepared_rps,
            submit_official_rps=submit,
            query_official_rps=query,
            verify_official_invoice_xml=self.verify_official_invoice_xml,
        )


def _validate_prepared_link(
    request: NfseAuthorizationRequest,
    original: Sp4OriginalRps,
    prepared: P,
    *,
    expected_type: type[P],
    expected_method: str,
) -> P:
    """No document, tenant, issuer, tax period or operation substitution."""
    if type(prepared) is not expected_type or (
        prepared.scope.identity_partition_key
        != request.document.scope.identity_partition_key
        or prepared.issuer_cnpj != original.issuer_cnpj
        or prepared.tax_regime != request.document.issuer.tax_regime
        or prepared.competence_date != original.competence_date
        or prepared.method != expected_method
    ):
        raise Sp4CanonicalMunicipalError("Prepared municipal operation conflicts with original RPS")
    return prepared


def _verified_outcome(value: object) -> Sp4ProviderOutcome:
    if not isinstance(value, Sp4ProviderOutcome):
        raise Sp4CanonicalMunicipalError(
            "Municipal official interpreter did not return a reviewed fiscal result"
        )
    return value


def build_cajamar_reviewed_ports(
    *, authority: Sp4BridgeAuthority,
    transport: CajamarGeiswebHomologationTransport,
    build_signed_operation: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, str], CajamarPreparedNfse
    ],
    verify_signed_rps_identity: Callable[[Sp4OriginalRps, bytes], None],
    interpret_official_result: Callable[
        [CajamarGeiswebResult, NfseAuthorizationRequest, Sp4OriginalRps],
        Sp4ProviderOutcome,
    ] = interpret_cajamar_geisweb_result,
) -> Sp4ReviewedMunicipalPorts:
    if not isinstance(transport, CajamarGeiswebHomologationTransport) or not all(
        callable(x) for x in (
            build_signed_operation, verify_signed_rps_identity,
            interpret_official_result,
        )
    ):
        raise Sp4CanonicalMunicipalError("Cajamar official contract adapters unavailable")

    def invoke(
        req: NfseAuthorizationRequest, original: Sp4OriginalRps, method: str,
    ) -> Sp4ProviderOutcome:
        # GeisWeb20 accepts one service per RPS and one invoice per lot.
        # Reject incompatible canonical documents before opening Vault/HTTP.
        if (
            len(req.document.services) != 1
            or not original.rps_number.isascii()
            or not original.rps_number.isdecimal()
            or not 1 <= len(original.rps_number) <= 8
            or int(original.rps_number) < 1
        ):
            raise Sp4CanonicalMunicipalError(
                "Cajamar GeisWeb requires one service and 1-8 digit original RPS"
            )
        operation = _validate_prepared_link(
            req, original, build_signed_operation(req, original, method),
            expected_type=CajamarPreparedNfse, expected_method=method,
        )
        # GeisWeb ConsultaLoteRps is keyed by NumeroLote (10 chars),
        # NOT the invoice number. Without a durable lot ID a lost POST
        # cannot be reconciled and must not be retransmitted.
        if (
            original.municipal_batch_id is None
            or len(original.municipal_batch_id) > 10
        ):
            raise Sp4CanonicalMunicipalError(
                "Cajamar requires persisted original GeisWeb lot ID"
            )
        try:
            root = etree.fromstring(
                operation.signed_request_xml,
                parser=etree.XMLParser(
                    no_network=True, resolve_entities=False, load_dtd=False,
                ),
            )
        except etree.XMLSyntaxError:
            raise Sp4CanonicalMunicipalError("Cajamar signed lot XML malformed") from None
        lots = [
            child for child in root.iter()
            if etree.QName(child).localname == "NumeroLote"
        ]
        if (
            etree.QName(root).localname != method
            or bool(getattr(root.getroottree().docinfo, "doctype", ""))
            or len(lots) != 1
            or (lots[0].text or "").strip() != original.municipal_batch_id
        ):
            raise Sp4CanonicalMunicipalError(
                "Cajamar lot XML differs from persisted original batch"
            )
        verify_signed_rps_identity(original, operation.signed_request_xml)
        receipt = transport.invoke(operation)
        return _verified_outcome(interpret_official_result(receipt, req, original))

    return authority.wrap(
        lambda req, original: invoke(req, original, "EnviaLoteRps"),
        # A pending issuance has a durable original LOT/RPS, not yet an
        # NFS-e number. ConsultaNfse requires an already assigned invoice
        # identifier and cannot reconcile an ambiguous emission POST.
        lambda req, original: invoke(req, original, "ConsultaLoteRps"),
    )


def build_osasco_reviewed_ports(
    *, authority: Sp4BridgeAuthority,
    transport: OsascoRtcHomologationTransport,
    build_wcf_operation: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, str], OsascoPreparedOperation
    ],
    verify_wcf_rps_identity: Callable[[Sp4OriginalRps, bytes], None],
    interpret_official_result: Callable[
        [OsascoOperationReceipt, NfseAuthorizationRequest, Sp4OriginalRps],
        Sp4ProviderOutcome,
    ],
) -> Sp4ReviewedMunicipalPorts:
    if not isinstance(transport, OsascoRtcHomologationTransport) or not all(
        callable(x) for x in (
            build_wcf_operation, verify_wcf_rps_identity,
            interpret_official_result,
        )
    ):
        raise Sp4CanonicalMunicipalError("Osasco RTC provider adapter incomplete")

    def invoke(
        req: NfseAuthorizationRequest, original: Sp4OriginalRps, method: str,
    ) -> Sp4ProviderOutcome:
        prepared = (
            build_osasco_original_note_query(
                original=original, regime=req.document.issuer.tax_regime,
            ) if method == "ConsultarNotaCompleta"
            else build_wcf_operation(req, original, method)
        )
        operation = _validate_prepared_link(
            req, original, prepared,
            expected_type=OsascoPreparedOperation, expected_method=method,
        )
        # The April 2026 municipal v2.1 manual includes RTC_ConsultarNFE
        # and ConsultarNotaCompleta. The latter retrieves complete invoice
        # XML by the original NumeroReciboUnico without a second issuance.
        if (
            not original.rps_number.isascii()
            or not original.rps_number.isdecimal()
            or not 1 <= len(original.rps_number) <= 20
        ):
            raise Sp4CanonicalMunicipalError("Osasco original receipt number invalid")
        field_name = (
            "NumeroRecibo" if method == "RTC_EmitirNFE"
            else "NumeroReciboUnico"
        )
        namespace = (
            "http://schemas.datacontract.org/2004/07/"
            + "Eissnfe.Dominio.DataTransferObject.Prestador"
            if method == "RTC_EmitirNFE"
            else "http://schemas.datacontract.org/2004/07/"
            + "Eissnfe.Negocio.WebServices.Mensagem"
        )
        try:
            root = etree.fromstring(
                operation.request_xml,
                parser=etree.XMLParser(
                    no_network=True, resolve_entities=False, load_dtd=False,
                ),
            )
        except etree.XMLSyntaxError:
            raise Sp4CanonicalMunicipalError("Osasco fiscal request is malformed") from None
        found = root.findall(f".//{{{namespace}}}{field_name}")
        if (
            len(found) != 1
            or not found[0].text
            or not found[0].text.isascii()
            or not found[0].text.isdecimal()
            or int(found[0].text) != int(original.rps_number)
            or bool(getattr(root.getroottree().docinfo, "doctype", ""))
        ):
            raise Sp4CanonicalMunicipalError(
                "Osasco requested receipt differs from durable original RPS"
            )
        verify_wcf_rps_identity(original, operation.request_xml)
        receipt = transport.invoke(operation)
        if not isinstance(receipt, OsascoOperationReceipt) or receipt.method != method:
            raise Sp4CanonicalMunicipalError(
                "Osasco returned an unexpected official operation"
            )
        if method == "RTC_EmitirNFE":
            # Even a synchronous NotaFiscalGerada with Erro=false is only a
            # provider reference until read-only ConsultarNotaCompleta
            # reconciles the original receipt and official invoice XML.
            return Sp4ProviderOutcome(
                status=AuthorizationStatus.PENDING,
                provider_request_id=(
                    receipt.note_reference.number
                    if receipt.note_reference is not None else None
                ),
            )
        if not receipt.response_xml or receipt.fiscal_error:
            return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
        return _verified_outcome(interpret_official_result(receipt, req, original))

    return authority.wrap(
        lambda req, original: invoke(req, original, "RTC_EmitirNFE"),
        lambda req, original: invoke(req, original, "ConsultarNotaCompleta"),
    )


def build_jundiai_reviewed_ports(
    *, authority: Sp4BridgeAuthority,
    transport: JundiaiGissHomologationTransport,
    build_signed_operation: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps, str], JundiaiSignedOperation
    ],
    verify_signed_rps_identity: Callable[[Sp4OriginalRps, bytes], None],
    interpret_official_result: Callable[
        [JundiaiGissReceipt, NfseAuthorizationRequest, Sp4OriginalRps],
        Sp4ProviderOutcome,
    ] = interpret_jundiai_giss_result,
) -> Sp4ReviewedMunicipalPorts:
    if not isinstance(transport, JundiaiGissHomologationTransport) or not all(
        callable(x) for x in (
            build_signed_operation, verify_signed_rps_identity,
            interpret_official_result,
        )
    ):
        raise Sp4CanonicalMunicipalError("Jundiai Giss provider adapter incomplete")

    def invoke(
        req: NfseAuthorizationRequest, original: Sp4OriginalRps, method: str,
    ) -> Sp4ProviderOutcome:
        operation = _validate_prepared_link(
            req, original, build_signed_operation(req, original, method),
            expected_type=JundiaiSignedOperation, expected_method=method,
        )
        try:
            root = etree.fromstring(
                operation.signed_xml,
                parser=etree.XMLParser(
                    no_network=True, resolve_entities=False, load_dtd=False,
                ),
            )
        except etree.XMLSyntaxError:
            raise Sp4CanonicalMunicipalError("Giss 2.04 prepared XML malformed") from None
        expected_root = (
            "EnviarLoteRpsEnvio" if method == "RecepcionarLoteRps"
            else "ConsultarNfseRpsEnvio"
        )
        ns = "{http://www.giss.com.br/tipos-v2_04.xsd}"
        # The lot's nested Rps/IdentificacaoRps is a complex *type*.
        # The direct query-level IdentificacaoRps is in the REQUEST namespace.
        identifier_ns = (
            ns if method == "RecepcionarLoteRps"
            else "{http://www.giss.com.br/consultar-nfse-rps-envio-v2_04.xsd}"
        )
        rps_numbers = root.findall(f".//{identifier_ns}IdentificacaoRps/{ns}Numero")
        rps_series = root.findall(f".//{identifier_ns}IdentificacaoRps/{ns}Serie")
        if (
            etree.QName(root).localname != expected_root
            or bool(getattr(root.getroottree().docinfo, "doctype", ""))
            or len(rps_numbers) != 1
            or len(rps_series) != 1
            or (rps_numbers[0].text or "").strip() != original.rps_number
            or (rps_series[0].text or "").strip() != original.rps_series
        ):
            raise Sp4CanonicalMunicipalError(
                "Jundiai signed Giss document differs from persisted original RPS"
            )
        if method == "RecepcionarLoteRps":
            lot = [
                child for child in root.iter()
                if etree.QName(child).localname == "NumeroLote"
            ]
            if (
                original.municipal_batch_id is None
                or len(original.municipal_batch_id) > 15
                or len(lot) != 1
                or (lot[0].text or "").strip() != original.municipal_batch_id
            ):
                raise Sp4CanonicalMunicipalError(
                    "Jundiai signed Giss batch differs from original persisted lot"
                )
        verify_signed_rps_identity(original, operation.signed_xml)
        receipt = transport.invoke(operation)
        return _verified_outcome(interpret_official_result(receipt, req, original))

    return authority.wrap(
        lambda req, original: invoke(req, original, "RecepcionarLoteRps"),
        lambda req, original: invoke(req, original, "ConsultarNfsePorRps"),
    )


def _validated_barueri_export(
    batch: BarueriRpsBatch, receipt: BarueriReceipt,
) -> BarueriConvertedNfseEvidence:
    """Current v3 municipal export schema per official January/2026 guide."""
    return parse_barueri_official_return_file(batch=batch, receipt=receipt)


def build_barueri_reviewed_ports(
    *, authority: Sp4BridgeAuthority,
    transport: BarueriPmb004HomologationTransport,
    build_remittance: Callable[
        [NfseAuthorizationRequest, Sp4OriginalRps], BarueriRpsBatch
    ],
    verify_fixed_width_rps_identity: Callable[[Sp4OriginalRps, BarueriRpsBatch], None],
    load_approved_remittance_protocol: Callable[[ExecutionScope, str], str | None],
    interpret_official_result: Callable[
        [BarueriReceipt, NfseAuthorizationRequest, Sp4OriginalRps],
        Sp4ProviderOutcome,
    ],
    validate_return_file: Callable[
        [BarueriRpsBatch, BarueriReceipt], BarueriConvertedNfseEvidence
    ] = _validated_barueri_export,
    retrieve_official_invoice_xml: Callable[
        [BarueriConvertedNfseEvidence], bytes
    ] | None = None,
    load_original_submission_date: Callable[
        [ExecutionScope, str], date | None
    ] | None = None,
) -> Sp4ReviewedMunicipalPorts:
    if not isinstance(transport, BarueriPmb004HomologationTransport) or not all(
        callable(x) for x in (
            build_remittance, verify_fixed_width_rps_identity,
            load_approved_remittance_protocol, interpret_official_result,
            validate_return_file,
        )
    ):
        raise Sp4CanonicalMunicipalError("Barueri PMB004 provider adapter incomplete")

    def original_batch(
        req: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> BarueriRpsBatch:
        batch = build_remittance(req, original)
        if not isinstance(batch, BarueriRpsBatch) or (
            batch.scope.identity_partition_key
            != req.document.scope.identity_partition_key
            or batch.issuer_cnpj != original.issuer_cnpj
            or batch.tax_regime != req.document.issuer.tax_regime
            or batch.competence_date != original.competence_date
            or original.municipal_batch_id is None
            or batch.remittance != original.municipal_batch_id
        ):
            raise Sp4CanonicalMunicipalError("Barueri remittance conflicts with canonical RPS")
        # The PMB004 type-2 action flag is fiscal authority, not a
        # cosmetic field. Emission routes may not carry cancellation ("C")
        # or replacement ("R") records without human-approved event flow.
        fiscal_details = [
            line for line in batch.rps_bytes.split(b"\r\n")
            if line.startswith(b"2")
        ]
        if len(fiscal_details) != 1 or fiscal_details[0][39:40] != b"E":
            raise Sp4CanonicalMunicipalError(
                "Barueri issuance must not submit cancellation or substitution"
            )
        verify_fixed_width_rps_identity(original, batch)
        return batch

    def authorize(
        req: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        batch = original_batch(req, original)
        receipt = transport.submit(batch)
        if (
            not isinstance(receipt, BarueriReceipt)
            or receipt.operation != "NFeLoteEnviarArquivo"
            or receipt.code != "OK200"
        ):
            raise Sp4CanonicalMunicipalError("Barueri returned unverified remittance receipt")
        # Barueri PMB004 is asynchronous. Its initial OK200 can NEVER
        # authorize a note, even if a caller supplies a faulty interpreter.
        if not receipt.remittance_protocol:
            raise Sp4CanonicalMunicipalError(
                "Barueri did not provide a recoverable remittance protocol"
            )
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.PENDING,
            provider_request_id=receipt.remittance_protocol,
        )

    def query(
        req: NfseAuthorizationRequest, original: Sp4OriginalRps,
    ) -> Sp4ProviderOutcome:
        batch = original_batch(req, original)
        protocol = load_approved_remittance_protocol(
            req.document.scope, req.document.document_id,
        )
        return_name: str | None = None
        if protocol is None:
            # No POST protocol can mean a network timeout AFTER the municipality
            # received the original file. Search by immutable original remittance
            # AND the separate, durable transmission date before any retransmit.
            if load_original_submission_date is None:
                return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
            submitted_on = load_original_submission_date(
                req.document.scope, req.document.document_id,
            )
            if submitted_on is None:
                return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
            if type(submitted_on) is not date:
                raise Sp4CanonicalMunicipalError(
                    "Barueri original submission date is untrusted"
                )
            matches = []
            for state in ("-2", "-1", "0", "1", "2"):
                listing = transport.list_on_date(
                    batch=batch, situation=state, submitted_on=submitted_on,
                )
                if (
                    not isinstance(listing, BarueriReceipt)
                    or listing.operation != "NFeLoteListarArquivos"
                    or listing.code != "OK200"
                ):
                    raise Sp4CanonicalMunicipalError(
                        "Barueri official remittance listing is invalid"
                    )
                for entry in listing.listed_files:
                    if entry.original_file_name != batch.file_name:
                        continue
                    if (
                        entry.remittance != original.municipal_batch_id
                        or entry.situation != state
                        or entry.validation_only
                    ):
                        raise Sp4CanonicalMunicipalError(
                            "Ambiguous duplicate or validation-only Barueri remittance"
                        )
                    matches.append(entry)
            if len(matches) > 1:
                raise Sp4CanonicalMunicipalError(
                    "Duplicate Barueri original RPS transmissions detected"
                )
            if not matches or matches[0].situation != "1":
                return Sp4ProviderOutcome(status=AuthorizationStatus.PENDING)
            return_name = matches[0].return_file_name
        else:
            if (
                not isinstance(protocol, str)
                or not 1 <= len(protocol) <= 128
                or not protocol.isascii()
                or not protocol.isalnum()
            ):
                raise Sp4CanonicalMunicipalError("Invalid original Barueri protocol")
            status = transport.status(batch=batch, protocol=protocol)
            if (
                not isinstance(status, BarueriReceipt)
                or status.operation != "NFeLoteStatusArquivo"
                or status.code != "OK200"
                or status.remittance_protocol not in (None, protocol)
            ):
                raise Sp4CanonicalMunicipalError(
                    "Barueri status does not match original remittance"
                )
            return_name = status.return_file_name
        if not return_name:
            return Sp4ProviderOutcome(
                status=AuthorizationStatus.PENDING,
                provider_request_id=protocol,
            )
        # Only a source-matched final return can lead to invoice XML.
        receipt = transport.download(batch=batch, file_name=return_name)
        if (
            not isinstance(receipt, BarueriReceipt)
            or receipt.operation != "NFeLoteBaixarArquivo"
            or receipt.code != "OK200"
            or not receipt.downloaded_file
            or receipt.return_file_name not in (None, return_name)
            or (
                protocol is not None
                and receipt.remittance_protocol not in (None, protocol)
            )
        ):
            raise Sp4CanonicalMunicipalError(
                "Barueri downloaded return file cannot be correlated"
            )
        # Municipal January/2026 guide v1.07 explicitly names official
        # NFE_Layout-v3.pdf (Aug/2025) as the CURRENT return layout, even
        # for January/2026 input PMB004 v4.2. This is not RPS error list v5.5.
        evidence = validate_return_file(batch, receipt)
        if (
            not isinstance(evidence, BarueriConvertedNfseEvidence)
            or int(evidence.rps_number) != int(original.rps_number)
            or evidence.rps_series != original.rps_series
            or evidence.service_total != original.gross_amount
            or evidence.remittance != batch.remittance
            or evidence.return_file != receipt.downloaded_file
        ):
            raise Sp4CanonicalMunicipalError(
                "Barueri official return does not prove original RPS"
            )
        # TXT is never a fiscal XML. The original municipal XML must be
        # downloaded independently using the authenticated NFS-e identifiers.
        # A missing or unprovisioned XML channel remains PENDING and must
        # never synthesize or authorize a document from the TXT export.
        if retrieve_official_invoice_xml is None:
            return Sp4ProviderOutcome(
                status=AuthorizationStatus.PENDING,
                provider_request_id=protocol,
            )
        raw = retrieve_official_invoice_xml(evidence)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 2_097_152:
            raise Sp4CanonicalMunicipalError(
                "Barueri original official NFS-e XML is missing"
            )
        # This is only a candidate. The canonical gateway must independently
        # validate the real municipal/ADN XSD, signature and all identifiers,
        # including the 50-digit access key, against this same XML.
        candidate = Sp4VerifiedInvoice(
            issuer_cnpj=original.issuer_cnpj,
            issuer_ibge=original.issuer_ibge,
            competence_date=original.competence_date,
            rps_number=original.rps_number,
            rps_series=original.rps_series,
            gross_amount=evidence.service_total,
            invoice_number=evidence.note_number,
            verification_code=evidence.verification_code,
            invoice_reference=evidence.access_key,
            authorized_xml=raw,
        )
        return Sp4ProviderOutcome(
            status=AuthorizationStatus.AUTHORIZED,
            provider_request_id=protocol,
            official_invoice=candidate,
        )

    return authority.wrap(authorize, query)
