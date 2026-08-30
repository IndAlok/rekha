from __future__ import annotations

from datetime import date

from rekha.msmed import compute_position


def propose_b2b(case: dict) -> dict:
    dpd = int(case.get("days_past_due") or 0)
    if case.get("strategic_tier") == "key" and dpd < 30:
        return _link("relationship_aware_email_only")
    if dpd >= 60:
        return {
            "action": "escalate_to_merchant",
            "channel": "internal",
            "template_id": None,
            "engine": "b2b_chaser",
            "reason": "human_escalation_after_60_dpd",
        }
    msme = _msme_position(case)
    if msme is not None and msme["days_past_due"] >= 45:
        # The tax message: factual, computable, aimed at the buyer's own
        # finance team. Delayed-payment interest is a number, not a threat.
        return {
            **_link("msmed_s16_factual_email"),
            "template_id": "svc_msme_email",
            "msmed_interest_inr": msme["interest_inr"],
            "msmed_interest_paise": msme["interest_paise"],
            "msmed_disallowance_paise": msme["disallowance_paise"],
        }
    if dpd >= 30:
        return {
            "action": "escalate_to_merchant",
            "channel": "internal",
            "template_id": None,
            "engine": "b2b_chaser",
            "reason": "human_escalation_after_30_dpd",
        }
    return {**_link("soa_plus_link"), "accept_partial": True}


def propose_legal_refuse() -> dict:
    return {
        "action": "refuse_legal_step",
        "channel": "internal",
        "template_id": None,
        "engine": "b2b_chaser",
        "reason": "legal_steps_are_human_only",
    }


def _msme_position(case: dict) -> dict | None:
    if not case.get("supplier_msme", False):
        return None
    acceptance = case.get("acceptance_date")
    if not acceptance:
        return None
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    today = date.fromisoformat(case.get("as_of_date") or _dt.now(_UTC).date().isoformat())
    position = compute_position(
        acceptance_date=date.fromisoformat(acceptance),
        today=today,
        amount_paise=int(case.get("amount_paise") or 0),
        agreed_days=case.get("agreed_payment_days"),
        supplier_msme=True,
        financial_year_end=date(today.year, 3, 31) if today.month <= 3 else None,
    )
    if not position.eligible:
        return None
    return {
        "days_past_due": position.days_past_due,
        "interest_paise": position.interest_paise,
        "interest_inr": f"{position.interest_paise / 100:.2f}",
        "disallowance_paise": position.tax_disallowance_paise,
    }


def _link(reason: str) -> dict:
    return {
        "action": "create_payment_link",
        "channel": "email",
        "template_id": "svc_invoice_email",
        "engine": "b2b_chaser",
        "reason": reason,
    }
