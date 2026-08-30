from __future__ import annotations

import json

from rekha.config import settings

CLOSED_TOOLS = {
    "silent_retry_same_instrument",
    "create_payment_link",
    "issue_or_notify_invoice",
    "send_subscription_update_method_link",
    "schedule_mandate_presentment",
    "apply_merchant_offer",
    "capture_promise_to_pay",
    "renegotiate_promise",
    "send_template_message",
    "escalate_to_merchant",
    "suppress_and_stop",
    "recommend_service_hold",
    "alert_engineering",
    "refuse_legal_step",
}


def advise(case: dict, diagnosis: dict) -> dict | None:
    if not settings.openai_api_key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    base = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": settings.openai_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Propose one recovery tool as JSON {\"action\": \"...\"}. "
                    "Pick only from the allowlist. You do not execute anything."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "case_id": case.get("id"),
                        "diagnosis": diagnosis,
                        "amount_paise": case.get("amount_paise"),
                        "error_reason": case.get("error_reason"),
                        "tools": sorted(CLOSED_TOOLS),
                    },
                    default=str,
                ),
            },
        ],
    }
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "content-type": "application/json"},
            json=body,
            timeout=8.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # noqa: BLE001
        return None
    return None


def filter_proposal(proposal: dict | None) -> dict | None:
    if not proposal:
        return None
    if proposal.get("action") not in CLOSED_TOOLS:
        return None
    return proposal
