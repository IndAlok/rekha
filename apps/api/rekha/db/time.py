"""UTC-aware datetimes only. psycopg3 cannot bind naive values to timestamptz
and cannot bind aware values to timestamp without time zone."""

from __future__ import annotations

from datetime import UTC, date, datetime


def as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def maybe_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return as_utc(ts)


def coerce_utc(value) -> datetime | None:
    """datetime, date, or ISO string to UTC-aware datetime. None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return as_utc(datetime.fromisoformat(raw))
    raise TypeError(f"expected datetime, got {type(value).__name__}")
