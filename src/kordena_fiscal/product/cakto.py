"""Provider-specific Cakto commercial boundary for WP-WEB-11.

This module grants commercial entitlements only. It deliberately has no port for
fiscal certificates, CSC, provider credentials, homologation or fiscal production
activation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self


class CaktoIntegrationError(ValueError):
    """Base error for the fail-closed Cakto integration."""


class CaktoAuthenticationError(CaktoIntegrationError):
    """Webhook origin/replay validation failed."""


class CaktoPayloadError(CaktoIntegrationError):
    """Webhook payload does not match the documented contract."""


class CaktoStateConflictError(CaktoIntegrationError):
    """Durable commercial state conflicts with a received event."""


class CaktoTransientProcessingError(CaktoIntegrationError):
    """A retryable local processing dependency is not ready yet."""


class CaktoPermanentProcessingError(CaktoIntegrationError):
    """Processing cannot safely be retried without administrative correction."""


class CaktoWebhookEvent(StrEnum):
    CHECKOUT_ABANDONMENT = "checkout_abandonment"
    PURCHASE_APPROVED = "purchase_approved"
    PURCHASE_REFUSED = "purchase_refused"
    REFUND = "refund"
    CHARGEBACK = "chargeback"
    PIX_GENERATED = "pix_gerado"
    BOLETO_GENERATED = "boleto_gerado"
    PICPAY_GENERATED = "picpay_gerado"
    OPENFINANCE_NUBANK_GENERATED = "openfinance_nubank_gerado"
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    SUBSCRIPTION_RENEWAL_REFUSED = "subscription_renewal_refused"
    SUBSCRIPTION_PAUSED = "subscription_paused"
    SUBSCRIPTION_RESUMED = "subscription_resumed"
    SUBSCRIPTION_LATE = "subscription_late"
    SUBSCRIPTION_LATE_RECOVERED = "subscription_late_recovered"
    SUBSCRIPTION_CANCELED = "subscription_canceled"


class CaktoInboxStatus(StrEnum):
    RECEIVED = "received"
    RETRY_WAIT = "retry_wait"
    PROCESSED = "processed"
    DEAD_LETTER = "dead_letter"


class CaktoEntitlementStatus(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"
    SUSPENDED = "suspended"
    CANCELED = "canceled"


class CaktoExternalSubscriptionStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    EXPIRED = "expired"
    CANCELED = "canceled"


@dataclass(frozen=True, slots=True)
class CaktoApiContract:
    """Documented public API endpoints; staging URL must never be inferred."""

    base_url: str = "https://api.cakto.com.br"
    token_path: str = "/public_api/token/"
    payments_path: str = "/public_api/payments/"
    subscriptions_path: str = "/public_api/subscriptions/"
    webhook_path: str = "/public_api/webhook/"


@dataclass(frozen=True, slots=True)
class CaktoPlanBinding:
    external_product_id: str
    external_offer_id: str
    plan_id: str
    entitlement_ids: tuple[str, ...]
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_product_id",
            _text(self.external_product_id, "product"),
        )
        object.__setattr__(
            self,
            "external_offer_id",
            _text(self.external_offer_id, "offer"),
        )
        object.__setattr__(self, "plan_id", _token(self.plan_id, "plan_id"))
        entitlements = tuple(_token(item, "entitlement_id") for item in self.entitlement_ids)
        if not entitlements or len(entitlements) != len(set(entitlements)):
            raise CaktoPayloadError("entitlement_ids must be non-empty and unique")
        object.__setattr__(self, "entitlement_ids", entitlements)
        if not isinstance(self.enabled, bool):
            raise CaktoPayloadError("enabled must be bool")

    @property
    def checkout_url(self) -> str:
        return f"https://pay.cakto.com.br/{self.external_offer_id}"


@dataclass(frozen=True, slots=True)
class CaktoWebhookInboxEntry:
    event_key: str
    event_type: CaktoWebhookEvent
    order_id: str | None
    external_product_id: str
    external_offer_id: str | None
    external_customer_id: str | None
    order_status: str | None
    occurred_at: datetime
    payload_sha256: str
    received_at: datetime
    callback_token: str | None = None
    external_subscription_id: str | None = None
    status: CaktoInboxStatus = CaktoInboxStatus.RECEIVED
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    last_error: str | None = None
    tenant_id: str | None = None
    outcome_reference: str | None = None
    external_customer_email: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_key", _text(self.event_key, "event_key", 320))
        if not isinstance(self.event_type, CaktoWebhookEvent):
            raise CaktoPayloadError("event_type must be CaktoWebhookEvent")
        object.__setattr__(
            self,
            "external_product_id",
            _text(self.external_product_id, "product"),
        )
        if self.external_offer_id is not None:
            object.__setattr__(
                self,
                "external_offer_id",
                _text(self.external_offer_id, "offer"),
            )
        if self.external_customer_id is not None:
            object.__setattr__(
                self,
                "external_customer_id",
                _text(self.external_customer_id, "customer", 160),
            )
        if self.order_id is not None:
            object.__setattr__(self, "order_id", _text(self.order_id, "order_id", 160))
        if self.order_status is not None:
            object.__setattr__(
                self,
                "order_status",
                _text(self.order_status, "order_status", 80),
            )
        if self.callback_token is not None:
            callback = _text(self.callback_token, "callback", 255)
            allowed = set(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._~-"
            )
            if any(character not in allowed for character in callback):
                raise CaktoPayloadError("callback contains invalid token characters")
            object.__setattr__(self, "callback_token", callback)
        if self.external_subscription_id is not None:
            object.__setattr__(
                self,
                "external_subscription_id",
                _text(
                    self.external_subscription_id,
                    "external_subscription_id",
                    160,
                ),
            )
        _aware(self.occurred_at, "occurred_at")
        _aware(self.received_at, "received_at")
        if len(self.payload_sha256) != 64:
            raise CaktoPayloadError("payload_sha256 must be sha256 hex")
        if not isinstance(self.status, CaktoInboxStatus):
            raise CaktoPayloadError("status must be CaktoInboxStatus")
        if self.attempt_count < 0:
            raise CaktoPayloadError("attempt_count cannot be negative")
        if self.next_attempt_at is not None:
            _aware(self.next_attempt_at, "next_attempt_at")
        if self.tenant_id is not None:
            object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        if self.external_customer_email is not None:
            object.__setattr__(
                self,
                "external_customer_email",
                _optional_email(self.external_customer_email),
            )


@dataclass(frozen=True, slots=True)
class CaktoCommercialTenant:
    tenant_id: str
    external_customer_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self,
            "external_customer_id",
            _text(self.external_customer_id, "external_customer_id", 160),
        )
        _aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class CaktoCommercialEntitlement:
    tenant_id: str
    plan_id: str
    entitlement_ids: tuple[str, ...]
    status: CaktoEntitlementStatus
    last_event_at: datetime
    last_event_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _token(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "plan_id", _token(self.plan_id, "plan_id"))
        entitlements = tuple(_token(item, "entitlement_id") for item in self.entitlement_ids)
        if not entitlements:
            raise CaktoPayloadError("entitlement_ids must not be empty")
        object.__setattr__(self, "entitlement_ids", entitlements)
        if not isinstance(self.status, CaktoEntitlementStatus):
            raise CaktoPayloadError("status must be CaktoEntitlementStatus")
        _aware(self.last_event_at, "last_event_at")
        object.__setattr__(
            self,
            "last_event_key",
            _text(self.last_event_key, "last_event_key", 320),
        )


@dataclass(frozen=True, slots=True)
class CaktoReconciliationSnapshot:
    external_customer_id: str
    external_product_id: str
    external_offer_id: str
    status: CaktoExternalSubscriptionStatus
    observed_at: datetime
    external_subscription_id: str | None = None
    external_order_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "external_customer_id",
            _text(self.external_customer_id, "external_customer_id", 160),
        )
        object.__setattr__(
            self,
            "external_product_id",
            _text(self.external_product_id, "product"),
        )
        object.__setattr__(
            self,
            "external_offer_id",
            _text(self.external_offer_id, "offer"),
        )
        if not isinstance(self.status, CaktoExternalSubscriptionStatus):
            raise CaktoPayloadError("status must be CaktoExternalSubscriptionStatus")
        if self.external_subscription_id is not None:
            object.__setattr__(
                self,
                "external_subscription_id",
                _text(
                    self.external_subscription_id,
                    "external_subscription_id",
                    160,
                ),
            )
        if self.external_order_id is not None:
            object.__setattr__(
                self,
                "external_order_id",
                _text(self.external_order_id, "external_order_id", 160),
            )
        _aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class CaktoReconciliationResult:
    canonical_purchase_id: str | None
    external_status: CaktoExternalSubscriptionStatus
    canonical_status: str | None
    drift: bool


class CaktoCanonicalCommercialBridge(Protocol):
    def process(
        self,
        entry: CaktoWebhookInboxEntry,
        binding: CaktoPlanBinding,
    ) -> str: ...

    def reconcile(
        self,
        snapshot: CaktoReconciliationSnapshot,
        binding: CaktoPlanBinding,
    ) -> CaktoReconciliationResult: ...


@dataclass(frozen=True, slots=True)
class CaktoProcessingResult:
    claimed: int = 0
    succeeded: int = 0
    retry_wait: int = 0
    dead_letter: int = 0
    stale_ignored: int = 0


class CaktoCommercialStore(Protocol):
    def put_cakto_plan_binding(self, binding: CaktoPlanBinding) -> CaktoPlanBinding: ...

    def list_cakto_plan_bindings(self) -> tuple[CaktoPlanBinding, ...]: ...

    def resolve_cakto_plan_binding(
        self,
        product_id: str,
        offer_id: str | None,
    ) -> CaktoPlanBinding | None: ...

    def receive_cakto_event(
        self,
        entry: CaktoWebhookInboxEntry,
    ) -> tuple[CaktoWebhookInboxEntry, bool]: ...

    def get_cakto_event(self, event_key: str) -> CaktoWebhookInboxEntry | None: ...

    def list_due_cakto_events(
        self,
        now: datetime,
        limit: int,
    ) -> tuple[CaktoWebhookInboxEntry, ...]: ...

    def mark_cakto_processed(
        self,
        event_key: str,
        *,
        tenant_id: str | None,
        outcome_reference: str,
    ) -> CaktoWebhookInboxEntry: ...

    def mark_cakto_retry(
        self,
        event_key: str,
        *,
        next_attempt_at: datetime,
        error: str,
    ) -> CaktoWebhookInboxEntry: ...

    def mark_cakto_dead_letter(
        self,
        event_key: str,
        *,
        error: str,
    ) -> CaktoWebhookInboxEntry: ...

    def get_cakto_tenant_by_customer(
        self,
        external_customer_id: str,
    ) -> CaktoCommercialTenant | None: ...

    def put_cakto_tenant(self, tenant: CaktoCommercialTenant) -> CaktoCommercialTenant: ...

    def get_cakto_entitlement(
        self,
        tenant_id: str,
        plan_id: str,
    ) -> CaktoCommercialEntitlement | None: ...

    def put_cakto_entitlement(
        self,
        entitlement: CaktoCommercialEntitlement,
    ) -> CaktoCommercialEntitlement: ...


class CaktoUnitOfWork(Protocol):
    @property
    def commercial(self) -> CaktoCommercialStore: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class CaktoUnitOfWorkFactory(Protocol):
    def __call__(self) -> CaktoUnitOfWork: ...


class CaktoMetricSink(Protocol):
    def increment(self, name: str, value: float = 1.0, **labels: str) -> None: ...


class NullCaktoMetricSink:
    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        del name, value, labels


class CaktoWebhookVerifier:
    """Verify the documented timestamped HMAC over the exact raw body."""

    def __init__(self, secret: bytes, *, tolerance_seconds: int = 300) -> None:
        if not isinstance(secret, bytes) or not secret:
            raise CaktoAuthenticationError("webhook secret must be non-empty bytes")
        if tolerance_seconds < 1:
            raise CaktoAuthenticationError("tolerance_seconds must be positive")
        self._secret = secret
        self._tolerance_seconds = tolerance_seconds

    def verify_and_parse(
        self,
        *,
        raw_body: bytes,
        timestamp_header: str,
        signature_header: str,
        received_at: datetime,
    ) -> tuple[CaktoWebhookInboxEntry, ...]:
        _aware(received_at, "received_at")
        if not raw_body:
            raise CaktoPayloadError("webhook body must not be empty")
        try:
            timestamp = int(timestamp_header)
        except ValueError as exc:
            raise CaktoAuthenticationError("X-Cakto-Timestamp is invalid") from exc
        if abs(received_at.timestamp() - timestamp) > self._tolerance_seconds:
            raise CaktoAuthenticationError("Cakto webhook timestamp is outside replay tolerance")
        expected = hmac.new(
            self._secret,
            timestamp_header.encode("utf-8") + b"." + raw_body,
            hashlib.sha256,
        ).hexdigest()
        known_signatures = tuple(
            item.strip()
            for item in signature_header.split(",")
            if item.strip().startswith("v1=")
        )
        if not any(
            hmac.compare_digest(candidate, f"v1={expected}")
            for candidate in known_signatures
        ):
            raise CaktoAuthenticationError("Cakto webhook signature is invalid")
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaktoPayloadError("Cakto webhook must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise CaktoPayloadError("Cakto webhook envelope must be an object")
        if not isinstance(payload.get("secret"), str):
            raise CaktoPayloadError("Cakto webhook envelope secret field is missing")
        try:
            event_type = CaktoWebhookEvent(_text(payload.get("event"), "event", 80))
        except ValueError as exc:
            raise CaktoPayloadError("unsupported Cakto webhook event") from exc
        data = payload.get("data")
        raw_items = data if isinstance(data, list) else [data]
        if not raw_items or any(not isinstance(item, dict) for item in raw_items):
            raise CaktoPayloadError("Cakto webhook data must be object or non-empty list")
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        return tuple(
            self._parse_item(
                event_type=event_type,
                data=item,
                payload_hash=payload_hash,
                received_at=received_at,
            )
            for item in raw_items
            if isinstance(item, dict)
        )

    @staticmethod
    def _parse_item(
        *,
        event_type: CaktoWebhookEvent,
        data: dict[str, Any],
        payload_hash: str,
        received_at: datetime,
    ) -> CaktoWebhookInboxEntry:
        product = _object(data.get("product"), "product")
        product_id = _text(product.get("id"), "product.id")
        offer_raw = data.get("offer")
        offer = None if offer_raw is None else _object(offer_raw, "offer")
        offer_id = None if offer is None else _text(offer.get("id"), "offer.id")
        created_at = _iso_datetime(data.get("createdAt"), "createdAt")
        if event_type is CaktoWebhookEvent.CHECKOUT_ABANDONMENT:
            email = data.get("customerEmail")
            if email is not None and not isinstance(email, str):
                raise CaktoPayloadError("customerEmail must be string or null")
            if offer_id is None:
                raise CaktoPayloadError("checkout abandonment requires offer.id")
            material = f"{email or ''}|{offer_id}|{created_at.isoformat()}"
            event_key = f"{event_type.value}:{hashlib.sha256(material.encode()).hexdigest()}"
            return CaktoWebhookInboxEntry(
                event_key=event_key,
                event_type=event_type,
                order_id=None,
                external_product_id=product_id,
                external_offer_id=offer_id,
                external_customer_id=None,
                order_status=None,
                occurred_at=created_at,
                payload_sha256=payload_hash,
                received_at=received_at,
            )

        order_id = _text(data.get("id"), "data.id", 160)
        customer = _object(data.get("customer"), "customer")
        customer_id = customer.get("id")
        if not isinstance(customer_id, (str, int)) or isinstance(customer_id, bool):
            raise CaktoPayloadError("customer.id must be string or integer")
        customer_email = customer.get("email")
        if customer_email is not None and not isinstance(customer_email, str):
            raise CaktoPayloadError("customer.email must be string or null")
        order_status = _text(data.get("status"), "status", 80)
        callback_raw = data.get("callback")
        if callback_raw is not None and not isinstance(callback_raw, str):
            raise CaktoPayloadError("callback must be string or null")
        subscription_raw = data.get("subscription")
        external_subscription_id: str | None = None
        if subscription_raw is not None:
            subscription = _object(subscription_raw, "subscription")
            subscription_id = subscription.get("id")
            if subscription_id is not None:
                if not isinstance(subscription_id, (str, int)) or isinstance(
                    subscription_id,
                    bool,
                ):
                    raise CaktoPayloadError("subscription.id must be string or integer")
                external_subscription_id = str(subscription_id)
        occurred_at = _business_time(event_type, data, created_at)
        return CaktoWebhookInboxEntry(
            event_key=f"{event_type.value}:{order_id}",
            event_type=event_type,
            order_id=order_id,
            external_product_id=product_id,
            external_offer_id=offer_id,
            external_customer_id=str(customer_id),
            order_status=order_status,
            occurred_at=occurred_at,
            callback_token=callback_raw,
            external_subscription_id=external_subscription_id,
            payload_sha256=payload_hash,
            received_at=received_at,
            external_customer_email=customer_email,
        )


class CaktoWebhookReceiver:
    """Authenticate first, then durably accept sanitized event metadata."""

    def __init__(
        self,
        *,
        verifier: CaktoWebhookVerifier,
        unit_of_work_factory: CaktoUnitOfWorkFactory,
        metrics: CaktoMetricSink | None = None,
    ) -> None:
        self._verifier = verifier
        self._uow_factory = unit_of_work_factory
        self._metrics = metrics or NullCaktoMetricSink()

    def receive(
        self,
        *,
        raw_body: bytes,
        timestamp_header: str,
        signature_header: str,
        received_at: datetime,
    ) -> tuple[CaktoWebhookInboxEntry, ...]:
        entries = self._verifier.verify_and_parse(
            raw_body=raw_body,
            timestamp_header=timestamp_header,
            signature_header=signature_header,
            received_at=received_at,
        )
        accepted: list[CaktoWebhookInboxEntry] = []
        with self._uow_factory() as uow:
            for entry in entries:
                persisted, replay = uow.commercial.receive_cakto_event(entry)
                accepted.append(persisted)
                self._metrics.increment(
                    "nfcore_cakto_webhooks_total",
                    operation=entry.event_type.value,
                    outcome="replay" if replay else "accepted",
                )
            uow.commit()
        return tuple(accepted)


class CaktoCommercialProcessor:
    """Process accepted Cakto events without acquiring any fiscal authority."""

    _RETRY_DELAYS = (5, 60, 150, 360, 1800)
    _ACTIVE_EVENTS = frozenset(
        {
            CaktoWebhookEvent.PURCHASE_APPROVED,
            CaktoWebhookEvent.SUBSCRIPTION_CREATED,
            CaktoWebhookEvent.SUBSCRIPTION_RENEWED,
            CaktoWebhookEvent.SUBSCRIPTION_RESUMED,
            CaktoWebhookEvent.SUBSCRIPTION_LATE_RECOVERED,
        }
    )
    _INFORMATIONAL_EVENTS = frozenset(
        {
            CaktoWebhookEvent.CHECKOUT_ABANDONMENT,
            CaktoWebhookEvent.PURCHASE_REFUSED,
            CaktoWebhookEvent.PIX_GENERATED,
            CaktoWebhookEvent.BOLETO_GENERATED,
            CaktoWebhookEvent.PICPAY_GENERATED,
            CaktoWebhookEvent.OPENFINANCE_NUBANK_GENERATED,
        }
    )

    def __init__(
        self,
        *,
        unit_of_work_factory: CaktoUnitOfWorkFactory,
        canonical_bridge: CaktoCanonicalCommercialBridge | None = None,
        metrics: CaktoMetricSink | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._canonical_bridge = canonical_bridge
        self._metrics = metrics or NullCaktoMetricSink()

    def process_due(self, *, now: datetime, limit: int = 100) -> CaktoProcessingResult:
        _aware(now, "now")
        if limit < 1 or limit > 1000:
            raise CaktoPayloadError("limit must be between 1 and 1000")
        with self._unit_of_work_factory() as uow:
            due = uow.commercial.list_due_cakto_events(now, limit)
        succeeded = retry_wait = dead_letter = stale_ignored = 0
        for entry in due:
            try:
                outcome = self._process_one(entry)
            except CaktoPermanentProcessingError as exc:
                self._dead_letter(entry, str(exc))
                dead_letter += 1
            except CaktoTransientProcessingError as exc:
                if entry.attempt_count >= len(self._RETRY_DELAYS) - 1:
                    self._dead_letter(entry, str(exc))
                    dead_letter += 1
                else:
                    delay = self._RETRY_DELAYS[entry.attempt_count]
                    self._retry(entry, now + timedelta(seconds=delay), str(exc))
                    retry_wait += 1
            else:
                succeeded += 1
                stale_ignored += int(outcome == "ignored_stale")
        return CaktoProcessingResult(
            claimed=len(due),
            succeeded=succeeded,
            retry_wait=retry_wait,
            dead_letter=dead_letter,
            stale_ignored=stale_ignored,
        )

    def reconcile(
        self,
        snapshot: CaktoReconciliationSnapshot,
    ) -> CaktoReconciliationResult:
        if self._canonical_bridge is None:
            raise CaktoTransientProcessingError(
                "canonical commercial bridge is unavailable"
            )
        with self._unit_of_work_factory() as uow:
            binding = uow.commercial.resolve_cakto_plan_binding(
                snapshot.external_product_id,
                snapshot.external_offer_id,
            )
        if binding is None or not binding.enabled:
            raise CaktoTransientProcessingError("Cakto plan mapping is not configured")
        result = self._canonical_bridge.reconcile(snapshot, binding)
        self._metrics.increment(
            "nfcore_cakto_reconciliation_total",
            outcome="drift" if result.drift else "aligned",
        )
        return result

    def _process_one(self, entry: CaktoWebhookInboxEntry) -> str:
        with self._unit_of_work_factory() as uow:
            current_entry = uow.commercial.get_cakto_event(entry.event_key)
            if current_entry is None:
                raise CaktoPermanentProcessingError("durable Cakto inbox entry disappeared")
            if current_entry.status is CaktoInboxStatus.PROCESSED:
                return current_entry.outcome_reference or "already_processed"
            if current_entry.status is CaktoInboxStatus.DEAD_LETTER:
                raise CaktoPermanentProcessingError(
                    "dead-letter entry requires governed reprocessing"
                )
            if current_entry.event_type in self._INFORMATIONAL_EVENTS:
                uow.commercial.mark_cakto_processed(
                    current_entry.event_key,
                    tenant_id=None,
                    outcome_reference="informational_no_entitlement_change",
                )
                uow.commit()
                return "informational_no_entitlement_change"
            binding = uow.commercial.resolve_cakto_plan_binding(
                current_entry.external_product_id,
                current_entry.external_offer_id,
            )
            if binding is None or not binding.enabled:
                raise CaktoTransientProcessingError(
                    "Cakto plan mapping is not configured"
                )
            if self._canonical_bridge is None:
                raise CaktoTransientProcessingError(
                    "canonical commercial bridge is unavailable"
                )

        outcome_reference = self._canonical_bridge.process(
            current_entry,
            binding,
        )
        with self._unit_of_work_factory() as uow:
            uow.commercial.mark_cakto_processed(
                current_entry.event_key,
                tenant_id=None,
                outcome_reference=outcome_reference,
            )
            uow.commit()
        self._metrics.increment(
            "nfcore_cakto_processing_total",
            operation=current_entry.event_type.value,
            outcome="canonical",
        )
        return outcome_reference

    @classmethod
    def _target_status(cls, entry: CaktoWebhookInboxEntry) -> CaktoEntitlementStatus | None:
        if entry.event_type in cls._ACTIVE_EVENTS:
            if entry.order_status != "paid":
                return None
            return CaktoEntitlementStatus.ACTIVE
        if entry.event_type in {
            CaktoWebhookEvent.SUBSCRIPTION_RENEWAL_REFUSED,
            CaktoWebhookEvent.SUBSCRIPTION_LATE,
        }:
            return CaktoEntitlementStatus.GRACE
        if entry.event_type is CaktoWebhookEvent.SUBSCRIPTION_PAUSED:
            return CaktoEntitlementStatus.SUSPENDED
        if entry.event_type in {
            CaktoWebhookEvent.SUBSCRIPTION_CANCELED,
            CaktoWebhookEvent.REFUND,
            CaktoWebhookEvent.CHARGEBACK,
        }:
            return CaktoEntitlementStatus.CANCELED
        return None

    @staticmethod
    def _ensure_tenant(
        store: CaktoCommercialStore,
        external_customer_id: str,
        created_at: datetime,
    ) -> CaktoCommercialTenant:
        existing = store.get_cakto_tenant_by_customer(external_customer_id)
        expected_id = commercial_tenant_id(external_customer_id)
        if existing is not None:
            if existing.tenant_id != expected_id:
                raise CaktoPermanentProcessingError("cross-tenant commercial identity conflict")
            return existing
        tenant = CaktoCommercialTenant(
            tenant_id=expected_id,
            external_customer_id=external_customer_id,
            created_at=created_at,
        )
        return store.put_cakto_tenant(tenant)

    @staticmethod
    def _next_entitlement(
        *,
        current: CaktoCommercialEntitlement | None,
        binding: CaktoPlanBinding,
        tenant_id: str,
        status: CaktoEntitlementStatus,
        event_at: datetime,
        event_key: str,
    ) -> CaktoCommercialEntitlement:
        if current is not None and event_at < current.last_event_at:
            return current
        return CaktoCommercialEntitlement(
            tenant_id=tenant_id,
            plan_id=binding.plan_id,
            entitlement_ids=binding.entitlement_ids,
            status=status,
            last_event_at=event_at,
            last_event_key=event_key,
        )

    def _retry(
        self,
        entry: CaktoWebhookInboxEntry,
        next_attempt_at: datetime,
        error: str,
    ) -> None:
        with self._unit_of_work_factory() as uow:
            uow.commercial.mark_cakto_retry(
                entry.event_key,
                next_attempt_at=next_attempt_at,
                error=_safe_error(error),
            )
            uow.commit()
        self._metrics.increment(
            "nfcore_cakto_processing_total",
            operation=entry.event_type.value,
            outcome="retry_wait",
        )

    def _dead_letter(self, entry: CaktoWebhookInboxEntry, error: str) -> None:
        with self._unit_of_work_factory() as uow:
            uow.commercial.mark_cakto_dead_letter(
                entry.event_key,
                error=_safe_error(error),
            )
            uow.commit()
        self._metrics.increment(
            "nfcore_cakto_processing_total",
            operation=entry.event_type.value,
            outcome="dead_letter",
        )


def commercial_tenant_id(external_customer_id: str) -> str:
    customer = _text(external_customer_id, "external_customer_id", 160)
    digest = hashlib.sha256(customer.encode("utf-8")).hexdigest()[:24]
    return f"cakto-{digest}"


def _reconciled_status(status: CaktoExternalSubscriptionStatus) -> CaktoEntitlementStatus:
    if status is CaktoExternalSubscriptionStatus.ACTIVE:
        return CaktoEntitlementStatus.ACTIVE
    if status is CaktoExternalSubscriptionStatus.PAUSED:
        return CaktoEntitlementStatus.SUSPENDED
    return CaktoEntitlementStatus.CANCELED


def _business_time(
    event_type: CaktoWebhookEvent,
    data: dict[str, Any],
    created_at: datetime,
) -> datetime:
    preferred: str | None = None
    if event_type is CaktoWebhookEvent.PURCHASE_APPROVED:
        preferred = "paidAt"
    elif event_type is CaktoWebhookEvent.REFUND:
        preferred = "refundedAt"
    elif event_type is CaktoWebhookEvent.CHARGEBACK:
        preferred = "chargedbackAt"
    elif event_type is CaktoWebhookEvent.SUBSCRIPTION_CANCELED:
        preferred = "canceledAt"
    if preferred is None or data.get(preferred) is None:
        return created_at
    return _iso_datetime(data.get(preferred), preferred)


def _text(value: object, field_name: str, max_length: int = 256) -> str:
    if not isinstance(value, str):
        raise CaktoPayloadError(f"{field_name} must be string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise CaktoPayloadError(f"{field_name} must contain 1..{max_length} characters")
    return normalized


def _token(value: str, field_name: str) -> str:
    normalized = _text(value, field_name, 128).lower()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(character not in allowed for character in normalized):
        raise CaktoPayloadError(f"{field_name} contains invalid token characters")
    return normalized


def _object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaktoPayloadError(f"{field_name} must be object")
    return value


def _optional_email(value: str) -> str | None:
    """Normalize an externally-reported email as an unverified delivery hint.

    This is never treated as proof of identity (see ``CommercialClaimService``
    and ``CaktoClaimAutomationService``). A value that is present but does not
    look like a usable address is dropped rather than rejecting the whole
    authenticated webhook event over optional, provider-supplied metadata.
    """

    normalized = value.strip().casefold()
    if (
        not normalized
        or len(normalized) > 320
        or normalized.count("@") != 1
        or normalized.startswith("@")
        or normalized.endswith("@")
        or "\r" in normalized
        or "\n" in normalized
    ):
        return None
    return normalized


def _iso_datetime(value: object, field_name: str) -> datetime:
    text = _text(value, field_name, 80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaktoPayloadError(f"{field_name} must be ISO-8601") from exc
    _aware(parsed, field_name)
    return parsed


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CaktoPayloadError(f"{field_name} must be timezone-aware")


def _safe_error(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized[:240] or "processing_error"


def utc_now() -> datetime:
    return datetime.now(UTC)
