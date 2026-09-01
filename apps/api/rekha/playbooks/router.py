from __future__ import annotations

from rekha.diagnose import Diagnosis
from rekha.playbooks.awaaz import propose_voice
from rekha.playbooks.cart import propose_cart
from rekha.playbooks.chaser import propose_b2b, propose_legal_refuse
from rekha.playbooks.doctor import propose_class_b, propose_downtime, propose_payment
from rekha.playbooks.saver import propose_subscription
from rekha.playbooks.sequencer import propose_holiday, propose_mandate, propose_preflight_fail
from rekha.playbooks.tracker import propose_promise
from rekha.preflight import Preflight
from rekha.taxonomy import Recoverability


def propose(case: dict, diagnosis: Diagnosis, preflight: Preflight, now) -> dict:
    if case.get("prefer_voice") and case.get("voice_consent"):
        return propose_voice()
    if case.get("bank_holiday") and case.get("loss_class") == "mandate_retry":
        return propose_holiday()
    if case.get("downtime_active") and diagnosis.recoverability_class == Recoverability.R:
        return propose_downtime()
    if case.get("requested_legal_step"):
        return propose_legal_refuse()
    if diagnosis.recoverability_class == Recoverability.B:
        return propose_class_b()
    if not preflight.ok:
        return propose_preflight_fail(preflight.reason)

    loss = case.get("loss_class")
    if loss == "checkout_abandonment":
        return propose_cart(case)
    if loss == "subscription_failure":
        return propose_subscription(case, diagnosis)
    if loss == "mandate_retry":
        return propose_mandate(case, diagnosis, now)
    if loss == "b2b_receivable":
        return propose_b2b(case)
    if loss == "promise_to_pay":
        return propose_promise(case)
    return propose_payment(case, diagnosis, now)
