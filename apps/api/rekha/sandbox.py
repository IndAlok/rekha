from __future__ import annotations

import hashlib
from typing import Any


def _id(prefix: str, key: str) -> str:
    digest = hashlib.sha1(key.encode()).hexdigest()[:14]
    return f"{prefix}_{digest}"


class UnavailablePayments:
    """Fail-closed stand-in when razorpay_test cannot start in prod."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("payments_adapter_unavailable")


class RazorpaySandbox:
    def __init__(self, budget: int | None = None) -> None:
        if budget is None:
            from rekha.config import settings

            budget = settings.payment_link_budget
        self.budget = budget
        self.links: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.subscriptions: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.created_links = 0

    def seed_entity(self, kind: str, entity_id: str, payload: dict) -> None:
        getattr(self, f"{kind}s")[entity_id] = payload

    def fetch_payment(self, payment_id: str) -> dict[str, Any] | None:
        return self.payments.get(payment_id)

    def fetch_order(self, order_id: str) -> dict[str, Any] | None:
        return self.orders.get(order_id)

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        return self.subscriptions.get(subscription_id)

    def fetch_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        return self.invoices.get(invoice_id)

    def fetch_payment_link(self, link_id: str) -> dict[str, Any] | None:
        return self.links.get(link_id)

    def list_unpaid_invoices(self, subscription_id: str) -> list[dict[str, Any]]:
        return [
            inv
            for inv in self.invoices.values()
            if inv.get("subscription_id") == subscription_id and inv.get("status") in {"issued", "partially_paid"}
        ]

    def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
        case_id = (kwargs.get("notes") or {}).get("case_id", "anon")
        attempt = (kwargs.get("notes") or {}).get("attempt_no", "0")
        receipt = kwargs.get("reference_id") or _id("rcpt", f"{case_id}:{attempt}")[:40]
        link_id = _id("plink", receipt)
        if link_id in self.links:
            return self.links[link_id]
        if self.budget > 0 and self.created_links >= self.budget:
            raise RuntimeError("test_mode_payment_link_budget_exceeded")
        link = {
            "id": link_id,
            "entity": "payment_link",
            "amount": kwargs["amount"],
            "currency": kwargs.get("currency", "INR"),
            "status": "created",
            "short_url": f"https://rzp.io/i/{link_id[-8:]}",
            "reference_id": receipt,
            "notes": kwargs.get("notes") or {},
            "accept_partial": kwargs.get("accept_partial", False),
            "upi_link": kwargs.get("upi_link", False),
        }
        if link["upi_link"] and link["accept_partial"]:
            raise ValueError("upi_links_cannot_accept_partial")
        self.links[link_id] = link
        self.created_links += 1
        return link

    def notify_link(self, link_id: str, medium: str) -> dict[str, Any]:
        if medium not in {"sms", "email"}:
            raise ValueError("invalid_medium")
        if link_id not in self.links:
            raise KeyError(link_id)
        return {"success": True, "medium": medium}

    def create_invoice(self, **kwargs: Any) -> dict[str, Any]:
        inv_id = _id("inv", str(kwargs.get("notes", {}).get("case_id", "x")))
        inv = {
            "id": inv_id,
            "status": "issued",
            "amount": kwargs["amount"],
            "amount_due": kwargs["amount"],
            "short_url": f"https://rzp.io/i/{inv_id[-8:]}",
            "notes": kwargs.get("notes") or {},
            "subscription_id": kwargs.get("subscription_id"),
        }
        self.invoices[inv_id] = inv
        return inv

    def notify_invoice(self, invoice_id: str, medium: str) -> dict[str, Any]:
        return {"success": True, "medium": medium, "id": invoice_id}

    def mark_paid(self, entity: str, entity_id: str) -> dict[str, Any]:
        store = getattr(self, f"{entity}s")
        row = store[entity_id]
        row["status"] = "paid"
        if "amount_due" in row:
            row["amount_due"] = 0
        if "amount_paid" in row:
            row["amount_paid"] = row.get("amount", 0)
        return row

    def retry_payment(self, payment_id: str, notes: dict | None = None) -> dict[str, Any]:
        original = self.payments.get(payment_id) or {"id": payment_id, "status": "failed"}
        new_id = _id("pay", f"retry:{payment_id}:{(notes or {}).get('attempt_no', '0')}")
        row = {**original, "id": new_id, "status": "created", "retry_of": payment_id, "notes": notes or {}}
        self.payments[new_id] = row
        return {"ok": True, "payment_id": new_id, "simulated": False}


class FileInbox:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, *, channel: str, to: str, template_id: str, body: str, case_id: str) -> dict:
        rec = {
            "channel": channel,
            "to": to,
            "template_id": template_id,
            "body": body,
            "case_id": case_id,
        }
        self.messages.append(rec)
        return {"ok": True, **rec}
