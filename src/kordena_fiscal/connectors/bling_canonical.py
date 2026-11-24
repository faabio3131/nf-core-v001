"""Bling sales facts mapped to canonical snapshots with governed fiscal profiles.

Provider classification hints never replace the canonical TaxRuleEngine. This
adapter performs no signing, numbering, transmission or tax-rate inference.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from kordena_fiscal.documents import (
    CanonicalFiscalDocument,
    FiscalLineSnapshot,
    FiscalPaymentSnapshot,
    FiscalRecipientSnapshot,
)
from kordena_fiscal.domain import (
    FiscalDocumentKind,
    FiscalProductProfile,
    FiscalProfile,
    FiscalValidationError,
    Money,
    SourceReference,
)
from kordena_fiscal.tax import (
    RecipientTaxProfile,
    TaxOperationType,
    TaxRule,
    TaxRuleContext,
    TaxRuleEngine,
)
from kordena_fiscal.tax.nfe_calculation import calculate_nfe_line

_CENT = Decimal("0.01")
_LIMIT = Decimal("999999999999.99")


def _number(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise FiscalValidationError(f"{field}: number required")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise FiscalValidationError(f"{field}: invalid number") from None
    if not number.is_finite() or number < 0 or number > _LIMIT or (positive and number == 0):
        raise FiscalValidationError(f"{field}: number out of range")
    return number


def _money(value: Any, field: str) -> Decimal:
    number = _number(value, field)
    if number != number.quantize(_CENT):
        raise FiscalValidationError(f"{field}: monetary precision exceeds cents")
    return number.quantize(_CENT)


def _allocate(total: Decimal, weights: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Largest remainder allocation, stable tie-break by source line order."""
    if total == 0:
        return tuple(Decimal("0.00") for _ in weights)
    weight_total = sum(weights)
    if weight_total <= 0:
        raise FiscalValidationError("cannot allocate adjustments to a zero-value order")
    with localcontext() as context:
        context.prec = 48
        cents = int(total * 100)
        exact = [Decimal(cents) * value / weight_total for value in weights]
        whole = [int(value) for value in exact]
        remainder = cents - sum(whole)
        ranked = sorted(range(len(weights)), key=lambda i: (-(exact[i] - whole[i]), i))
        for index in ranked[:remainder]:
            whole[index] += 1
        return tuple(Decimal(value) / 100 for value in whole)


def map_bling_document(
    order: Mapping[str, Any],
    *,
    document_id: str,
    company_id: str,
    recipient: FiscalRecipientSnapshot,
    issued_at: datetime,
    issuer: FiscalProfile,
    products_by_code: Mapping[str, FiscalProductProfile],
    rules: Sequence[TaxRule],
    payments: tuple[FiscalPaymentSnapshot, ...],
    taxable_factors: Mapping[str, Decimal] | None = None,
) -> CanonicalFiscalDocument:
    """Resolve each line from scoped profiles/rules and reconcile commercial totals.

    `valor` is Bling's net unit value: its item percentage must not be applied a
    second time. Percentage order discounts are calculated over the reconciled
    product total and require matching upstream totals; a mismatch is blocked.
    """
    if issuer.scope.host_namespace != "bling":
        raise FiscalValidationError("Bling preparation requires its own namespace")
    if not company_id.strip() or len(company_id) > 96:
        raise FiscalValidationError("Bling company identity is required")
    recipient_state = recipient.address.jurisdiction.state_code
    recipient_profile = (
        RecipientTaxProfile.CONSUMER_FINAL
        if recipient.final_consumer
        else RecipientTaxProfile.TAXPAYER
        if recipient.ie_indicator in {1, 2}
        else RecipientTaxProfile.NON_TAXPAYER
    )
    order_id = order.get("id")
    raw_lines = order.get("itens")
    if type(order_id) is not int or order_id <= 0:
        raise FiscalValidationError("Bling order id must be a positive integer")
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 500:
        raise FiscalValidationError("Bling order requires 1 to 500 lines")
    discount_data = order.get("desconto", {})
    transport = order.get("transporte", {})
    if not isinstance(discount_data, dict) or not isinstance(transport, dict):
        raise FiscalValidationError("Bling adjustments must be objects")
    discount = _number(discount_data.get("valor", 0), "discount")
    unit = discount_data.get("unidade", "REAL")
    if unit not in {"REAL", "PERCENTUAL"}:
        raise FiscalValidationError("Bling discount unit is unknown")
    if unit == "REAL":
        discount = _money(discount, "discount")
    elif discount > 100 or "total" not in order or "totalProdutos" not in order:
        raise FiscalValidationError("Bling percentage discount requires reconciled upstream totals")
    freight = _money(transport.get("frete", 0), "freight")
    other = _money(order.get("outrasDespesas", 0), "other expenses")
    engine = TaxRuleEngine()
    lines: list[FiscalLineSnapshot] = []
    for index, raw in enumerate(raw_lines, 1):
        if not isinstance(raw, dict):
            raise FiscalValidationError("Bling line must be an object")
        provider_ipi = _number(raw.get("aliquotaIPI", 0), "IPI rate")
        code = raw.get("codigo")
        if not isinstance(code, str) or not code.strip():
            raise FiscalValidationError("Bling line requires a product code")
        product = products_by_code.get(code.strip())
        if product is None or product.commercial_code != code.strip():
            raise FiscalValidationError(f"line {index}: governed product profile unavailable")
        if product.scope.identity_partition_key != issuer.scope.identity_partition_key:
            raise FiscalValidationError("Bling product profile belongs to another scope")
        quantity = _number(raw.get("quantidade"), "quantity", positive=True)
        unit_value = _number(raw.get("valor"), "unit value")
        if quantity != quantity.quantize(Decimal("0.0001")) or unit_value != unit_value.quantize(
            Decimal("0.0000000001")
        ):
            raise FiscalValidationError("Bling line precision exceeds XML commercial precision")
        gross = (quantity * unit_value).quantize(_CENT, rounding=ROUND_HALF_UP)
        if gross > _LIMIT:
            raise FiscalValidationError("Bling line amount exceeds supported range")
        decision = engine.resolve(
            TaxRuleContext(
                scope=issuer.scope,
                instant=issued_at,
                jurisdiction=issuer.address.jurisdiction,
                tax_regime=issuer.tax_regime,
                document_kind=FiscalDocumentKind.NFE,
                operation_type=TaxOperationType.SALE,
                recipient_profile=recipient_profile,
                product=product,
            ),
            rules,
        )
        selected_rates = decision.outcome.nfe_rates
        if provider_ipi and (selected_rates is None or selected_rates.ipi_rate != provider_ipi):
            raise FiscalValidationError("IPI hint conflicts with approved fiscal policy")
        expected_cfop_prefix = (
            "5" if recipient_state == issuer.address.jurisdiction.state_code else "6"
        )
        if not decision.outcome.cfop.startswith(expected_cfop_prefix):
            raise FiscalValidationError("resolved CFOP conflicts with recipient jurisdiction")
        taxable_quantity = taxable_price = None
        factor = (taxable_factors or {}).get(code.strip())
        if factor is not None:
            if not isinstance(factor, Decimal) or not factor.is_finite() or factor <= 0:
                raise FiscalValidationError("taxable conversion factor must be positive")
            with localcontext() as context:
                context.prec = 48
                taxable_quantity = quantity * factor
                if taxable_quantity > _LIMIT or taxable_quantity != taxable_quantity.quantize(
                    Decimal("0.0001")
                ):
                    raise FiscalValidationError("taxable quantity exceeds XML precision")
                taxable_price = (unit_value / factor).quantize(
                    Decimal("0.0000000001"), rounding=ROUND_HALF_UP
                )
                if (taxable_quantity * taxable_price).quantize(
                    _CENT, rounding=ROUND_HALF_UP
                ) != gross:
                    raise FiscalValidationError("taxable conversion does not reconcile")
        lines.append(
            FiscalLineSnapshot(
                line_number=index,
                product=product,
                quantity=quantity,
                unit_price=Money(unit_value),
                gross_amount=Money(gross),
                tax_decision=decision,
                taxable_quantity=taxable_quantity,
                taxable_unit_price=taxable_price,
            )
        )
    gross_total = sum(line.gross_amount.amount for line in lines)
    if unit == "PERCENTUAL":
        discount = (gross_total * discount / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
    if discount > gross_total:
        raise FiscalValidationError("Bling discount exceeds product amount")
    if "totalProdutos" in order and _money(order["totalProdutos"], "products total") != gross_total:
        raise FiscalValidationError("Bling product total conflicts with item amounts")
    expected = gross_total - discount + freight + other
    weights = [line.gross_amount.amount for line in lines]
    discounts = _allocate(discount, weights)
    freights, others = _allocate(freight, weights), _allocate(other, weights)
    document = CanonicalFiscalDocument(
        document_id=document_id,
        scope=issuer.scope,
        source=SourceReference("bling", f"{company_id}:{order_id}"),
        document_kind=FiscalDocumentKind.NFE,
        issued_at=issued_at,
        issuer=issuer,
        items=tuple(
            replace(
                line,
                discount_amount=Money(discounts[i]),
                surcharge_amount=Money(freights[i] + others[i]),
                freight_amount=Money(freights[i]),
            )
            for i, line in enumerate(lines)
        ),
        payments=payments,
        recipient=recipient,
    )
    if document.totals.net_amount.amount != expected:
        raise FiscalValidationError("canonical total differs from Bling reconciled amount")
    if any(
        line.tax_decision.outcome.nfe_rates is not None
        and line.tax_decision.outcome.nfe_rates.icms_benefit is not None
        for line in document.items
    ):
        raise FiscalValidationError("T14 benefit requires canonical authorized NF-e preparation")
    calculated_taxes = tuple(
        calculate_nfe_line(
            line.tax_decision,
            net_amount=line.net_amount.amount,
            regime=issuer.tax_regime,
            interstate_final_consumer=(
                recipient_state != issuer.address.jurisdiction.state_code
                and recipient.final_consumer
                and recipient.ie_indicator == 9
            ),
            taxable_quantity=line.taxable_quantity or line.quantity,
        )
        for line in document.items
        if line.tax_decision.outcome.nfe_rates is not None
    )
    expected += sum(
        (tax.ipi_amount + tax.st_amount + tax.fcp_st_amount for tax in calculated_taxes),
        Decimal(0),
    )
    if "total" in order and _money(order["total"], "order total") != expected:
        raise FiscalValidationError("Bling total requires reconciliation before fiscal preparation")
    if payments and document.totals.payment_amount.amount != expected:
        raise FiscalValidationError("payment snapshots do not reconcile with the order")
    return document
