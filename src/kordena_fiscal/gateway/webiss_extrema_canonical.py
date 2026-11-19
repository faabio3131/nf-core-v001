"""Canonical durable NFS-e authorization and read-only recovery for Extrema.

The single source of truth is FiscalApplicationService. This adapter consumes
its immutable archived RPS intent, never untrusted raw XML; returns normalized
outcomes, never writes fiscal state and never automatically retries an HTTP POST.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from lxml import etree

from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalValidationError,
)
from kordena_fiscal.gateway.authorization import AuthorizationStatus, GatewayProviderMetadata
from kordena_fiscal.gateway.mg_webiss_soap import (
    EXTREMA_IBGE,
    WebissExtremaHomologationTransport,
    WebissMgContractError,
)
from kordena_fiscal.gateway.nfse_abrasf203_envelope import (
    Abrasf203Envelope,
    Abrasf203Operation,
    AbrasfCancellationFacts,
    AbrasfServiceFacts,
    prepare_abrasf203_soap,
)
from kordena_fiscal.issuance.nfe_nfse import (
    NfseAuthorizationRequest,
    NfseAuthorizationResult,
)
from kordena_fiscal.issuance.webiss_extrema_builder import (
    ExtremaRpsIntent,
    build_extrema_rps_xml,
    validate_extrema_intent,
)
from kordena_fiscal.vault import EphemeralCertificateMaterial
from kordena_fiscal.xml.schema import XmlSchemaValidator

_NS = "{http://www.abrasf.org.br/nfse.xsd}"
_PROVIDER = GatewayProviderMetadata(
    provider_name="webiss-extrema-mg-homologation",
    adapter_version="extrema-rtc-2.02-v1",
)


def _response_messages(xml: etree._Element) -> tuple[str, str] | None:
    messages = xml.findall(f".//{_NS}ListaMensagemRetorno/{_NS}MensagemRetorno")
    if not messages:
        return None
    first = messages[0]
    code = first.findtext(f"{_NS}Codigo", "")
    message = first.findtext(f"{_NS}Mensagem", "")
    if not code or not message or len(code) > 64:
        raise WebissMgContractError("Extrema returned incomplete official rejection")
    return code[:64], message[:512]


def _invoice_reference(
    xml: etree._Element, request: NfseAuthorizationRequest,
    intent: ExtremaRpsIntent,
) -> tuple[str, str, str] | None:
    if xml.tag == f"{_NS}SubstituirNfseResposta":
        # The official substitution receipt contains BOTH old and new notes.
        # Only the replacement invoice may be the new fiscal authority.
        invoices = xml.findall(
            f"{_NS}RetSubstituicao/{_NS}NfseSubstituidora/"
            f"{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse"
        )
    else:
        invoices = xml.findall(
            f".//{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse"
        )
    if not invoices:
        return None
    if len(invoices) != 1:
        raise WebissMgContractError("Ambiguous municipal NFS-e response")
    invoice = invoices[0]
    invoice_number = invoice.findtext(f"{_NS}Numero", "")
    code = invoice.findtext(f"{_NS}CodigoVerificacao", "")
    access_key = invoice.findtext(f"{_NS}ChaveAcesso", "")
    legal_issuer = invoice.findtext(
        f"{_NS}PrestadorServico/{_NS}IdentificacaoPrestador/"
        f"{_NS}CpfCnpj/{_NS}Cnpj", "",
    )
    issuing_city = invoice.findtext(f"{_NS}OrgaoGerador/{_NS}CodigoMunicipio", "")
    source = invoice.find(
        f"{_NS}DeclaracaoPrestacaoServico/"
        f"{_NS}InfDeclaracaoPrestacaoServico"
    )
    if source is None:
        raise WebissMgContractError("Municipal invoice has no original RPS declaration")
    ident = source.find(f"{_NS}Rps/{_NS}IdentificacaoRps")
    if ident is None:
        raise WebissMgContractError("Municipal invoice has no RPS correlation")
    facts = (
        ident.findtext(f"{_NS}Numero", ""),
        ident.findtext(f"{_NS}Serie", ""),
        ident.findtext(f"{_NS}Tipo", ""),
    )
    service = source.find(f"{_NS}Servico")
    if service is None:
        raise WebissMgContractError("Municipal invoice has no trusted service")
    billed_amount = service.findtext(f"{_NS}Valores/{_NS}ValorServicos", "")
    issuer_cnpj = source.findtext(f"{_NS}Prestador/{_NS}CpfCnpj/{_NS}Cnpj", "")
    competence = source.findtext(f"{_NS}Competencia", "")
    taker = source.findtext(
        f"{_NS}Tomador/{_NS}IdentificacaoTomador/"
        f"{_NS}CpfCnpj/{_NS}Cnpj", "",
    )
    line = request.document.services[0]
    if (
        not invoice_number.isdecimal()
        or not code
        or not access_key
        or legal_issuer != intent.issuer_cnpj.value
        or issuer_cnpj != intent.issuer_cnpj.value
        or issuing_city != EXTREMA_IBGE
        or facts != (
            str(intent.reservation.number), str(intent.reservation.key.series), "1",
        )
        or competence != request.document.competence_date.isoformat()
        or billed_amount != f"{line.gross_amount.amount:.2f}"
        or taker != intent.taker.cnpj.value
    ):
        raise WebissMgContractError(
            "NFS-e received from WebISS differs from original durable fiscal intention"
        )
    # An official invoice must carry both verification code and access key.
    # Those are external identifiers, not locally invented IDs.
    return access_key, code, invoice_number


@dataclass(frozen=True, slots=True)
class ExtremaCancellationOutcome:
    """Normalized provider event response; no local lifecycle authority."""

    confirmed: bool
    xml: bytes
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.xml, bytes) or not self.xml:
            raise FiscalValidationError("Extrema cancellation requires schema-verified response")
        if self.confirmed and self.rejection_code is not None:
            raise FiscalValidationError("Confirmed cancellation cannot also be rejected")
        if not self.confirmed and not self.rejection_code:
            raise FiscalValidationError("Cancellation rejection must identify an official code")


@dataclass(frozen=True, slots=True)
class ExtremaSubstitutionOutcome:
    """Official atomic replacement result, not a simulated fiscal event."""

    confirmed: bool
    xml: bytes
    invoice_reference: str | None = None
    verification_code: str | None = None
    invoice_number: str | None = None
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.xml, bytes) or not self.xml:
            raise FiscalValidationError("Extrema substitution response is required")
        if self.confirmed:
            if not self.invoice_reference or not self.verification_code or not self.invoice_number:
                raise FiscalValidationError("Confirmed replacement requires original fiscal proofs")
            if self.rejection_code is not None:
                raise FiscalValidationError("Replacement cannot be accepted and rejected")
        elif not self.rejection_code or any((
            self.invoice_reference, self.verification_code, self.invoice_number,
        )):
            raise FiscalValidationError("Rejected replacement cannot carry invoice authority")


class WebissExtremaCanonicalNfseGateway:
    """NfseGateway + NfseQueryGateway through the existing durable state machine.

    A 2.02 RTC document is only authorized when the provider returns one
    source-correlated, schema-valid CompNfse in a certified SOAP exchange.
    An uncertain POST is left TRANSMITTING by the application, and query()
    uses ConsultarNfsePorRps without making a second emission request.
    """

    def __init__(
        self, *,
        transport: WebissExtremaHomologationTransport,
        load_intent: Callable[[ExecutionScope, str], ExtremaRpsIntent],
        resolve_certificate: Callable[[ExecutionScope, str], EphemeralCertificateMaterial],
        canonical_preaudit: Callable[[NfseAuthorizationRequest], None],
        service_preaudit: Callable[[tuple[AbrasfServiceFacts, ...]], None],
        cancellation_preaudit: Callable[[AbrasfCancellationFacts], None] | None = None,
        municipal_validator: XmlSchemaValidator,
    ) -> None:
        if (
            not isinstance(transport, WebissExtremaHomologationTransport)
            or not callable(load_intent)
            or not callable(resolve_certificate)
            or not callable(canonical_preaudit)
            or not callable(service_preaudit)
            or not isinstance(municipal_validator, XmlSchemaValidator)
        ):
            raise FiscalValidationError("Incomplete governed WebISS Extrema composition")
        self._transport = transport
        self._load_intent = load_intent
        self._certificate = resolve_certificate
        self._canonical_preaudit = canonical_preaudit
        self._service_preaudit = service_preaudit
        self._cancellation_preaudit = cancellation_preaudit
        self._validator = municipal_validator

    def _trusted_intent(
        self, request: NfseAuthorizationRequest,
    ) -> ExtremaRpsIntent:
        if not isinstance(request, NfseAuthorizationRequest):
            raise FiscalValidationError("NFS-e request is required")
        intent = self._load_intent(
            request.document.scope, request.document.document_id,
        )
        validate_extrema_intent(request, intent)
        return intent

    def _outcome(
        self, *, request: NfseAuthorizationRequest,
        intent: ExtremaRpsIntent, response: bytes, is_query: bool,
    ) -> NfseAuthorizationResult:
        try:
            parsed = etree.fromstring(
                response, parser=etree.XMLParser(
                    no_network=True, resolve_entities=False, load_dtd=False,
                ),
            )
        except etree.XMLSyntaxError:
            raise WebissMgContractError("Invalid Extrema normalized response") from None
        reference = _invoice_reference(parsed, request, intent)
        messages = _response_messages(parsed)
        if reference is not None:
            if messages is not None:
                raise WebissMgContractError("WebISS returned contradictory result and rejection")
            return NfseAuthorizationResult(
                status=AuthorizationStatus.AUTHORIZED,
                invoice_reference=reference[0], verification_code=reference[1],
                invoice_number=reference[2], authorized_xml=response,
                scope=request.document.scope, document_id=request.document.document_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request.request_fingerprint, provider=_PROVIDER,
            )
        if messages is not None and not is_query:
            return NfseAuthorizationResult(
                status=AuthorizationStatus.REJECTED,
                rejection_code=messages[0], rejection_message=messages[1],
                scope=request.document.scope, document_id=request.document.document_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request.request_fingerprint, provider=_PROVIDER,
            )
        # A read-only query reporting "not found" cannot prove a failed POST,
        # and an uncorrelated response never authorizes an invoice.
        return NfseAuthorizationResult(
            status=AuthorizationStatus.PENDING,
            scope=request.document.scope, document_id=request.document.document_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.request_fingerprint, provider=_PROVIDER,
        )

    def authorize(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        intent = self._trusted_intent(request)
        self._canonical_preaudit(request)
        xml = build_extrema_rps_xml(request, intent, validator=self._validator)
        signed = prepare_abrasf203_soap(
            operation=Abrasf203Operation.GENERATE,
            xml=xml,
            scope=request.document.scope,
            issuer_cnpj=intent.issuer_cnpj,
            resolve_certificate=self._certificate,
            preaudit=self._service_preaudit,
            municipal_schema_version="2.02",
            municipal_validator=self._validator,
        )
        result = self._transport.exchange_prepared(
            envelope=signed,
            operation=Abrasf203Operation.GENERATE,
            scope=request.document.scope,
            issuer_cnpj=intent.issuer_cnpj,
            issuer_tax_regime=request.document.issuer.tax_regime,
            competence_date=request.document.competence_date,
            jurisdiction=request.document.issuer.address.jurisdiction,
        )
        return self._outcome(request=request, intent=intent, response=result, is_query=False)

    def prepare_cancellation(
        self, *,
        request: NfseAuthorizationRequest,
        authorized_xml: bytes,
        cancellation_code: str,
    ) -> tuple[Abrasf203Envelope, str]:
        """Sign one ORIGINAL NFS-e cancellation with A1; no HTTP side effect."""
        intent = self._trusted_intent(request)
        if not callable(self._cancellation_preaudit):
            raise FiscalValidationError("Approved municipal cancellation policy required")
        if cancellation_code not in {"1", "2", "3", "4", "5"}:
            raise FiscalValidationError("Invalid municipal cancellation reason code")
        self._validator.validate_document(authorized_xml)
        origin = etree.fromstring(
            authorized_xml, parser=etree.XMLParser(no_network=True, resolve_entities=False),
        )
        reference = _invoice_reference(origin, request, intent)
        if reference is None:
            raise WebissMgContractError("No correlated authorized invoice for cancellation")
        # Substitution returns BOTH the cancelled old invoice and the
        # replacement invoice. The only cancellable invoice is the one
        # correlated by _invoice_reference() to this durable RPS.
        if origin.tag == f"{_NS}SubstituirNfseResposta":
            invoices = origin.findall(
                f"{_NS}RetSubstituicao/{_NS}NfseSubstituidora/"
                f"{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse"
            )
        else:
            invoices = origin.findall(
                f".//{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse"
            )
        if len(invoices) != 1:
            raise WebissMgContractError(
                "Ambiguous original authorized NFS-e for cancellation"
            )
        original_number = invoices[0].findtext(f"{_NS}Numero", "")
        if original_number != reference[2]:
            raise WebissMgContractError(
                "Cancellation note does not match the durable fiscal authorization"
            )
        root = etree.Element(
            f"{_NS}CancelarNfseEnvio", nsmap=cast(dict[str, str], {None: _NS[1:-1]}),
        )
        pedido = etree.SubElement(root, f"{_NS}Pedido")
        ident = etree.SubElement(
            pedido, f"{_NS}InfPedidoCancelamento",
            Id="CAN" + request.request_fingerprint[:30],
        )
        nfse = etree.SubElement(ident, f"{_NS}IdentificacaoNfse")
        etree.SubElement(nfse, f"{_NS}Numero").text = original_number
        tax = etree.SubElement(nfse, f"{_NS}CpfCnpj")
        etree.SubElement(tax, f"{_NS}Cnpj").text = intent.issuer_cnpj.value
        etree.SubElement(nfse, f"{_NS}CodigoMunicipio").text = EXTREMA_IBGE
        etree.SubElement(ident, f"{_NS}CodigoCancelamento").text = cancellation_code
        envelope = prepare_abrasf203_soap(
            operation=Abrasf203Operation.CANCEL,
            xml=etree.tostring(root, encoding="utf-8"),
            scope=request.document.scope,
            issuer_cnpj=intent.issuer_cnpj,
            resolve_certificate=self._certificate,
            preaudit=self._service_preaudit,
            preaudit_cancel=self._cancellation_preaudit,
            municipal_schema_version="2.02",
            municipal_validator=self._validator,
        )
        return envelope, original_number

    def submit_cancellation(
        self, *, request: NfseAuthorizationRequest,
        envelope: Abrasf203Envelope, original_number: str,
    ) -> ExtremaCancellationOutcome:
        """Single governed SOAP POST; successful receipt must echo old document."""
        intent = self._trusted_intent(request)
        result = self._transport.exchange_prepared(
            envelope=envelope,
            operation=Abrasf203Operation.CANCEL,
            scope=request.document.scope,
            issuer_cnpj=intent.issuer_cnpj,
            issuer_tax_regime=request.document.issuer.tax_regime,
            competence_date=request.document.competence_date,
            jurisdiction=request.document.issuer.address.jurisdiction,
        )
        root = etree.fromstring(
            result, parser=etree.XMLParser(no_network=True, resolve_entities=False),
        )
        messages = _response_messages(root)
        if messages is not None:
            return ExtremaCancellationOutcome(
                confirmed=False, xml=result, rejection_code=messages[0],
            )
        confirmed = root.find(
            f"{_NS}RetCancelamento/{_NS}NfseCancelamento/"
            f"{_NS}Confirmacao/{_NS}Pedido/"
            f"{_NS}InfPedidoCancelamento/{_NS}IdentificacaoNfse"
        )
        if confirmed is None or (
            confirmed.findtext(f"{_NS}Numero", "") != original_number
            or confirmed.findtext(f"{_NS}CpfCnpj/{_NS}Cnpj", "")
            != intent.issuer_cnpj.value
            or confirmed.findtext(f"{_NS}CodigoMunicipio", "") != EXTREMA_IBGE
        ):
            raise WebissMgContractError(
                "Cancellation response does not prove original Extrema invoice cancellation"
            )
        return ExtremaCancellationOutcome(confirmed=True, xml=result)

    def prepare_substitution(
        self, *, original: NfseAuthorizationRequest,
        replacement: NfseAuthorizationRequest, original_xml: bytes,
        cancellation_code: str,
    ) -> tuple[Abrasf203Envelope, str]:
        """Build an unsigned cancellation+new RPS and sign all 3 official targets.

        The old and replacement documents must already exist as distinct,
        durable, independently preaudited fiscal intentions under one unit.
        This function does not dispatch a request.
        """
        original_intent = self._trusted_intent(original)
        new_intent = self._trusted_intent(replacement)
        if (
            not callable(self._cancellation_preaudit)
            or original.document.scope != replacement.document.scope
            or original.document.document_id == replacement.document.document_id
            or original_intent.issuer_cnpj != new_intent.issuer_cnpj
            or cancellation_code not in {"1", "2", "3", "4", "5"}
        ):
            raise FiscalValidationError("Substitution lacks shared issuer and cancellation policy")
        self._validator.validate_document(original_xml)
        initial = etree.fromstring(
            original_xml,
            parser=etree.XMLParser(no_network=True, resolve_entities=False),
        )
        old_reference = _invoice_reference(initial, original, original_intent)
        if old_reference is None:
            raise WebissMgContractError("Original authorized invoice is not correlated")
        invoices = initial.findall(
            f".//{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse"
        )
        if initial.tag == f"{_NS}SubstituirNfseResposta":
            invoices = initial.findall(
                f"{_NS}RetSubstituicao/{_NS}NfseSubstituidora/"
                f"{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse"
            )
        if len(invoices) != 1:
            raise WebissMgContractError("Original fiscal invoice is ambiguous")
        old_number = invoices[0].findtext(f"{_NS}Numero", "")
        new_xml = build_extrema_rps_xml(
            replacement, new_intent, validator=self._validator,
        )
        rps = etree.fromstring(new_xml)[0]
        root = etree.Element(
            f"{_NS}SubstituirNfseEnvio",
            nsmap=cast(dict[str, str], {None: _NS[1:-1]}),
        )
        group = etree.SubElement(
            root, f"{_NS}SubstituicaoNfse",
            Id="SUBST" + replacement.request_fingerprint[:30],
        )
        pedido = etree.SubElement(group, f"{_NS}Pedido")
        old_info = etree.SubElement(
            pedido, f"{_NS}InfPedidoCancelamento",
            Id="CAN" + original.request_fingerprint[:30],
        )
        ident = etree.SubElement(old_info, f"{_NS}IdentificacaoNfse")
        etree.SubElement(ident, f"{_NS}Numero").text = old_number
        tax = etree.SubElement(ident, f"{_NS}CpfCnpj")
        etree.SubElement(tax, f"{_NS}Cnpj").text = original_intent.issuer_cnpj.value
        etree.SubElement(ident, f"{_NS}CodigoMunicipio").text = EXTREMA_IBGE
        etree.SubElement(old_info, f"{_NS}CodigoCancelamento").text = cancellation_code
        group.append(rps)
        signed = prepare_abrasf203_soap(
            operation=Abrasf203Operation.SUBSTITUTE,
            xml=etree.tostring(root, encoding="utf-8"),
            scope=original.document.scope,
            issuer_cnpj=original_intent.issuer_cnpj,
            resolve_certificate=self._certificate,
            preaudit=self._service_preaudit,
            preaudit_cancel=self._cancellation_preaudit,
            municipal_schema_version="2.02",
            municipal_validator=self._validator,
        )
        return signed, old_number

    def submit_substitution(
        self, *, original: NfseAuthorizationRequest,
        replacement: NfseAuthorizationRequest, envelope: Abrasf203Envelope,
        original_number: str,
    ) -> ExtremaSubstitutionOutcome:
        """Dispatch once, verify the official linked old/new invoices, no retry."""
        intent = self._trusted_intent(original)
        replacement_intent = self._trusted_intent(replacement)
        result = self._transport.exchange_prepared(
            envelope=envelope, operation=Abrasf203Operation.SUBSTITUTE,
            scope=original.document.scope, issuer_cnpj=intent.issuer_cnpj,
            issuer_tax_regime=original.document.issuer.tax_regime,
            competence_date=original.document.competence_date,
            jurisdiction=original.document.issuer.address.jurisdiction,
        )
        xml = etree.fromstring(
            result, parser=etree.XMLParser(no_network=True, resolve_entities=False),
        )
        messages = _response_messages(xml)
        if messages is not None:
            return ExtremaSubstitutionOutcome(
                confirmed=False, xml=result, rejection_code=messages[0],
            )
        old = xml.find(f"{_NS}RetSubstituicao/{_NS}NfseSubstituida")
        new = xml.find(f"{_NS}RetSubstituicao/{_NS}NfseSubstituidora")
        if old is None or new is None:
            raise WebissMgContractError("Unconfirmed municipal replacement receipt")
        old_reference = _invoice_reference(old, original, intent)
        new_reference = _invoice_reference(new, replacement, replacement_intent)
        if old_reference is None or new_reference is None:
            raise WebissMgContractError("Substitution did not confirm both fiscal invoices")
        number = old.findtext(
            f"{_NS}CompNfse/{_NS}Nfse/{_NS}InfNfse/{_NS}Numero", "",
        )
        if number != original_number:
            raise WebissMgContractError("Substitution references a different original invoice")
        if (
            old_reference[0] == new_reference[0]
            or old_reference[2] == new_reference[2]
        ):
            raise WebissMgContractError(
                "WebISS substitution has no distinct replacement invoice"
            )
        return ExtremaSubstitutionOutcome(
            confirmed=True, xml=result, invoice_reference=new_reference[0],
            verification_code=new_reference[1], invoice_number=new_reference[2],
        )

    def query(self, request: NfseAuthorizationRequest) -> NfseAuthorizationResult:
        intent = self._trusted_intent(request)
        # A query never allocates another number and never signs or sends
        # another RPS; it reuses the exact number stored with the issuance.
        root = etree.Element(
            f"{_NS}ConsultarNfseRpsEnvio",
            nsmap=cast(dict[str, str], {None: _NS[1:-1]}),
        )
        identity = etree.SubElement(root, f"{_NS}IdentificacaoRps")
        for name, value in (
            ("Numero", str(intent.reservation.number)),
            ("Serie", str(intent.reservation.key.series)),
            ("Tipo", "1"),
        ):
            etree.SubElement(identity, f"{_NS}{name}").text = value
        prestador = etree.SubElement(root, f"{_NS}Prestador")
        cpf_cnpj = etree.SubElement(prestador, f"{_NS}CpfCnpj")
        etree.SubElement(cpf_cnpj, f"{_NS}Cnpj").text = intent.issuer_cnpj.value
        xml = etree.tostring(root, encoding="utf-8")
        self._validator.validate_document(xml)
        prepared = prepare_abrasf203_soap(
            operation=Abrasf203Operation.QUERY_RPS,
            xml=xml,
            scope=request.document.scope,
            issuer_cnpj=intent.issuer_cnpj,
            resolve_certificate=self._certificate,
            preaudit=self._service_preaudit,
            municipal_schema_version="2.02",
            municipal_validator=self._validator,
        )
        result = self._transport.exchange_prepared(
            envelope=prepared,
            operation=Abrasf203Operation.QUERY_RPS,
            scope=request.document.scope,
            issuer_cnpj=intent.issuer_cnpj,
            issuer_tax_regime=request.document.issuer.tax_regime,
            competence_date=request.document.competence_date,
            jurisdiction=request.document.issuer.address.jurisdiction,
        )
        return self._outcome(request=request, intent=intent, response=result, is_query=True)
