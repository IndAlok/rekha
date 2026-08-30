from __future__ import annotations

from dataclasses import dataclass

PAID_STATES = {"paid", "captured", "authorized", "partially_paid"}


@dataclass
class ReconResult:
    already_paid: bool
    live_status: str
    source: str
    unknown: bool = False


class ReconciliationGuard:
    """Re-fetch before outreach so a late auth is not billed twice.

    Fetch failures never crash the pipeline. An unknown status is treated as
    a fail-closed block on outreach. The raw error is surfaced for the audit
    trail. Unknown is not credited as a recovery.
    """

    def __init__(self, payments) -> None:
        self.payments = payments

    def check(self, case: dict) -> ReconResult:
        refs = case.get("source_refs") or {}
        if case.get("already_paid"):
            return ReconResult(True, "paid", "case_flag")
        payment_id = refs.get("payment_id")
        if payment_id:
            payment, failed = self._fetch("payment", payment_id)
            if failed:
                return ReconResult(False, "unknown", "payment_fetch_failed", unknown=True)
            status = (payment or {}).get("status", "unknown")
            if status in PAID_STATES:
                return ReconResult(True, status, "payment")
        order_id = refs.get("order_id")
        if order_id:
            order, failed = self._fetch("order", order_id)
            if failed:
                return ReconResult(False, "unknown", "order_fetch_failed", unknown=True)
            status = (order or {}).get("status")
            if status in PAID_STATES:
                return ReconResult(True, status, "order")
        invoice_id = refs.get("invoice_id")
        if invoice_id:
            inv, failed = self._fetch("invoice", invoice_id)
            if failed:
                return ReconResult(False, "unknown", "invoice_fetch_failed", unknown=True)
            if (inv or {}).get("status") in PAID_STATES:
                return ReconResult(True, inv["status"], "invoice")
        link_id = refs.get("payment_link_id")
        if link_id:
            link, failed = self._fetch("payment_link", link_id)
            if failed:
                return ReconResult(False, "unknown", "payment_link_fetch_failed", unknown=True)
            if (link or {}).get("status") in PAID_STATES:
                return ReconResult(True, link["status"], "payment_link")
        return ReconResult(False, "unpaid", "none")

    def deep_check(self, case: dict) -> bool:
        """Settlement-level check for indeterminate outcomes (deemed
        transactions, duplicate RRNs). True only when we can positively
        confirm the money settled upstream. never guess."""
        refs = case.get("source_refs") or {}
        payment_id = refs.get("payment_id")
        if not payment_id:
            return False
        payment, failed = self._fetch("payment", payment_id)
        if failed or not payment:
            return False
        acquirer = payment.get("acquirer_data") or {}
        if payment.get("status") in PAID_STATES and (acquirer.get("rrn") or acquirer.get("utr")):
            return True
        return bool(payment.get("settled") is True)

    def _fetch(self, kind: str, entity_id: str) -> tuple[dict | None, bool]:
        try:
            return getattr(self.payments, f"fetch_{kind}")(entity_id), False
        except Exception:  # noqa: BLE001
            return None, True
