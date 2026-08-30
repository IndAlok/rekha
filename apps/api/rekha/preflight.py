from __future__ import annotations

from dataclasses import dataclass

from rekha import constants


@dataclass
class Preflight:
    ok: bool
    reason: str | None
    recommended_action: str | None


def preflight(case: dict) -> Preflight:
    mandate = case.get("mandate") or {}
    amount = int(case.get("amount_paise") or 0)
    if mandate.get("state") in {"revoked", "paused", "expired"} or mandate.get("expired"):
        return Preflight(False, "mandate_not_presentable", "create_payment_link")
    max_amount = mandate.get("max_amount")
    if max_amount is not None and amount > int(max_amount):
        return Preflight(False, "amount_exceeds_mandate_max", "create_payment_link")
    category = mandate.get("category") or case.get("mcc_category")
    if category in constants.AFA_1L_CATEGORIES:
        # Exempt categories get a higher AFA-free ceiling, not an infinite one.
        if amount > constants.AFA_1L_CEILING_PAISE:
            return Preflight(False, "above_1l_exempt_ceiling", "create_payment_link")
    elif amount > constants.AFA_FREE_PAISE:
        return Preflight(False, "afa_required_silent_debit_will_fail", "create_payment_link")
    return Preflight(True, None, None)
