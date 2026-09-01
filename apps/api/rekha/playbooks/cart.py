from __future__ import annotations


def propose_cart(case: dict) -> dict:
    if case.get("recoverability_tier") == "low":
        return _stop("low_recoverability_suppressed")
    if not case.get("contact_captured"):
        return _stop("no_consented_identity")
    return {
        "action": "create_payment_link",
        "channel": "whatsapp",
        "template_id": "svc_cart_wa",
        "engine": "cart_rescue",
        "reason": "one_nudge",
        "max_touches": 1,
    }


def _stop(reason: str) -> dict:
    return {
        "action": "suppress_and_stop",
        "channel": None,
        "template_id": None,
        "engine": "cart_rescue",
        "reason": reason,
    }
