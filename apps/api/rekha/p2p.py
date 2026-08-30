from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from rekha.clocks import as_ist

PTPState = Literal[
    "Open",
    "Reminded",
    "Kept",
    "PartiallyKept",
    "Broken",
    "Cancelled",
    "Renegotiated",
]

GRACE_DAYS = 2


@dataclass
class Instalment:
    seq: int
    amount_paise: int
    date: str
    state: PTPState = "Open"


@dataclass
class PromiseToPay:
    id: str
    customer_id: str
    case_id: str
    promised_amount_paise: int
    promised_date: str
    instalments: list[Instalment] = field(default_factory=list)
    channel_captured: str = "whatsapp"
    evidence_ref: str = ""
    promiser_authority: str = "unknown"
    unstated_condition: str | None = None
    state: PTPState = "Open"
    parent_promise_id: str | None = None
    ladder_effect: str = "PAUSE_DUNNING_UNTIL"

    def to_dict(self) -> dict:
        return asdict(self)

    def remind(self) -> None:
        if self.state == "Open":
            self.state = "Reminded"


def remind_if_open(promise: PromiseToPay) -> None:
    promise.remind()


def evaluate_promise(promise: PromiseToPay, received_paise: int, today: str, *, apply_instalments: list[tuple[str, int]] | None = None) -> PromiseToPay:
    """Instalment-aware evaluation. Instalments land as (date, amount) pairs;
    a promise is Kept only when every instalment is paid."""
    if promise.state in {"Cancelled", "Renegotiated"}:
        return promise
    paid_by_date = dict(apply_instalments or [])
    all_paid = True
    any_paid = False
    for inst in promise.instalments:
        landed = paid_by_date.get(inst.date, 0)
        if landed >= inst.amount_paise:
            inst.state = "Kept"
            any_paid = True
        elif landed > 0:
            inst.state = "PartiallyKept"
            any_paid = True
            all_paid = False
        elif today > inst.date:
            inst.state = "Broken"
            all_paid = False
        else:
            all_paid = False
    if promise.instalments:
        if all_paid:
            promise.state = "Kept"
            return promise
        if any(inst.state == "Broken" for inst in promise.instalments):
            promise.state = "Broken"
            return promise
        if any_paid and today > promise.promised_date:
            promise.state = "PartiallyKept"
            return promise
    if received_paise >= promise.promised_amount_paise:
        promise.state = "Kept"
        return promise
    if received_paise > 0:
        promise.state = "PartiallyKept"
        return promise
    grace = _shift(promise.promised_date, GRACE_DAYS)
    if today > grace and promise.state not in {"Kept", "PartiallyKept"}:
        promise.state = "Broken"
    return promise


def _shift(iso_date: str, days: int) -> str:
    from datetime import date as _date

    return (_date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def renegotiate(old: PromiseToPay, new_date: str, new_amount: int, new_id: str) -> PromiseToPay:
    old.state = "Renegotiated"
    return PromiseToPay(
        id=new_id,
        customer_id=old.customer_id,
        case_id=old.case_id,
        promised_amount_paise=new_amount,
        promised_date=new_date,
        channel_captured=old.channel_captured,
        evidence_ref=old.evidence_ref,
        parent_promise_id=old.id,
        promiser_authority=old.promiser_authority,
        unstated_condition=old.unstated_condition,
    )


def freeze_active(promise: PromiseToPay | dict | None, now: datetime) -> bool:
    """Dunning stays paused until promised_date + grace (in IST)."""
    if not promise:
        return False
    if isinstance(promise, dict):
        state = promise.get("state")
        promised_date = promise.get("promised_date")
    else:
        state = promise.state
        promised_date = promise.promised_date
    if state not in {"Open", "Reminded"}:
        return False
    if not promised_date:
        return False
    horizon = _shift(promised_date, GRACE_DAYS)
    return as_ist(now).date().isoformat() <= horizon
