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
        try:
            return self._check(case)
        except Exception:  # noqa: BLE001
            return ReconResult(False, "unknown", "recon_error", unknown=True)

    def _check(self, case: dict) -> ReconResult:
        refs = case.get("source_refs") or {}
        live = case.get("live_statuses") or {}
        if case.get("already_paid"):
            return ReconResult(True, "paid", "case_flag")
        unpaid = False
        for kind, ref_key, live_key in (
            ("payment", "payment_id", "payment"),
            ("order", "order_id", "order"),
            ("invoice", "invoice_id", "invoice"),
            ("payment_link", "payment_link_id", "payment_link"),
        ):
            entity_id = refs.get(ref_key)
            if not entity_id:
                continue
            entity, failed = self._fetch(kind, entity_id)
            webhook_status = live.get(live_key)
            if failed:
                if webhook_status in PAID_STATES:
                    return ReconResult(True, str(webhook_status), f"{kind}_webhook")
                if webhook_status or unpaid:
                    unpaid = True
                    continue
                return ReconResult(False, "unknown", f"{kind}_fetch_failed", unknown=True)
            status = (entity or {}).get("status") or "unknown"
            if status in PAID_STATES:
                return ReconResult(True, status, kind)
            if status != "unknown":
                unpaid = True
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
        acquirer = payment.get("acquirer_data") or {} if isinstance(payment, dict) else {}
        if payment.get("status") in PAID_STATES and (acquirer.get("rrn") or acquirer.get("utr")):
            return True
        return bool(payment.get("settled") is True)

    def _fetch(self, kind: str, entity_id: str) -> tuple[dict | None, bool]:
        try:
            raw = getattr(self.payments, f"fetch_{kind}")(entity_id)
        except Exception:  # noqa: BLE001
            return None, True
        if raw is None:
            return None, False
        if isinstance(raw, dict):
            return raw, False
        try:
            return dict(raw), False
        except (TypeError, ValueError):
            return None, True
