from __future__ import annotations

from rekha.clocks import next_ist_midnight, next_salary_window
from rekha.diagnose import Diagnosis
from rekha.taxonomy import Recoverability


def propose_payment(case: dict, diagnosis: Diagnosis, now) -> dict:
    reason = diagnosis.error_reason
    if diagnosis.recoverability_class == Recoverability.T:
        return _act("suppress_and_stop", reason="terminal_no_retry")
    if reason == "payment_risk_check_failed":
        return _act("suppress_and_stop", reason="risk_decline_no_retry")
    if diagnosis.reconcile_first:
        return _act(
            "silent_retry_same_instrument",
            reason="deemed_after_reconcile",
            extra={"needs_reconcile": True},
        )
    if diagnosis.recoverability_class == Recoverability.R:
        return _act("silent_retry_same_instrument", reason="soft_infra")
    if reason == "insufficient_funds":
        return _act(
            "silent_retry_same_instrument",
            reason="iff_salary_window",
            extra={"send_after": next_salary_window(now).isoformat()},
        )
    if reason in {"transaction_daily_limit_exceeded", "transaction_frequency_limit_exceeded"}:
        return _act(
            "silent_retry_same_instrument",
            reason="limit_resets_tomorrow",
            extra={"send_after": next_ist_midnight(now).isoformat()},
        )
    if diagnosis.recoverability_class == Recoverability.I:
        return _act(
            "send_subscription_update_method_link",
            channel="email",
            template_id="svc_card_update_email",
            reason="instrument_dead",
        )
    if reason == "payment_cancelled":
        return {
            "action": "create_payment_link",
            "channel": "whatsapp",
            "template_id": "svc_cart_wa",
            "engine": "cart_rescue",
            "reason": "in_session_intent",
        }
    return _act(
        "create_payment_link",
        channel="email",
        template_id="svc_pay_link_email",
        reason="customer_action_link",
    )


def propose_class_b() -> dict:
    return _act("alert_engineering", channel="internal", template_id="eng_class_b", reason="class_b_no_outreach")


def propose_downtime() -> dict:
    return _act("suppress_and_stop", reason="downtime_no_woodpecker")


def _act(
    action: str,
    *,
    channel: str | None = None,
    template_id: str | None = None,
    reason: str,
    extra: dict | None = None,
) -> dict:
    row = {
        "action": action,
        "channel": channel,
        "template_id": template_id,
        "engine": "payment_doctor",
        "reason": reason,
    }
    if extra:
        row.update(extra)
    return row
