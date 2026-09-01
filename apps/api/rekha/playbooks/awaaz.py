from __future__ import annotations


def propose_voice() -> dict:
    return {
        "action": "send_template_message",
        "channel": "voice",
        "template_id": "svc_voice_pay",
        "engine": "awaaz",
        "reason": "high_arpc_last_resort_voice",
    }
