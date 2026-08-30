from __future__ import annotations

from typing import Any

from rekha.config import settings


def assert_test_mode(key_id: str | None = None) -> str:
    key_id = key_id if key_id is not None else settings.razorpay_key_id
    if not key_id:
        raise RuntimeError("no_razorpay_key")
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError("live_keys_forbidden")
    return key_id


class RazorpayLive:
    def __init__(self) -> None:
        key = assert_test_mode()
        try:
            import razorpay  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pip install rekha[razorpay]") from exc
        self.client = razorpay.Client(auth=(key, settings.razorpay_key_secret))
        self.created_links = 0
        self.budget = settings.payment_link_budget

    def fetch_payment(self, payment_id: str) -> dict[str, Any] | None:
        return self.client.payment.fetch(payment_id)

    def fetch_order(self, order_id: str) -> dict[str, Any] | None:
        return self.client.order.fetch(order_id)

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        return self.client.subscription.fetch(subscription_id)

    def fetch_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        return self.client.invoice.fetch(invoice_id)

    def fetch_payment_link(self, link_id: str) -> dict[str, Any] | None:
        return self.client.payment_link.fetch(link_id)

    def list_unpaid_invoices(self, subscription_id: str) -> list[dict[str, Any]]:
        page = self.client.invoice.all({"subscription_id": subscription_id})
        return [i for i in page.get("items", []) if i.get("status") in {"issued", "partially_paid"}]

    def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
        if self.created_links >= self.budget:
            raise RuntimeError("test_mode_payment_link_budget_exceeded")
        link = self.client.payment_link.create(kwargs)
        self.created_links += 1
        return link

    def notify_link(self, link_id: str, medium: str) -> dict[str, Any]:
        return self.client.payment_link.notify_by(link_id, medium)

    def create_invoice(self, **kwargs: Any) -> dict[str, Any]:
        return self.client.invoice.create(kwargs)

    def notify_invoice(self, invoice_id: str, medium: str) -> dict[str, Any]:
        return self.client.invoice.notify_by(invoice_id, medium)

    def mark_paid(self, entity: str, entity_id: str) -> dict[str, Any]:
        raise RuntimeError("mark_paid is sandbox-only")

    def retry_payment(self, payment_id: str, notes: dict | None = None) -> dict[str, Any]:
        return {"ok": False, "reason": "silent_retry_sandbox_only", "simulated": False, "payment_id": payment_id}
