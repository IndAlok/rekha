from __future__ import annotations

from rekha.diagnose import Diagnosis
from rekha.taxonomy import Recoverability


def propose_subscription(case: dict, diagnosis: Diagnosis) -> dict:
    sub = case.get("subscription") or {}
    native_attempts = int(sub.get("auth_attempts") or case.get("native_attempts") or 0)
    status = sub.get("status") or case.get("subscription_status")
    if status == "pending" and native_attempts < 3 and not case.get("native_exhausted"):
        return _act("suppress_and_stop", reason="dormant_during_native_retry")
    if status == "authenticated" and case.get("would_pause_authenticated_sub"):
        return _act("suppress_and_stop", reason="never_pause_authenticated")
    if diagnosis.recoverability_class == Recoverability.I or status == "halted":
        return _act(
            "send_subscription_update_method_link",
            channel="email",
            template_id="svc_card_update_email",
            reason="halted_or_dead_instrument_plus_arrears",
            extra={"collect_arrears": True},
        )
    return _act(
        "create_payment_link",
        channel="email",
        template_id="svc_pay_link_email",
        reason="arrears_link",
        extra={"collect_arrears": True},
    )


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
        "engine": "subscription_saver",
        "reason": reason,
    }
    if extra:
        row.update(extra)
    return row
