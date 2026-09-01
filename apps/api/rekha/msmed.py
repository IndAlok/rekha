"""MSMED Act arithmetic for B2B receivables.

s.15: payment due within the agreed period, capped at 45 days from
acceptance (15 days when nothing is agreed). s.16: on failure, compound
interest with monthly rests at three times the RBI Bank Rate . 
notwithstanding anything in any agreement. s.43B(h) (Income Tax): sums
payable to a micro/small enterprise beyond the s.15 window are deductible
only in the year actually paid. the buyer's own tax exposure.

The agent computes and states facts. It never drafts legal notices and
never implies criminal liability (see COMPLIANCE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

BANK_RATE_ANNUAL = 0.065  # RBI Bank Rate as config-of-record; fetch live in production
MULTIPLE = 3.0
MAX_AGREED_DAYS = 45
DEFAULT_DAYS = 15


@dataclass
class MsmedPosition:
    due_date: date
    days_past_due: int
    interest_paise: int
    tax_disallowance_paise: int
    eligible: bool
    reason: str | None = None


def due_date(acceptance_date: date, agreed_days: int | None) -> date:
    from datetime import timedelta

    if agreed_days is None:
        return acceptance_date + timedelta(days=DEFAULT_DAYS)
    # Contract terms longer than 45 days are void to that extent.
    return acceptance_date + timedelta(days=min(agreed_days, MAX_AGREED_DAYS))


def compute_position(
    *,
    acceptance_date: date,
    today: date,
    amount_paise: int,
    agreed_days: int | None = None,
    supplier_msme: bool = True,
    financial_year_end: date | None = None,
) -> MsmedPosition:
    if not supplier_msme:
        return MsmedPosition(due_date(acceptance_date, agreed_days), 0, 0, 0, False, "msmed_benefits_require_micro_or_small_classification")
    dd = due_date(acceptance_date, agreed_days)
    dpd = (today - dd).days
    months = max(0.0, dpd / 30.0)
    monthly = BANK_RATE_ANNUAL * MULTIPLE / 12.0
    # compound interest, monthly rests
    interest = amount_paise * ((1.0 + monthly) ** months - 1.0)
    disallowance = amount_paise if dpd > 0 and financial_year_end and today <= financial_year_end else 0
    return MsmedPosition(dd, max(0, dpd), int(interest), int(disallowance), True, None)
