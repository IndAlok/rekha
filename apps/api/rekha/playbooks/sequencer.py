from __future__ import annotations

from rekha.clocks import next_upi_offpeak
from rekha.diagnose import Diagnosis
from rekha.taxonomy import Recoverability


def propose_mandate(case: dict, diagnosis: Diagnosis, now) -> dict:
    rail = (case.get("mandate") or {}).get("rail", "upi")
    if diagnosis.recoverability_class == Recoverability.I:
        return {
            "action": "create_payment_link",
            "channel": "sms",
            "template_id": "svc_pay_link_sms",
            "engine": "mandate_sequencer",
            "reason": "mandate_dead_one_time_link",
        }
    send_after = next_upi_offpeak(now).isoformat() if rail == "upi" else None
    return {
        "action": "schedule_mandate_presentment",
        "channel": "sms",
        "template_id": "svc_pdn_sms",
        "engine": "mandate_sequencer",
        "send_after": send_after,
        "reason": "reason_aware_budgeted_retry",
    }


def propose_holiday() -> dict:
    return {
        "action": "suppress_and_stop",
        "channel": None,
        "template_id": None,
        "engine": "mandate_sequencer",
        "reason": "bank_holiday_no_presentment",
    }


def propose_preflight_fail(reason: str | None) -> dict:
    return {
        "action": "create_payment_link",
        "channel": "email",
        "template_id": "svc_pay_link_email",
        "engine": "mandate_sequencer",
        "reason": reason,
    }
