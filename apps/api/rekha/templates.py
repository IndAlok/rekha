"""DLT templates. The model does not write SMS."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from rekha import constants
from rekha.compliance import ScanResult, scan_copy


@dataclass(frozen=True)
class Template:
    template_id: str
    channel: str
    category: str
    body: str
    slots: tuple[str, ...]
    url_allowed: bool = True


TEMPLATES = {
    "svc_pay_link_sms": Template(
        "svc_pay_link_sms",
        "sms",
        "service_implicit",
        "Payment of INR {amount} for {ref} is pending. Pay securely: {url}",
        ("amount", "ref", "url"),
    ),
    "svc_card_update_sms": Template(
        "svc_card_update_sms",
        "sms",
        "service_implicit",
        "Your {issuer} card ending {last4} could not be charged. Update method: {url}",
        ("issuer", "last4", "url"),
    ),
    "svc_pay_link_email": Template(
        "svc_pay_link_email",
        "email",
        "service_implicit",
        "Payment of INR {amount} for {ref} is pending. Pay securely: {url}",
        ("amount", "ref", "url"),
    ),
    "svc_card_update_email": Template(
        "svc_card_update_email",
        "email",
        "service_implicit",
        "Your {issuer} card ending {last4} could not be charged. Update your payment method: {url}",
        ("issuer", "last4", "url"),
    ),
    "svc_invoice_email": Template(
        "svc_invoice_email",
        "email",
        "service_implicit",
        "Invoice {ref} for INR {amount} is unpaid. Statement attached. Pay: {url}",
        ("ref", "amount", "url"),
    ),
    "svc_msme_email": Template(
        "svc_msme_email",
        "email",
        "service_implicit",
        "Invoice {ref} for INR {amount} is past due (due {date}). Delayed-payment interest of INR {interest} has accrued. Pay: {url}",
        ("ref", "amount", "date", "interest", "url"),
    ),
    "svc_cart_wa": Template(
        "svc_cart_wa",
        "whatsapp",
        "utility",
        "You left items in checkout at {merchant}. Resume here: {url}",
        ("merchant", "url"),
    ),
    "svc_pdn_sms": Template(
        "svc_pdn_sms",
        "sms",
        "service_implicit",
        "Autopay of INR {amount} is scheduled on {date}. Ensure balance. Ref {ref}",
        ("amount", "date", "ref"),
    ),
    "svc_ptp_remind": Template(
        "svc_ptp_remind",
        "email",
        "service_implicit",
        "Reminder: you promised to pay INR {amount} by {date}. Link: {url}",
        ("amount", "date", "url"),
    ),
    "svc_voice_pay": Template(
        "svc_voice_pay",
        "voice",
        "service",
        "Aapka INR {amount} payment pending hai. Secure link: {url}",
        ("amount", "url"),
    ),
    "eng_class_b": Template(
        "eng_class_b",
        "internal",
        "ops",
        "Class B failure {reason} on {ref}. Do not contact customer. Fix integration.",
        ("reason", "ref"),
    ),
}

DEV_URL_HOSTS = ("localhost", "rekha.test", "127.0.0.1")


def url_whitelisted(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    from rekha.config import settings

    allowed = list(constants.URL_WHITELIST)
    if settings.rekha_env == "dev":
        allowed += list(DEV_URL_HOSTS)
    for entry in allowed:
        entry = entry.lower()
        if host == entry or host.endswith("." + entry):
            return True
    return False


def render(template_id: str, values: dict[str, str], *, channel: str | None = None) -> tuple[str, ScanResult]:
    tmpl = TEMPLATES[template_id]
    for slot in tmpl.slots:
        val = values.get(slot, "")
        if len(val) > constants.VARIABLE_MAX_CHARS:
            raise ValueError(f"slot {slot} exceeds {constants.VARIABLE_MAX_CHARS} chars")
    body = tmpl.body.format(**{k: values.get(k, "") for k in tmpl.slots})
    if "url" in tmpl.slots:
        url = values.get("url", "")
        if url and not url_whitelisted(url):
            raise ValueError("url_not_whitelisted")
    scan = scan_copy(body, channel=channel or tmpl.channel)
    return body, scan
