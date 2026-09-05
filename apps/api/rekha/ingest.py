from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from rekha.config import settings
from rekha.db.time import coerce_utc

# Events that mean money moved in, not out. They close cases and attribute
# recovery. They must never open a dunning case.
RECOVERY_EVENTS = {
    "payment.authorized",
    "payment.captured",
    "order.paid",
    "payment_link.paid",
    "payment_link.partially_paid",
    "invoice.paid",
    "invoice.partially_paid",
    "subscription.charged",
    "virtual_account.credited",
}

PAIDISH_PAYMENT_STATES = {"captured", "authorized", "partially_paid"}


def webhook_hmac(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str | None = None) -> bool:
    secret = secret if secret is not None else settings.razorpay_webhook_secret
    if not secret:
        # Fail closed outside dev: an unverified trigger can send customer
        # messages, so only the dev environment may accept it.
        return settings.rekha_env == "dev"
    if not signature:
        return False
    try:
        return hmac.compare_digest(webhook_hmac(raw_body, secret), signature)
    except (TypeError, ValueError):
        return False


@dataclass
class Inbox:
    events: dict[str, dict] = field(default_factory=dict)

    def accept(self, event_id: str, event_type: str, payload: dict) -> tuple[dict, bool]:
        if event_id in self.events:
            return self.events[event_id], False
        rec = {
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload,
            "received_at": datetime.now(UTC).isoformat(),
            "processed": False,
        }
        self.events[event_id] = rec
        return rec, True


def canonical_case_id(refs: dict, *, customer_id: str | None = None, fallback: str) -> str:
    """Stable case identity per obligation, so a payment.failed and the later
    payment.captured for the same order land on the same case."""
    for key in ("order_id", "invoice_id", "payment_link_id", "subscription_id", "payment_id"):
        value = refs.get(key)
        if value:
            return f"case-{key.split('_')[0]}-{value}"
    if customer_id:
        return f"case-cust-{customer_id}"
    return fallback


def event_to_case(event: dict, *, case_id: str | None = None) -> dict:
    payload = event.get("payload") or event
    # Defensive unwrap: tolerate a full webhook envelope nested one level deep.
    if isinstance(payload.get("payload"), dict) and payload.get("event"):
        payload = payload["payload"]
    entity = _entity(payload)
    payment = entity if entity.get("entity") == "payment" or "error_reason" in entity else payload.get("payment") or {}
    if isinstance(payment, dict) and "entity" in payment and isinstance(payment["entity"], dict):
        payment = payment["entity"]
    error = payment.get("error") or {}
    raw_amount = entity.get("amount") or payment.get("amount") or event.get("amount_paise") or 0
    try:
        amount = int(raw_amount)
    except (TypeError, ValueError):
        amount = 0
    event_type = event.get("event_type") or event.get("event") or ""
    refs = {
        "payment_id": (payment.get("id") or entity.get("id")) if entity.get("entity") == "payment" else payment.get("id"),
        "order_id": payment.get("order_id") or entity.get("order_id"),
        "subscription_id": entity.get("subscription_id") or entity.get("id")
        if event_type.startswith("subscription")
        else entity.get("subscription_id"),
        "invoice_id": entity.get("id") if entity.get("entity") == "invoice" else entity.get("invoice_id"),
        "payment_link_id": entity.get("id") if entity.get("entity") == "payment_link" else None,
    }
    refs = {k: v for k, v in refs.items() if v}
    notes = entity.get("notes") or payment.get("notes") or {}
    if not isinstance(notes, dict):
        notes = {}
    noted_case = notes.get("case_id") or event.get("case_id")
    customer_block = payload.get("customer") or {}
    if not isinstance(customer_block, dict):
        customer_block = {}
    consent = (
        customer_block.get("consent_status")
        or event.get("consent_status")
        or ("GRANTED" if customer_block.get("consent") is True else None)
        or ("REVOKED" if customer_block.get("consent") is False else None)
        or "UNKNOWN"
    )
    return {
        "id": case_id
        or noted_case
        or event.get("case_id")
        or canonical_case_id(refs, customer_id=customer_block.get("id") or event.get("customer_id"), fallback=f"evt-{event.get('event_id', 'anon')}"),
        "customer_id": customer_block.get("id") or entity.get("customer_id") or event.get("customer_id") or "cust_unknown",
        "merchant_id": event.get("merchant_id") or "merch_demo",
        "merchant_name": event.get("merchant_name") or (customer_block.get("merchant_name") or "Demo Merchant"),
        "event_type": event_type,
        "loss_class": _loss_class(event_type, entity, payment),
        "amount_paise": amount,
        "currency": entity.get("currency") or payment.get("currency") or "INR",
        "error_reason": error.get("reason") or payment.get("error_reason") or entity.get("error_reason") or "",
        "error_source": error.get("source") or payment.get("error_source") or entity.get("error_source"),
        "live_statuses": {
            key: value
            for key, value in {
                "payment": payment.get("status"),
                "order": (payload.get("order") or {}).get("status") if isinstance(payload.get("order"), dict) else None,
                "invoice": (payload.get("invoice") or {}).get("status") if isinstance(payload.get("invoice"), dict) else None,
            }.items()
            if value
        },
        "source_refs": refs,
        "consent_status": consent,
        "contact": customer_block.get("contact") or customer_block.get("phone") or event.get("contact"),
        "first_name": customer_block.get("first_name") or customer_block.get("name"),
        "contact_captured": bool(customer_block.get("contact") or customer_block.get("phone") or event.get("contact")),
        "contacts_last_7d": event.get("contacts_last_7d", 0),
        "touches_this_case": event.get("touches_this_case", 0),
        "hours_since_failure": _hours_since_failure(entity, payment, event),
        "mandate_attempts_used": event.get("mandate_attempts_used", 0),
        "nach_representations_used": event.get("nach_representations_used", 0),
        "webhook_event_id": event.get("event_id"),
    }


def _hours_since_failure(entity: dict, payment: dict, event: dict) -> float:
    if event.get("hours_since_failure") is not None:
        try:
            return float(event["hours_since_failure"])
        except (TypeError, ValueError):
            pass
    raw = payment.get("created_at") or entity.get("created_at") or event.get("created_at")
    if raw is None:
        return 48.0
    try:
        if isinstance(raw, (int, float)):
            created = datetime.fromtimestamp(float(raw), tz=UTC)
        else:
            created = coerce_utc(str(raw))
            if created is None:
                return 48.0
        return max(0.0, (datetime.now(UTC) - created).total_seconds() / 3600.0)
    except (TypeError, ValueError, OSError):
        return 48.0


def _entity(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("payment", "order", "subscription", "invoice", "payment_link", "entity"):
        block = payload.get(key)
        if isinstance(block, dict) and "entity" in block and isinstance(block["entity"], dict):
            return block["entity"]
        if isinstance(block, dict) and block.get("id"):
            return block
    return payload


def _loss_class(event_type: str, entity: dict, payment: dict) -> str:
    et = (event_type or "").lower()
    if et in RECOVERY_EVENTS:
        return "recovery_event"
    if payment.get("status") in PAIDISH_PAYMENT_STATES:
        return "recovery_event"
    if "subscription" in et:
        return "subscription_failure"
    if "invoice" in et:
        return "b2b_receivable"
    if "payment_link" in et or et == "cart.abandoned":
        return "checkout_abandonment" if et == "cart.abandoned" else "payment_failure"
    if entity.get("entity") == "subscription":
        return "subscription_failure"
    return "payment_failure"


def parse_batch_line(line: str) -> dict:
    return json.loads(line)
