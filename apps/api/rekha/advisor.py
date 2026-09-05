"""Optional live advisor. Playbooks still pick the tool.

The env names stay OPENAI_* because the HTTP dialect is OpenAI chat
completions. The default host is Groq. Eval never calls this.
"""

from __future__ import annotations

import json
import logging

from rekha.config import settings

log = logging.getLogger("rekha.advisor")

GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"
ADVISOR_TIMEOUT_S = 2.5

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


def advisor_configured() -> bool:
    return bool((settings.openai_api_key or "").strip())


def advisor_base() -> str:
    return (settings.openai_base_url or GROQ_BASE).rstrip("/")


def advisor_model() -> str:
    return (settings.openai_model or GROQ_MODEL).strip() or GROQ_MODEL


def advisor_provider() -> str:
    host = advisor_base().lower()
    if "groq.com" in host:
        return "groq"
    if "openrouter.ai" in host:
        return "openrouter"
    if "googleapis.com" in host:
        return "gemini"
    if "openai.com" in host:
        return "openai"
    return "openai_compat"


def advisor_public() -> dict:
    on = advisor_configured()
    return {
        "configured": on,
        "provider": advisor_provider() if on else "off",
        "model": advisor_model() if on else "",
        "live_only": True,
        "eval": "off",
        "timeout_s": ADVISOR_TIMEOUT_S,
        "fallback_model": GROQ_FALLBACK_MODEL,
        "can": ["reason_if_same_action"],
        "cannot": ["pick_tool", "change_channel", "change_amount", "set_send_after", "execute"],
    }


def _extract_json(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text[3:]
        if text.lower().startswith("json"):
            text = text[4:]
        fence = text.rfind("```")
        if fence >= 0:
            text = text[:fence]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def advise(case: dict, diagnosis: dict) -> dict | None:
    if not advisor_configured():
        return None
    try:
        import httpx
    except ImportError:
        return None
    base = advisor_base()
    models = [advisor_model()]
    if GROQ_FALLBACK_MODEL not in models:
        models.append(GROQ_FALLBACK_MODEL)
    payload = {
        "case_id": case.get("id"),
        "diagnosis": diagnosis,
        "amount_paise": case.get("amount_paise"),
        "error_reason": case.get("error_reason"),
        "tools": sorted(CLOSED_TOOLS),
    }
    last_error = None
    for model in models:
        for use_json in (True, False):
            try:
                body = {
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Propose one recovery tool as JSON "
                                '{"action": "...", "reason": "..."}. '
                                "Pick only from the allowlist. You do not execute anything."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(payload, default=str),
                        },
                    ],
                }
                if use_json:
                    body["response_format"] = {"type": "json_object"}
                response = httpx.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "content-type": "application/json",
                    },
                    json=body,
                    timeout=ADVISOR_TIMEOUT_S,
                )
                if response.status_code in {401, 403}:
                    log.warning("advisor auth failed, playbook keeps the tool")
                    return None
                if response.status_code in {429, 500, 502, 503}:
                    log.warning("advisor %s on %s, playbook keeps the tool", response.status_code, model)
                    return None
                if response.status_code in {400, 404, 422}:
                    last_error = f"{response.status_code} {model} json={use_json}"
                    continue
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = _extract_json(content)
                if parsed is not None:
                    return parsed
                last_error = "unreadable_json"
            except httpx.TimeoutException:
                log.warning("advisor timeout, playbook keeps the tool")
                return None
            except httpx.ConnectError:
                log.warning("advisor unreachable, playbook keeps the tool")
                return None
            except Exception as exc:  # noqa: BLE001
                log.warning("advisor %s, playbook keeps the tool", type(exc).__name__)
                return None
    if last_error:
        log.warning("advisor gave up: %s", last_error)
    return None


def filter_proposal(proposal: dict | None) -> dict | None:
    if not proposal:
        return None
    if proposal.get("action") not in CLOSED_TOOLS:
        return None
    out: dict = {"action": proposal["action"]}
    if proposal.get("reason"):
        out["reason"] = str(proposal["reason"])
    return out
