"""Manual commercial facts enter the existing atomic fiscal preparation authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException

from kordena_fiscal.application.authorized_issuance import IssuanceApprovalRequired
from kordena_fiscal.application.nfe_preparation import prepare_nfe_sale
from kordena_fiscal.application.service import FiscalApplicationService
from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.documents import (
    CanonicalFiscalDocument,
    FiscalLineSnapshot,
    FiscalPaymentSnapshot,
    PaymentMethodKind,
)
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalDocumentKind,
    FiscalEnvironment,
    FiscalValidationError,
    Money,
    SourceReference,
)
from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions
from kordena_fiscal.lifecycle.idempotency import IdempotencyConflictError
from kordena_fiscal.numbering import SequenceStateError
from kordena_fiscal.persistence.ports import (
    FiscalUnitOfWork,
    FiscalUnitOfWorkFactory,
    PersistenceConflictError,
    PersistenceStateError,
)
from kordena_fiscal.runtime.native_sale_policy import load_sale_policy
from kordena_fiscal.runtime.sale_facts import parse_sale_rule, recipient_from_review
from kordena_fiscal.security.human_identity import (
    AuthenticatedHuman,
    HumanAuthorizationError,
    PortalPermission,
)
from kordena_fiscal.tax import (
    RecipientTaxProfile,
    TaxOperationType,
    TaxRuleAmbiguityError,
    TaxRuleContext,
    TaxRuleEngine,
    TaxRuleNotFoundError,
)
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault


def _number(value: Any, places: int, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{1,12}(?:\.[0-9]{1," + str(places) + r"})?", value
    ):
        raise FiscalValidationError("Invalid decimal commercial fact")
    number = Decimal(value)
    if positive and number <= 0:
        raise FiscalValidationError("Positive commercial fact required")
    return number


def native_sale_operation(
    *,
    factory: FiscalUnitOfWorkFactory,
    authority: AuthenticatedHuman,
    payload: Mapping[str, Any],
    idempotency_key: str | None,
    review_only: bool = False,
) -> Mapping[str, Any]:
    """Same session, scope, policy, numbering, A1 and archive as existing issuance."""
    try:
        required = {"unit_id", "environment", "document_kind"}
        if not review_only:
            required |= {
                "source_id",
                "issued_at",
                "policy_sha256",
                "recipient",
                "items",
                "payments",
                "change_amount",
            }
        if set(payload) != required:
            raise FiscalValidationError("Unknown or missing sale fields")
        unit = payload["unit_id"]
        if not isinstance(unit, str) or not unit.strip():
            raise FiscalValidationError("Fiscal unit required")
        authority.assert_permission(PortalPermission.DOCUMENT_ISSUE, unit_id=unit)
        if payload["environment"] != "homologation":
            raise FiscalValidationError("Only homologation is configured")
        kind = FiscalDocumentKind(payload["document_kind"])
        if kind not in {FiscalDocumentKind.NFE, FiscalDocumentKind.NFCE}:
            raise FiscalValidationError("Sale requires NF-e or NFC-e")
        scope = ExecutionScope(
            authority.tenant_id,
            unit,
            FiscalEnvironment.HOMOLOGATION,
            "native-sale",
            host_namespace="fm-nfcore",
        )
        now = datetime.now(UTC)
        issued = now if review_only else datetime.fromisoformat(payload["issued_at"])
        if issued.tzinfo is None or issued > now:
            raise FiscalValidationError("Issuance instant must be aware and not in the future")
        source = None if review_only else payload["source_id"]
        if not review_only and (
            not isinstance(source, str) or not 1 <= len(source) <= 120
            or source != source.strip() or not idempotency_key
            or not 1 <= len(idempotency_key) <= 256
        ):
            raise FiscalValidationError("Immutable sale source and idempotency key required")
        identity = hashlib.sha256(
            json.dumps([*scope.identity_material, kind.value, source]).encode()
        ).hexdigest()
        document_id = "native-sale-" + identity[:40]
        fingerprint = hashlib.sha256(
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        command_keys = (
            "native-sale-source:" + identity,
            "native-sale-command:" + hashlib.sha256((idempotency_key or "").encode()).hexdigest(),
        )
        # Check durable replay before loading today's policy or A1. The original
        # facts remain authoritative after a policy rotation or catalog update.
        # New reservations in this read phase roll back when leaving the UoW.
        if not review_only:
            with factory() as uow:
                registration = uow.control_plane.get_unit(authority.tenant_id, unit)
                if (
                    registration is None
                    or scope.environment not in registration.enabled_environments
                ):
                    raise FiscalValidationError("Unit is not enabled")
                original = uow.commercial.reserve_configuration_command(
                    scope, command_keys[0], fingerprint,
                )
                uow.commercial.reserve_configuration_command(scope, command_keys[1], fingerprint)
                if original is not None:
                    if original.get("document_id") != document_id:
                        raise PersistenceStateError("Sale replay identity mismatch")
                    uow.lifecycle.assert_scope(document_id, scope)
                    state = uow.lifecycle.get(document_id)
                    if state is None:
                        raise PersistenceStateError("Sale replay lifecycle missing")
                    FiscalApplicationService(factory)._load_prepared_from_uow(
                        uow, scope, document_id,
                    )
                    for key in command_keys:
                        uow.commercial.complete_configuration_command(
                            scope, key, {"document_id": document_id},
                        )
                    uow.commit()
                    return {
                        "document_id": document_id, "status": state.state.value,
                        "document_kind": kind.value, "replay": True, "transmitted": False,
                        "environment": "homologation",
                        "numbering_authority": "fiscal_sequence_durable",
                    }
        policy, digest, policy_bytes = load_sale_policy(os.environ, scope, kind)
        with factory() as uow:
            registration = uow.control_plane.get_unit(authority.tenant_id, unit)
            if registration is None or scope.environment not in registration.enabled_environments:
                raise FiscalValidationError("Unit is not enabled")
            issuer = uow.control_plane.get_profile(
                policy["issuer_profile_id"], policy["issuer_profile_version"]
            )
            if (
                issuer is None
                or issuer.scope.identity_partition_key != scope.identity_partition_key
                or not issuer.is_effective_at(issued)
            ):
                raise FiscalValidationError("Pinned issuer profile is unavailable")
            products = {}
            for product_id, binding in policy["products"].items():
                product = uow.commercial.resolve_product_profile(
                    tenant_id=scope.tenant_id,
                    unit_id=scope.unit_id,
                    environment=scope.environment,
                    product_id=product_id,
                    instant=issued,
                )
                if (
                    product is None
                    or product.version != binding["version"]
                    or product.scope.identity_partition_key != scope.identity_partition_key
                ):
                    raise FiscalValidationError("Pinned product profile is unavailable")
                products[product_id] = product
        if issuer.address.jurisdiction.state_code not in (
            {"SP", "MG"}
        ):
            raise FiscalValidationError("Sale preparation target unavailable")
        app = FiscalApplicationService(factory)
        provider = app.resolve_configured_provider_id(
            scope=scope,
            document_kind=kind,
            jurisdiction=issuer.address.jurisdiction,
            operation="authorize",
        )
        expected_provider = {
            ("SP", FiscalDocumentKind.NFE): "sefaz-sp-homologacao-nfe4",
            ("MG", FiscalDocumentKind.NFE): "sefaz-mg-homologacao-nfe4",
            ("MG", FiscalDocumentKind.NFCE): "sefaz-mg-homologacao-nfce4",
            ("SP", FiscalDocumentKind.NFCE): "sefaz-sp-homologacao-nfce4",
        }[(issuer.address.jurisdiction.state_code, kind)]
        if provider != expected_provider:
            raise FiscalValidationError("Sale provider binding does not match issuer/model")
        if review_only:
            return {
                "policy_sha256": digest,
                "policy_id": policy["policy_id"],
                "version": policy["version"],
                "document_kind": kind.value,
                "series": policy["series"],
                "accounting_approval_required": [
                    {
                        "rule_id": rule["rule_id"],
                        "benefit_id": rule["outcome"]["nfe_rates"]["icms_benefit"]["benefit_id"],
                        "benefit_code": rule["outcome"]["nfe_rates"]["icms_benefit"]["code"],
                    }
                    for rule in policy["rules"]
                    if "icms_benefit" in rule["outcome"]["nfe_rates"]
                ],
                "products": [
                    {
                        "product_id": pid,
                        "description": p.description,
                        "commercial_code": p.commercial_code,
                        "unit": p.commercial_unit.value,
                        "taxable_unit": p.taxable_unit.value,
                    }
                    for pid, p in products.items()
                ],
            }
        if digest != payload["policy_sha256"]:
            raise PersistenceConflictError("Sale policy changed after review")
        assert isinstance(source, str) and idempotency_key is not None
        recipient = (
            None if payload["recipient"] is None else recipient_from_review(payload["recipient"])
        )
        if recipient is None and kind is not FiscalDocumentKind.NFCE:
            raise FiscalValidationError("NF-e requires complete recipient")
        recipient_profile = (
            RecipientTaxProfile.CONSUMER_FINAL
            if recipient is None or recipient.final_consumer
            else RecipientTaxProfile.TAXPAYER
            if recipient.ie_indicator in {1, 2}
            else RecipientTaxProfile.NON_TAXPAYER
        )
        origin_state = issuer.address.jurisdiction.state_code
        destination_state = (
            origin_state if recipient is None else recipient.address.jurisdiction.state_code
        )
        if kind is FiscalDocumentKind.NFCE and destination_state != origin_state:
            raise FiscalValidationError("NFC-e requires a same-state recipient")
        raw_items = payload["items"]
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 500:
            raise FiscalValidationError("Sale requires 1 to 500 items")
        rules = tuple(parse_sale_rule(r, document_kind=kind) for r in policy["rules"])
        # Legacy same-state rules are preserved; no generic rate may authorize
        # an interstate sale. Selection and ambiguity remain in TaxRuleEngine.
        if destination_state != origin_state:
            rules = tuple(
                rule for rule in rules
                if rule.selector.destination_state_code == destination_state
            )
        lines = []
        for index, item in enumerate(raw_items, 1):
            fields = {"product_id", "quantity", "unit_price", "discount", "freight", "other"}
            if not isinstance(item, dict) or set(item) not in (
                fields,
                fields | {"taxable_quantity", "taxable_unit_price"},
            ):
                raise FiscalValidationError("Invalid sale line")
            product = products[item["product_id"]]
            quantity, price = (
                _number(item["quantity"], 4, positive=True),
                _number(item["unit_price"], 10, positive=True),
            )
            freight, other = _number(item["freight"], 2), _number(item["other"], 2)
            decision = TaxRuleEngine().resolve(
                TaxRuleContext(
                    scope=scope,
                    instant=issued,
                    jurisdiction=issuer.address.jurisdiction,
                    tax_regime=issuer.tax_regime,
                    document_kind=kind,
                    operation_type=TaxOperationType.SALE,
                    recipient_profile=recipient_profile,
                    product=product,
                    destination_state_code=destination_state,
                ),
                rules,
            )
            lines.append(
                FiscalLineSnapshot(
                    line_number=index,
                    product=product,
                    quantity=quantity,
                    unit_price=Money(price),
                    gross_amount=Money(
                        (quantity * price).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
                    ),
                    tax_decision=decision,
                    discount_amount=Money(_number(item["discount"], 2)),
                    surcharge_amount=Money(freight + other),
                    freight_amount=Money(freight),
                    taxable_quantity=_number(item["taxable_quantity"], 4, positive=True)
                    if "taxable_quantity" in item
                    else None,
                    taxable_unit_price=_number(item["taxable_unit_price"], 10)
                    if "taxable_unit_price" in item
                    else None,
                )
            )
        raw_payments = payload["payments"]
        if not isinstance(raw_payments, list) or not 1 <= len(raw_payments) <= 100:
            raise FiscalValidationError("Explicit payments required")
        payments = []
        for payment in raw_payments:
            if not isinstance(payment, dict) or set(payment) not in (
                {"method", "amount"},
                {"method", "amount", "acquirer_cnpj", "brand", "authorization"},
            ):
                raise FiscalValidationError("Invalid payment facts")
            payments.append(
                FiscalPaymentSnapshot(
                    PaymentMethodKind(payment["method"]),
                    Money(_number(payment["amount"], 2, positive=True)),
                    card_acquirer_cnpj=payment.get("acquirer_cnpj"),
                    card_brand=payment.get("brand"),
                    card_authorization=payment.get("authorization"),
                )
            )
        document = CanonicalFiscalDocument(
            document_id,
            scope,
            SourceReference("nfcore-portal-sale", source),
            kind,
            issued,
            issuer,
            tuple(lines),
            tuple(payments),
            Money(_number(payload["change_amount"], 2)),
            recipient=recipient,
        )
        with factory() as uow:
            previous = uow.lifecycle.get(document_id)
            if previous is not None:
                uow.lifecycle.assert_scope(document_id, scope)
        vault = EncryptedA1Vault.from_environ() if previous is None else None
        certificate = vault.resolve(scope=scope, issuer_cnpj=issuer.cnpj.value) if vault else None

        def commit(uow: FiscalUnitOfWork, persisted_id: str) -> None:
            for key in command_keys:
                uow.commercial.reserve_configuration_command(scope, key, fingerprint)
                uow.commercial.complete_configuration_command(
                    scope, key, {"document_id": persisted_id}
                )
            policy_key = (
                "native-sale-policy:"
                + hashlib.sha256(
                    json.dumps([kind.value, policy["policy_id"], policy["version"]]).encode()
                ).hexdigest()
            )
            replay = uow.commercial.reserve_configuration_command(scope, policy_key, digest)
            if replay is None:
                uow.archive.append(
                    FiscalArchiveEntry.build(
                        scope=scope,
                        document_reference=policy_key,
                        kind=FiscalArchiveKind.OTHER,
                        content=policy_bytes,
                        media_type="application/vnd.nfcore.sale-fiscal-policy.v1+json",
                        archived_at=now,
                        retention=RetentionPolicyMetadata("nfcore-fiscal-policy", 1),
                    )
                )
            uow.commercial.complete_configuration_command(scope, policy_key, {"sha256": digest})

        result = prepare_nfe_sale(
            factory,
            document,
            options=NfeSaleOptions(**policy["sale_options"]),
            series=policy["series"],
            certificate=certificate,
            now=now,
            commit_preparation=commit,
        )
        with factory() as uow:
            state = uow.lifecycle.get(result)
        return {
            "document_id": result,
            "status": state.state.value if state else "unknown",
            "document_kind": kind.value,
            "replay": previous is not None,
            "transmitted": False,
            "environment": "homologation",
            "numbering_authority": "fiscal_sequence_durable",
        }
    except IssuanceApprovalRequired as exc:
        raise HTTPException(409, detail={"code": "ACCOUNTING_ISSUANCE_BLOCKED"}) from exc
    except HumanAuthorizationError as exc:
        raise HTTPException(403, detail={"code": "NATIVE_SALE_UNIT_FORBIDDEN"}) from exc
    except (
        PersistenceConflictError, PersistenceStateError,
        IdempotencyConflictError, SequenceStateError,
    ) as exc:
        raise HTTPException(409, detail={"code": "NATIVE_SALE_CONTENT_CONFLICT"}) from exc
    except (
        FiscalValidationError, TaxRuleNotFoundError, TaxRuleAmbiguityError,
        KeyError, TypeError, ValueError, ArithmeticError,
    ) as exc:
        raise HTTPException(
            400, detail={"code": "NATIVE_SALE_INVALID_FACTS_OR_CONFIGURATION"}
        ) from exc
