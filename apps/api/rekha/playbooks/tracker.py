from __future__ import annotations


def propose_promise(case: dict) -> dict:
    if case.get("ptp_breached"):
        return {
            "action": "create_payment_link",
            "channel": "email",
            "template_id": "svc_ptp_remind",
            "engine": "promise_tracker",
            "reason": "one_reminder_after_breach",
        }
    return {
        "action": "suppress_and_stop",
        "channel": None,
        "template_id": None,
        "engine": "promise_tracker",
        "reason": "freeze_until_promised_date",
    }
