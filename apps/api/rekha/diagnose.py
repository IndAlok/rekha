from __future__ import annotations

from dataclasses import asdict, dataclass, field

from rekha.taxonomy import Recoverability, classify, needs_reconcile_first


@dataclass
class Diagnosis:
    recoverability_class: Recoverability
    root_cause: str
    error_reason: str
    error_source: str | None
    customer_action_required: bool
    reconcile_first: bool
    confidence: float
    evidence: list[str] = field(default_factory=list)
    human_summary: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recoverability_class"] = str(self.recoverability_class)
        return d


SUMMARIES = {
    Recoverability.R: "Transient infrastructure fault. Silent retry on the same instrument after backoff, then fail over.",
    Recoverability.T: "Terminal reject. Never retry this instrument. Close or write off.",
    Recoverability.C: "Customer can fix this (funds, OTP, approval). Do not silent-retry immediately.",
    Recoverability.I: "Instrument is unusable. Drive an update-method / new-mandate session.",
    Recoverability.B: "Merchant or integration defect. Alert engineering. Never contact the customer.",
}


def diagnose(event: dict) -> Diagnosis:
    reason = event.get("error_reason") or event.get("reason") or ""
    source = event.get("error_source") or event.get("source")
    klass = classify(reason, source)
    if event.get("loss_class") == "checkout_abandonment" and not reason:
        klass = Recoverability.C
        reason = reason or "checkout_abandoned"
    if event.get("already_paid"):
        klass = Recoverability.T
        reason = "order_already_paid"
    recon = needs_reconcile_first(reason)
    return Diagnosis(
        recoverability_class=klass,
        root_cause=reason or event.get("loss_class", "unknown"),
        error_reason=reason,
        error_source=source,
        customer_action_required=klass in {Recoverability.C, Recoverability.I},
        reconcile_first=recon,
        confidence=0.92 if reason else 0.55,
        evidence=[f"reason={reason}", f"source={source}", f"class={klass}"],
        human_summary=SUMMARIES[klass],
    )
