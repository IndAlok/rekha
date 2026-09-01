from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rekha import constants

IST = ZoneInfo("Asia/Kolkata")


def as_ist(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def local_hour(ts: datetime) -> int:
    return as_ist(ts).hour


def in_contact_window(ts: datetime) -> bool:
    return constants.CONTACT_WINDOW_START <= local_hour(ts) < constants.CONTACT_WINDOW_END


def next_window_open(ts: datetime, hour: int | None = None) -> datetime:
    local = as_ist(ts)
    target = constants.CONTACT_WINDOW_START if hour is None else hour
    candidate = local.replace(hour=target, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def in_upi_peak(ts: datetime) -> bool:
    local = as_ist(ts)
    minutes = local.hour * 60 + local.minute
    for start, end in constants.UPI_PEAK_WINDOWS:
        if start <= minutes < end:
            return True
    return False


def _at_minutes(day: datetime, minutes: int) -> datetime:
    return day.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)


def next_upi_offpeak(ts: datetime) -> datetime:
    """Next moment system-initiated UPI execution is allowed (outside both peaks)."""
    local = as_ist(ts)
    if not in_upi_peak(local):
        return local
    minutes = local.hour * 60 + local.minute
    candidates: list[datetime] = []
    for _start, end in constants.UPI_PEAK_WINDOWS:
        # the moment this peak ends
        target_day = local if end > minutes else local + timedelta(days=1)
        candidates.append(_at_minutes(target_day, end % 1440))
    for start, _end in constants.UPI_PEAK_WINDOWS:
        # or the next peak's start minus nothing. the window just before it opens
        target_day = local if start > minutes else local + timedelta(days=1)
        candidates.append(_at_minutes(target_day, start % 1440))
    return min(c for c in candidates if c > local)


def india_salary_windows(ts: datetime) -> bool:
    """Salary-window days. 1 to 5, 25 to month end."""
    d = as_ist(ts).day
    return d in {1, 2, 3, 4, 5} or d >= 25


def next_salary_window(ts: datetime) -> datetime:
    """3 to 5 days out, weekday, salary-window day, dispatched off-peak (14:00 IST)."""
    local = as_ist(ts)
    probe = (local + timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0)
    for _ in range(3):  # days 3, 4, 5 only. never drift to +40 days
        if india_salary_windows(probe) and probe.weekday() < 5:
            return probe
        probe += timedelta(days=1)
    return (local + timedelta(days=5)).replace(hour=14, minute=0, second=0, microsecond=0)


def next_ist_midnight(ts: datetime) -> datetime:
    local = as_ist(ts)
    return (local + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)


def nach_gap_elapsed_days(last_return_at: datetime | None, now: datetime) -> float | None:
    """Days since the last NACH return, if known. None means unknown (fail-closed upstream)."""
    if last_return_at is None:
        return None
    return (as_ist(now) - as_ist(last_return_at)).total_seconds() / 86400
