"""Configurable Bling preparation using pinned policy and existing profile stores."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from kordena_fiscal.application.bling_orders import BlingOrders
from kordena_fiscal.archive import FiscalArchiveEntry, FiscalArchiveKind, RetentionPolicyMetadata
from kordena_fiscal.connectors.bling_canonical import map_bling_document
from kordena_fiscal.documents import (
    FiscalPaymentSnapshot,
    PaymentMethodKind,
)
from kordena_fiscal.domain import (
    ExecutionScope,
    FiscalValidationError,
    Money,
)
from kordena_fiscal.issuance.nfe_builder import NfeSaleOptions
from kordena_fiscal.vault.encrypted_a1 import EncryptedA1Vault

from .sale_facts import _unique, recipient_from_review
from .sale_facts import parse_sale_rule as _rule


class BlingSalePreparer:
    def __init__(self, environ: Mapping[str, str]) -> None:
        self.environ = environ

    def policy(self, orders: BlingOrders) -> tuple[dict[str, Any], str]:
        policy, digest, _raw = self._policy_artifact(orders)
        return policy, digest

    @staticmethod
    def policy_scope_digest(scope: ExecutionScope, company_id: str) -> str:
        """Filename is derived only from canonical fiscal scope and provider company.

        Neither an HTTP field nor a provider webhook can select another company's
        policy. The digest also hides tenant identifiers from directory listings.
        """
        if scope.host_namespace != "bling":
            raise FiscalValidationError("Bling fiscal policy requires canonical host scope")
        if not isinstance(company_id, str) or not company_id.strip():
            raise FiscalValidationError("Bling fiscal policy requires company identity")
        material = [*scope.identity_material, company_id]
        return hashlib.sha256(
            json.dumps(material, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    def _policy_artifact(self, orders: BlingOrders) -> tuple[dict[str, Any], str, bytes]:
        if self.environ.get("NFCORE_BLING_INSTALLATIONS_ENABLED") == "true":
            # Multi-company mode must never read the legacy global policy file.
            # Resolve from the already authorized tenant/unit/environment/company.
            if (
                self.environ.get("NFCORE_BLING_FISCAL_POLICY_FILE")
                or self.environ.get("NFCORE_BLING_FISCAL_POLICY_SHA256")
            ):
                raise FiscalValidationError("legacy global policy is forbidden in Bling multi mode")
            root = Path(self.environ.get("NFCORE_BLING_FISCAL_POLICY_ROOT", ""))
            if not root.is_absolute() or root.is_symlink() or not root.is_dir():
                raise FiscalValidationError("Bling scoped fiscal policy directory unavailable")
            digest = self.policy_scope_digest(orders.scope, orders.company_id)
            policy_path = root / f"{digest}.json"
            digest_path = root / f"{digest}.sha256"
            if policy_path.is_symlink() or digest_path.is_symlink():
                raise FiscalValidationError("Bling policy symlink is forbidden")
            try:
                # A manifest-sized pin, NOT arbitrary JSON from the HTTP request.
                with digest_path.open("rb") as stream:
                    signature = stream.read(66)
                if not re.fullmatch(rb"[0-9a-f]{64}\n?", signature):
                    raise FiscalValidationError("Bling fiscal policy digest invalid")
                expected = signature.decode("ascii").strip()
            except OSError:
                raise FiscalValidationError("Bling fiscal policy digest unavailable") from None
            path = policy_path
        else:
            if self.environ.get("NFCORE_BLING_FISCAL_POLICY_ROOT"):
                raise FiscalValidationError("Bling scoped policy requires multi-installation mode")
            path = Path(self.environ.get("NFCORE_BLING_FISCAL_POLICY_FILE", ""))
            expected = self.environ.get("NFCORE_BLING_FISCAL_POLICY_SHA256", "")
            if not path or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise FiscalValidationError("Bling fiscal policy is not configured")
        try:
            if path.is_symlink() or not path.is_file():
                raise FiscalValidationError("Bling fiscal policy artifact unavailable")
            with path.open("rb") as stream:
                raw = stream.read(1_048_577)
            if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != expected:
                raise FiscalValidationError("Bling fiscal policy integrity mismatch")
            policy = json.loads(raw, object_pairs_hook=_unique)
            if not isinstance(policy, dict) or set(policy) != {
                "schema_version",
                "policy_id",
                "version",
                "company_id",
                "tenant_id",
                "unit_id",
                "environment",
                "issuer_profile_id",
                "issuer_profile_version",
                "products",
                "payment_methods",
                "series",
                "sale_options",
                "rules",
            }:
                raise FiscalValidationError("invalid fiscal policy fields")
            if (
                type(policy["schema_version"]) is not int
                or policy["schema_version"] != 1
                or type(policy["issuer_profile_version"]) is not int
                or policy["issuer_profile_version"] < 1
                or type(policy["version"]) is not int
                or policy["version"] < 1
                or not isinstance(policy["policy_id"], str)
                or not policy["policy_id"].strip()
                or len(policy["policy_id"]) > 128
                or policy["company_id"] != orders.company_id
                or policy["tenant_id"] != orders.scope.tenant_id
                or policy["unit_id"] != orders.scope.unit_id
                or policy["environment"] != orders.scope.environment.value
            ):
                raise FiscalValidationError("Bling fiscal policy scope mismatch")
            if not isinstance(policy["rules"], list) or not 1 <= len(policy["rules"]) <= 500:
                raise FiscalValidationError("Bling fiscal policy requires explicit rules")
            if not isinstance(policy["products"], dict) or not policy["products"]:
                raise FiscalValidationError("product profile bindings are required")
            for binding in policy["products"].values():
                if (
                    not isinstance(binding, dict)
                    or set(binding)
                    not in (
                        {"product_id", "version"},
                        {"product_id", "version", "taxable_factor"},
                    )
                    or type(binding["version"]) is not int
                    or binding["version"] < 1
                    or not isinstance(binding["product_id"], str)
                    or not binding["product_id"]
                    or (
                        "taxable_factor" in binding
                        and (
                            not isinstance(binding["taxable_factor"], str)
                            or not re.fullmatch(
                                r"[0-9]{1,12}(?:\.[0-9]{1,10})?", binding["taxable_factor"]
                            )
                            or Decimal(binding["taxable_factor"]) <= 0
                        )
                    )
                ):
                    raise FiscalValidationError("invalid product profile binding")
            return policy, expected, raw
        except (OSError, KeyError, TypeError, ValueError, RecursionError):
            raise FiscalValidationError("Bling fiscal policy is unavailable or invalid") from None

    def prepare(
        self, orders: BlingOrders, order_id: int, payload: Mapping[str, Any], actor: str
    ) -> str:
        required = {"snapshot_sha256", "issued_at", "recipient", "policy_sha256"}
        if not required <= set(payload) or set(payload) - required - {"card_payments"}:
            raise FiscalValidationError(
                "Bling preparation requires the reviewed snapshot and policy"
            )
        policy, digest, policy_bytes = self._policy_artifact(orders)
        if digest != payload["policy_sha256"]:
            raise FiscalValidationError("Bling fiscal policy changed after review")
        row = orders.get(order_id)
        if row is None or row.get("snapshot_sha256") != payload["snapshot_sha256"]:
            raise FiscalValidationError("Bling order changed after review")
        try:
            issued_at = datetime.fromisoformat(payload["issued_at"])
            now = datetime.now(UTC)
            if issued_at.tzinfo is None or issued_at > now:
                raise FiscalValidationError(
                    "Bling issuance instant must be aware and not in the future"
                )
            recipient = recipient_from_review(payload["recipient"])
            raw = orders.snapshot(order_id)["raw"]
            contact = raw.get("contato", {})
            if not isinstance(contact, dict):
                raise FiscalValidationError("Bling contact is invalid")
            provider_document = contact.get("numeroDocumento")
            if (
                provider_document
                and re.sub(r"[.\-/]", "", provider_document) != recipient.document.value
            ):
                raise FiscalValidationError("reviewed recipient differs from the Bling order")
            with orders.factory() as uow:
                issuer = uow.control_plane.get_profile(
                    policy["issuer_profile_id"], policy["issuer_profile_version"]
                )
                if issuer is None:
                    raise FiscalValidationError("issuer fiscal profile is not configured")
                products = {}
                for code, binding in policy["products"].items():
                    product = uow.commercial.resolve_product_profile(
                        tenant_id=orders.scope.tenant_id,
                        unit_id=orders.scope.unit_id,
                        environment=orders.scope.environment,
                        product_id=binding["product_id"],
                        instant=issued_at,
                    )
                    if product is None or product.version != binding["version"]:
                        raise FiscalValidationError(
                            "pinned product fiscal profile is not configured"
                        )
                    products[code] = product
            if issuer.scope.identity_partition_key != orders.scope.identity_partition_key:
                raise FiscalValidationError("issuer belongs to a different installation")
            card_payments = payload.get("card_payments", {})
            if not isinstance(card_payments, dict):
                raise FiscalValidationError("card payment review must be an object")
            parcels = raw["parcelas"]
            if not isinstance(parcels, list):
                raise FiscalValidationError("order payments must be a list")
            if any(
                not isinstance(index, str)
                or not index.isascii()
                or not index.isdigit()
                or str(int(index)) != index
                or int(index) >= len(parcels)
                or not isinstance(facts, dict)
                or set(facts) != {"acquirer_cnpj", "brand", "authorization"}
                for index, facts in card_payments.items()
            ):
                raise FiscalValidationError("invalid card payment review")
            payments = tuple(
                FiscalPaymentSnapshot(
                    method=PaymentMethodKind(
                        policy["payment_methods"][str(parcel["formaPagamento"]["id"])]
                    ),
                    amount=Money(Decimal(str(parcel["valor"]))),
                    card_acquirer_cnpj=card_payments.get(str(index), {}).get("acquirer_cnpj"),
                    card_brand=card_payments.get(str(index), {}).get("brand"),
                    card_authorization=card_payments.get(str(index), {}).get("authorization"),
                )
                for index, parcel in enumerate(parcels)
            )
            options = NfeSaleOptions(**policy["sale_options"])
            document = map_bling_document(
                raw,
                document_id="bling-" + orders.key(order_id).split(":", 1)[1],
                company_id=orders.company_id,
                recipient=recipient,
                issued_at=issued_at,
                issuer=issuer,
                products_by_code=products,
                rules=tuple(_rule(r) for r in policy["rules"]),
                payments=payments,
                taxable_factors={
                    code: Decimal(str(binding["taxable_factor"]))
                    for code, binding in policy["products"].items()
                    if "taxable_factor" in binding
                },
            )
            # A version is immutable even if the deployment file is replaced later.
            policy_key = (
                "bling-fiscal-policy:"
                + hashlib.sha256(
                    json.dumps(
                        [
                            *orders.scope.identity_material,
                            orders.company_id,
                            policy["policy_id"],
                            policy["version"],
                        ]
                    ).encode()
                ).hexdigest()
            )
            with orders.factory() as uow:
                existing_policy = uow.commercial.reserve_configuration_command(
                    orders.scope, policy_key, digest
                )
                if existing_policy is None:
                    uow.archive.append(
                        FiscalArchiveEntry.build(
                            scope=orders.scope,
                            document_reference=policy_key,
                            kind=FiscalArchiveKind.OTHER,
                            content=policy_bytes,
                            media_type="application/vnd.nfcore.bling-fiscal-policy.v1+json",
                            archived_at=now,
                            retention=RetentionPolicyMetadata("nfcore-fiscal-policy", 1),
                        )
                    )
                uow.commercial.complete_configuration_command(
                    orders.scope, policy_key, {"sha256": digest}
                )
                uow.commit()
            vault = EncryptedA1Vault.from_environ()
            certificate = (
                vault.resolve(scope=orders.scope, issuer_cnpj=issuer.cnpj.value)
                if vault and row.get("document_id") is None
                else None
            )
            return orders.prepare_sale(
                order_id,
                document,
                snapshot_sha256=payload["snapshot_sha256"],
                actor_id=actor,
                now=now,
                options=options,
                series=policy["series"],
                certificate=certificate,
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise FiscalValidationError(
                "Bling fiscal preparation facts or configuration are invalid"
            ) from None
